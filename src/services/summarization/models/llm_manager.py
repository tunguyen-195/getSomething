"""
LLM Manager - Singleton Pattern for Ollama
Lazy loading, optional usage (không gọi mặc định)
"""
import hashlib
import logging
import math
import requests
import json
import threading
import time
from pathlib import Path
from typing import Any, Optional, Dict, List

from src.core.config import settings
from src.services.investigation.chunk_planner import estimate_tokens
from .context_analysis import (
    CONTEXT_PROMPT_VERSION,
    build_context_prompt,
    normalize_simple_analysis,
    simple_analysis_failure,
)
from ..investigation_scenarios import (
    DEFAULT_INVESTIGATION_SCENARIO,
    InvestigationScenario,
)
from .openai_compatible_client import OpenAICompatibleClient, validate_local_base_url

logger = logging.getLogger(__name__)


ANALYSIS_MAX_COMPLETION_TOKENS = 4096
ANALYSIS_MIN_COMPLETION_TOKENS = 512
ANALYSIS_CONTEXT_SAFETY_RESERVE_TOKENS = 320
ANALYSIS_COMPLETION_SOURCE_RATIO = 0.35


def context_window_tokens_for_provider(provider: str) -> int:
    if provider == "llama_cpp_server":
        return int(settings.LLAMA_SERVER_CONTEXT_SIZE)
    return int(settings.OLLAMA_NUM_CTX)


def plan_one_call_context_budget(
    prompt: str,
    source_text: str,
    *,
    context_window_tokens: int,
    max_completion_tokens: int,
    min_completion_tokens: int,
    completion_source_ratio: float | None,
    safety_reserve_tokens: int,
    desired_completion_tokens: int | None = None,
) -> dict[str, int | float | str | bool]:
    """Plan a deterministic full-source prompt and one completion call."""

    if context_window_tokens < 1:
        raise ValueError("context_window_tokens must be positive")
    if not 1 <= min_completion_tokens <= max_completion_tokens:
        raise ValueError("completion token bounds are invalid")
    if desired_completion_tokens is None:
        if completion_source_ratio is None or completion_source_ratio <= 0:
            raise ValueError("completion_source_ratio must be positive")
    elif desired_completion_tokens < 1:
        raise ValueError("desired_completion_tokens must be positive")
    if safety_reserve_tokens < 0:
        raise ValueError("safety_reserve_tokens must be non-negative")

    prompt_tokens = estimate_tokens(prompt)
    source_tokens = estimate_tokens(source_text)
    framed_source = f"<transcript>\n{source_text}\n</transcript>"
    source_occurrence_count = prompt.count(framed_source) if source_text else 0
    resolved_desired_completion_tokens = min(
        max_completion_tokens,
        max(
            min_completion_tokens,
            desired_completion_tokens
            if desired_completion_tokens is not None
            else math.ceil(source_tokens * float(completion_source_ratio)),
        ),
    )
    available_completion_tokens = max(
        0,
        context_window_tokens - safety_reserve_tokens - prompt_tokens,
    )
    fits = available_completion_tokens >= min_completion_tokens
    completion_tokens = (
        min(resolved_desired_completion_tokens, available_completion_tokens)
        if fits
        else 0
    )
    return {
        "token_counter": "utf8-bytes-over-2.8-ceiling",
        "context_window_tokens": context_window_tokens,
        "prompt_token_estimate": prompt_tokens,
        "source_token_estimate": source_tokens,
        "desired_completion_tokens": resolved_desired_completion_tokens,
        "available_completion_tokens": available_completion_tokens,
        "completion_token_budget": completion_tokens,
        "safety_reserve_tokens": safety_reserve_tokens,
        "source_occurrence_count": source_occurrence_count,
        "full_transcript_included": source_occurrence_count >= 1,
        "fits_context_window": fits,
        "completion_budget_clamped": (
            fits and completion_tokens < resolved_desired_completion_tokens
        ),
    }


def _plan_analysis_context_budget(
    prompt: str,
    transcript: str,
    *,
    context_window_tokens: int,
) -> dict[str, int | float | str | bool]:
    """Plan a one-call budget without ever dropping transcript content."""

    return plan_one_call_context_budget(
        prompt,
        transcript,
        context_window_tokens=context_window_tokens,
        max_completion_tokens=ANALYSIS_MAX_COMPLETION_TOKENS,
        min_completion_tokens=ANALYSIS_MIN_COMPLETION_TOKENS,
        completion_source_ratio=ANALYSIS_COMPLETION_SOURCE_RATIO,
        safety_reserve_tokens=ANALYSIS_CONTEXT_SAFETY_RESERVE_TOKENS,
    )


def _analysis_config_fingerprint(
    *,
    provider: str,
    model_id: str | None,
    temperature: float,
    budget: dict[str, Any],
) -> str:
    material = {
        "provider": provider,
        "model_id": model_id,
        "seed": settings.LLM_SEED,
        "temperature": temperature,
        "prompt_version": CONTEXT_PROMPT_VERSION,
        "context_window_tokens": budget["context_window_tokens"],
        "completion_token_budget": budget["completion_token_budget"],
        "safety_reserve_tokens": budget["safety_reserve_tokens"],
        "token_counter": budget["token_counter"],
    }
    encoded = json.dumps(
        material,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class LLMManager:
    """
    Singleton manager for Ollama LLM
    Only loads when explicitly requested
    """
    _instance: Optional['LLMManager'] = None
    _initialized: bool = False
    _available_models: List[str] = []

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._session = requests.Session()
            self._session.trust_env = False
            # Default to the configured model while keeping a legacy fallback.
            self._default_model = (
                settings.DEFAULT_AI_MODEL
                if hasattr(settings, "DEFAULT_AI_MODEL")
                else "gpt-oss:latest"
            )
            self._last_model_used: str | None = None
            self._last_generation_metadata: dict[str, Any] | None = None
            self._generation_count = 0
            self._available_models_cached_at = 0.0
            self._availability_lock = threading.Lock()
            self._openai_client: OpenAICompatibleClient | None = None
            self._openai_client_key: tuple[
                str,
                str,
                str,
                str,
                str,
                int,
                float,
                bool,
            ] | None = None
            self._availability_provider: str | None = None
            self._initialized = True
            logger.info("[LLM_MANAGER] Initialized (lazy mode)")

    @staticmethod
    def _provider_name() -> str:
        return str(settings.LOCAL_LLM_PROVIDER).strip().casefold()

    def _get_openai_client(self) -> OpenAICompatibleClient:
        repository_root = Path(__file__).resolve().parents[4]
        configured_path = Path(settings.LLAMA_SERVER_MODEL_PATH)
        if not configured_path.is_absolute():
            configured_path = repository_root / configured_path
        expected_model_path = str(configured_path.resolve())
        manifest_path = repository_root / "config/models/qwen3-8b-q4_k_m.manifest.json"
        expected_model_sha256 = ""
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected_file = next(
                row
                for row in manifest["model"]["files"]
                if str(row.get("path") or "").endswith(".gguf")
            )
            expected_model_sha256 = str(expected_file["sha256"])
        except (OSError, ValueError, KeyError, StopIteration, TypeError) as exc:
            raise RuntimeError("Pinned llama-server model manifest is invalid") from exc
        key = (
            settings.LLAMA_SERVER_BASE_URL.rstrip("/"),
            settings.LLAMA_SERVER_MODEL,
            settings.LLAMA_SERVER_API_KEY,
            expected_model_path,
            expected_model_sha256,
            int(settings.LLAMA_SERVER_CONTEXT_SIZE),
            float(settings.LLM_HEALTH_CACHE_SECONDS),
            bool(settings.OFFLINE_STRICT),
        )
        if self._openai_client is None or self._openai_client_key != key:
            self._openai_client = OpenAICompatibleClient(
                base_url=key[0],
                default_model=key[1],
                api_key=key[2],
                health_cache_seconds=key[6],
                offline_strict=key[7],
                expected_model_path=key[3],
                expected_model_sha256=key[4],
                expected_context_size=key[5],
            )
            self._openai_client_key = key
        return self._openai_client

    @staticmethod
    def _ollama_base_url() -> str:
        return validate_local_base_url(
            settings.OLLAMA_BASE_URL,
            offline_strict=bool(settings.OFFLINE_STRICT),
        )

    @classmethod
    def _ollama_url(cls, path: str) -> str:
        return f"{cls._ollama_base_url()}/{path.lstrip('/')}"

    def check_availability(self, *, force_refresh: bool = False) -> bool:
        """Check the configured local inference provider."""
        provider = self._provider_name()
        if provider == "llama_cpp_server":
            client = self._get_openai_client()
            available = client.check_availability(force_refresh=force_refresh)
            self._available_models = client.get_available_models() if available else []
            self._available_models_cached_at = time.monotonic() if available else 0.0
            self._availability_provider = provider if available else None
            if not available:
                logger.warning(
                    "[LLM_MANAGER] llama-server not available at %s",
                    settings.LLAMA_SERVER_BASE_URL,
                )
            return available

        cache_seconds = max(0.0, float(settings.LLM_HEALTH_CACHE_SECONDS))
        if (
            not force_refresh
            and self._availability_provider == provider
            and self._available_models
            and time.monotonic() - self._available_models_cached_at <= cache_seconds
        ):
            return True
        try:
            with self._availability_lock:
                if (
                    not force_refresh
                    and self._availability_provider == provider
                    and self._available_models
                    and time.monotonic() - self._available_models_cached_at <= cache_seconds
                ):
                    return True
                response = self._session.get(
                    self._ollama_url("api/tags"),
                    timeout=2,
                    allow_redirects=False,
                )
                if response.status_code == 200:
                    data = response.json()
                    self._available_models = [
                        model["name"]
                        for model in data.get("models", [])
                        if isinstance(model, dict) and model.get("name")
                    ]
                    self._available_models_cached_at = time.monotonic()
                    self._availability_provider = provider
                    logger.info(
                        "[LLM_MANAGER] Available models: %s",
                        self._available_models,
                    )
                    return True
                self._available_models = []
                self._available_models_cached_at = 0.0
                self._availability_provider = None
        except Exception as e:
            self._available_models = []
            self._available_models_cached_at = 0.0
            self._availability_provider = None
            logger.warning(f"[LLM_MANAGER] Ollama not available: {e}")
        return False

    def get_available_models(self, *, force_refresh: bool = False) -> List[str]:
        """Get list of available models"""
        if force_refresh:
            self.check_availability(force_refresh=True)
        else:
            self.check_availability()
        return list(self._available_models)

    def select_best_model(self, preferred: str = None) -> str:
        """
        Select an installed model without silently overriding the configured default.
        """
        models = self.get_available_models()

        if not models:
            raise RuntimeError("No verified local LLM model is available")

        if self._provider_name() == "llama_cpp_server":
            configured = settings.LLAMA_SERVER_MODEL
            aliases = {None, "", "auto", "configured_api", "qwen3", "vistral"}
            if preferred in aliases or preferred == configured:
                if configured not in models:
                    raise RuntimeError(
                        f"Configured llama-server model {configured!r} is not loaded"
                    )
                return configured
            raise ValueError(
                f"Model {preferred!r} is not the configured llama-server alias "
                f"{configured!r}"
            )

        def resolve(candidate: str | None) -> str | None:
            if not candidate:
                return None
            if candidate in models:
                return candidate
            tagged = f"{candidate}:latest" if ":" not in candidate else candidate
            return tagged if tagged in models else None

        preferred_model = resolve(preferred)
        if preferred_model:
            return preferred_model
        aliases = {None, "", "auto", "configured_api", "qwen3", "vistral"}
        if preferred not in aliases:
            raise ValueError(
                f"Requested Ollama model {preferred!r} is not installed; available={models}"
            )

        configured_model = resolve(self._default_model)
        if configured_model:
            logger.info("[LLM_MANAGER] Selected configured model: %s", configured_model)
            return configured_model

        if settings.OFFLINE_STRICT:
            raise RuntimeError(
                f"Configured Ollama model {self._default_model!r} is not installed"
            )

        # Prefer instruction models that are fast and reliable at structured output.
        priority = [
            "speechintel-qwen3:8b-q4",
            "qwen3:8b",
            "qwen2.5:14b",
            "qwen2.5:7b",
            "llama3.1:8b",
            "gemma2:9b",
            "llama3.2:3b",
            "deepseek-coder:6.7b-instruct",
            "gpt-oss:latest"
        ]
        for model in priority:
            if model in models:
                logger.info(f"[LLM_MANAGER] Selected model: {model}")
                return model

        # Return first available
        selected = models[0]
        logger.info(f"[LLM_MANAGER] Using first available: {selected}")
        return selected

    def generate(
        self,
        prompt: str,
        model: str = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False,
        json_mode: bool = False,
        json_schema: dict[str, Any] | None = None,
    ) -> str:
        """
        Generate response from LLM

        Args:
            prompt: Input prompt
            model: Model name (None = auto-select best)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stream: Stream response

        Returns:
            Generated text
        """
        force_runtime_attestation = self._provider_name() == "llama_cpp_server"
        available = (
            self.check_availability(force_refresh=True)
            if force_runtime_attestation
            else self.check_availability()
        )
        if not available:
            raise Exception(f"Local LLM provider {self._provider_name()} is not available")

        if self._provider_name() == "llama_cpp_server":
            selected_model = self.select_best_model(model)
            result = self._get_openai_client().generate(
                prompt,
                model=selected_model,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
                json_mode=json_mode,
                json_schema=json_schema,
                seed=settings.LLM_SEED,
                connect_timeout=settings.LLM_CONNECT_TIMEOUT_SECONDS,
                read_timeout=settings.LLM_READ_TIMEOUT_SECONDS,
            )
            self._last_model_used = selected_model
            self._generation_count += 1
            self._last_generation_metadata = {
                **result.metadata,
                "generation_index": self._generation_count,
            }
            return result.text

        if model is None:
            model = self.select_best_model()
        self._last_model_used = model

        model_family = model.casefold()
        # Legacy Qwen3 templates understand /no_think. Qwen3.5 uses the explicit
        # Ollama `think` request field and may otherwise treat /no_think as content.
        if (
            "qwen3" in model_family
            and "qwen3.5" not in model_family
            and not prompt.lstrip().startswith("/no_think")
        ):
            prompt = f"/no_think\n{prompt}"

        logger.info(f"[LLM_MANAGER] Generating with model: {model}")

        try:
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": stream,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                    "num_ctx": settings.OLLAMA_NUM_CTX,
                    "seed": settings.LLM_SEED,
                },
                "keep_alive": settings.OLLAMA_KEEP_ALIVE,
            }
            if "qwen3" in model_family:
                payload["think"] = False
            if json_schema is not None:
                payload["format"] = json_schema
            elif json_mode:
                payload["format"] = "json"

            api_url = self._ollama_url("api/generate")
            logger.debug(
                "[LLM_MANAGER] Sending local request | model=%s | prompt_length=%s",
                model,
                len(prompt),
            )

            # Use longer timeout for large prompts
            # (connect timeout, read timeout) - 30s to connect, 300s (5min) to read
            # For very long transcripts, may need even longer
            connect_timeout = 30
            read_timeout = min(600, max(300, len(prompt) // 100))  # 5-10 min based on prompt length

            request_started = time.perf_counter()
            response = self._session.post(
                api_url,
                json=payload,
                timeout=(connect_timeout, read_timeout),
                stream=stream,
                allow_redirects=False,
            )

            if response.status_code == 200:
                if stream:
                    full_response = ""
                    first_token_seconds = None
                    final_data: dict[str, Any] = {}
                    done_received = False
                    try:
                        for line in response.iter_lines():
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                                raise RuntimeError(
                                    "Ollama returned a malformed streaming frame"
                                ) from exc
                            if not isinstance(data, dict):
                                raise RuntimeError(
                                    "Ollama returned a non-object streaming frame"
                                )
                            if data.get("error"):
                                raise RuntimeError(
                                    f"Ollama stream error: {data['error']}"
                                )
                            chunk = data.get("response", "")
                            if not isinstance(chunk, str):
                                raise RuntimeError(
                                    "Ollama returned a non-string response chunk"
                                )
                            if chunk and first_token_seconds is None:
                                first_token_seconds = (
                                    time.perf_counter() - request_started
                                )
                            full_response += chunk
                            if data.get("done") is True:
                                final_data = data
                                done_received = True
                                break
                    finally:
                        close = getattr(response, "close", None)
                        if callable(close):
                            close()
                    if not done_received:
                        raise RuntimeError("Ollama stream ended without done=true")
                    if not full_response.strip():
                        raise RuntimeError("Ollama returned an empty completion")
                    if final_data.get("done_reason") in {"length", "unload"}:
                        raise RuntimeError(
                            "Ollama completion was not safely finished: "
                            f"{final_data.get('done_reason')}"
                        )
                    self._record_generation_metadata(
                        final_data,
                        model=model,
                        wall_time_seconds=time.perf_counter() - request_started,
                        time_to_first_token_seconds=first_token_seconds,
                    )
                    return full_response
                else:
                    data = response.json()
                    if not isinstance(data, dict) or data.get("done") is not True:
                        raise RuntimeError(
                            "Ollama did not confirm a complete non-streaming response"
                        )
                    result = data.get("response", "")
                    if not isinstance(result, str) or not result.strip():
                        raise RuntimeError("Ollama returned an empty completion")
                    if data.get("done_reason") in {"length", "unload"}:
                        raise RuntimeError(
                            "Ollama completion was not safely finished: "
                            f"{data.get('done_reason')}"
                        )
                    self._record_generation_metadata(
                        data,
                        model=model,
                        wall_time_seconds=time.perf_counter() - request_started,
                    )
                    logger.debug(f"[LLM_MANAGER] Received response | length={len(result)}")
                    return result
            else:
                logger.error(
                    "[LLM_MANAGER] LLM API error | status=%s",
                    response.status_code,
                )
                raise RuntimeError(
                    f"LLM API error: status {response.status_code}"
                )

        except requests.exceptions.Timeout:
            logger.error(
                "[LLM_MANAGER] Request timeout | read_timeout_seconds=%s",
                read_timeout,
            )
            raise RuntimeError(
                f"LLM request timeout after {read_timeout}s. "
                "The prompt may be too long or Ollama is slow."
            ) from None
        except requests.exceptions.ConnectionError:
            logger.error("[LLM_MANAGER] Connection error")
            raise RuntimeError(
                f"Cannot connect to Ollama at {self._ollama_base_url()}"
            ) from None
        except Exception as e:
            logger.error(
                "[LLM_MANAGER] Generation failed | error_type=%s",
                type(e).__name__,
            )
            raise

    def _record_generation_metadata(
        self,
        data: dict[str, Any],
        *,
        model: str,
        wall_time_seconds: float,
        time_to_first_token_seconds: float | None = None,
    ) -> None:
        eval_duration = data.get("eval_duration") or 0
        eval_count = data.get("eval_count") or 0
        prompt_duration = data.get("prompt_eval_duration") or 0
        prompt_count = data.get("prompt_eval_count") or 0
        self._generation_count += 1
        self._last_generation_metadata = {
            "generation_index": self._generation_count,
            "model": data.get("model") or model,
            "created_at": data.get("created_at"),
            "done_reason": data.get("done_reason"),
            "wall_time_seconds": round(wall_time_seconds, 6),
            "time_to_first_token_seconds": round(time_to_first_token_seconds, 6)
            if time_to_first_token_seconds is not None
            else None,
            "total_duration_seconds": round((data.get("total_duration") or 0) / 1e9, 6),
            "load_duration_seconds": round((data.get("load_duration") or 0) / 1e9, 6),
            "prompt_eval_duration_seconds": round(prompt_duration / 1e9, 6),
            "eval_duration_seconds": round(eval_duration / 1e9, 6),
            "prompt_eval_count": prompt_count,
            "eval_count": eval_count,
            "prompt_tokens_per_second": round(
                prompt_count / (prompt_duration / 1e9),
                3,
            )
            if prompt_duration
            else None,
            "decode_tokens_per_second": round(
                eval_count / (eval_duration / 1e9),
                3,
            )
            if eval_duration
            else None,
            # Backward-compatible alias used by existing reports.
            "tokens_per_second": round(eval_count / (eval_duration / 1e9), 3)
            if eval_duration
            else None,
            "keep_alive": settings.OLLAMA_KEEP_ALIVE,
        }

    def get_last_generation_metadata(self) -> dict[str, Any] | None:
        """Return a copy of Ollama timing/token metadata for benchmark capture."""

        return dict(self._last_generation_metadata) if self._last_generation_metadata else None

    def get_generation_count(self) -> int:
        return self._generation_count

    def unload_model(self, model: str | None = None) -> bool:
        """Release provider-owned model state when the provider supports it."""

        if self._provider_name() == "llama_cpp_server":
            slept = self._get_openai_client().wait_for_sleep(
                timeout_seconds=settings.LLAMA_SERVER_SLEEP_WAIT_SECONDS,
            )
            if not slept:
                logger.error(
                    "[LLM_MANAGER] llama-server did not enter idle sleep; GPU handoff is unsafe"
                )
                return False
            self._last_model_used = None
            return True

        target = model or self._last_model_used
        if not target:
            return True
        try:
            response = self._session.post(
                self._ollama_url("api/generate"),
                json={"model": target, "stream": False, "keep_alive": 0},
                timeout=(3, 30),
                allow_redirects=False,
            )
            if response.status_code != 200:
                logger.warning(
                    "[LLM_MANAGER] Model unload failed | model=%s | status=%s",
                    target,
                    response.status_code,
                )
                return False
            if target == self._last_model_used:
                self._last_model_used = None
            logger.info("[LLM_MANAGER] Model unloaded | model=%s", target)
            return True
        except requests.RequestException as exc:
            logger.warning(
                "[LLM_MANAGER] Model unload request failed | model=%s | error=%s",
                target,
                type(exc).__name__,
            )
            return False

    def unload_last_model(self) -> bool:
        return self.unload_model(self._last_model_used)

    def analyze_context(
        self,
        text: str,
        model: str = None,
        additional_instructions: str = None,
        segments: list[dict] | None = None,
        source_metadata: dict | None = None,
        investigation_scenario: InvestigationScenario = DEFAULT_INVESTIGATION_SCENARIO,
    ) -> Dict:
        """Analyze the complete transcript with exactly one LLM generation call."""
        transcript_casefold = text.casefold()
        segment_labels = sorted(
            {
                str(label).strip()
                for segment in segments or []
                if isinstance(segment, dict)
                and (label := segment.get("speaker") or segment.get("speaker_id"))
                and str(label).strip()
            }
        )
        source_bound_speaker_labels = [
            label
            for label in segment_labels
            if label.casefold() in transcript_casefold
        ]
        prompt = build_context_prompt(
            text,
            additional_instructions=additional_instructions,
            investigation_scenario=investigation_scenario,
            source_bound_speaker_labels=source_bound_speaker_labels,
        )
        provider = self._provider_name()
        budget = _plan_analysis_context_budget(
            prompt,
            text,
            context_window_tokens=context_window_tokens_for_provider(provider),
        )
        if not budget["fits_context_window"]:
            logger.warning(
                "[LLM_MANAGER] Analysis context window exceeded | "
                "prompt_tokens=%s | context_window=%s",
                budget["prompt_token_estimate"],
                budget["context_window_tokens"],
            )
            failure = simple_analysis_failure(
                "ANALYSIS_CONTEXT_WINDOW_EXCEEDED",
                "Toàn bộ bản ghi không vừa cửa sổ ngữ cảnh của mô hình; "
                "hệ thống không cắt bớt nội dung.",
            )
            failure["runtime"].update(budget)
            return failure

        try:
            # Prevent metadata from an earlier call being attributed to this run
            # when a provider or test double fails to publish fresh metadata.
            self._last_generation_metadata = None
            response = self.generate(
                prompt,
                model=model,
                temperature=0.0,
                max_tokens=int(budget["completion_token_budget"]),
                json_mode=False,
            )
        except Exception as exc:
            logger.error(
                "[LLM_MANAGER] Context generation failed | prompt_version=%s | error_type=%s",
                CONTEXT_PROMPT_VERSION,
                type(exc).__name__,
            )
            failure = simple_analysis_failure(
                "LLM_GENERATION_FAILED",
                "Không thể tạo nội dung phân tích từ mô hình.",
                llm_call_count=1,
            )
            failure["runtime"].update(budget)
            return failure

        result = normalize_simple_analysis(
            response,
            transcript=text,
            segments=segments,
            source_metadata=source_metadata,
        )
        generation_metadata = self.get_last_generation_metadata() or {}
        effective_model = (
            model
            or generation_metadata.get("model")
            or self._last_model_used
            or self._default_model
        )
        result["runtime"].update(
            {
                **budget,
                "provider": provider,
                "model_id": effective_model,
                "seed": settings.LLM_SEED,
                "temperature": 0.0,
                "speaker_signal": {
                    "source": "single_transcript_block",
                    "segment_label_count": len(segment_labels),
                    "source_bound_labels": source_bound_speaker_labels,
                    "attribution_supported": bool(source_bound_speaker_labels),
                },
                "config_fingerprint": _analysis_config_fingerprint(
                    provider=provider,
                    model_id=effective_model,
                    temperature=0.0,
                    budget=budget,
                ),
                "provider_generation_metadata": generation_metadata or None,
            }
        )
        logger.info(
            "[LLM_MANAGER] Context analysis complete | prompt_version=%s | status=%s",
            CONTEXT_PROMPT_VERSION,
            result.get("analysis_status"),
        )
        return result

    @classmethod
    def get_instance(cls) -> 'LLMManager':
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


# Global accessor
def get_llm_manager() -> LLMManager:
    """Get global LLM manager instance"""
    return LLMManager.get_instance()
