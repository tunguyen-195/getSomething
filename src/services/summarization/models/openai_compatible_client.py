"""Small OpenAI-compatible client for the repository-local llama-server."""

from __future__ import annotations

import hashlib
import json
import ipaddress
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import requests


class OpenAICompatibleError(RuntimeError):
    """Raised when the local inference server returns an unusable response."""


def validate_local_base_url(base_url: str, *, offline_strict: bool) -> str:
    """Reject endpoints that could send sensitive transcripts off-host."""

    normalized = base_url.rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme != "http" or not parsed.hostname:
        raise ValueError("Local LLM base URL must use plain HTTP with a hostname")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Local LLM base URL cannot contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("Local LLM base URL cannot contain an API path")
    if offline_strict:
        host = parsed.hostname.casefold()
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            raise ValueError(
                "OFFLINE_STRICT requires a literal loopback IP for the local LLM endpoint"
            )
    return normalized


@dataclass(frozen=True)
class OpenAICompatibleResult:
    text: str
    metadata: dict[str, Any]


class OpenAICompatibleClient:
    """Talk to a loopback OpenAI-compatible server without an SDK dependency."""

    def __init__(
        self,
        *,
        base_url: str,
        default_model: str,
        api_key: str = "",
        health_cache_seconds: float = 10.0,
        offline_strict: bool = True,
        expected_model_path: str | None = None,
        expected_model_sha256: str | None = None,
        expected_context_size: int | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = validate_local_base_url(
            base_url,
            offline_strict=offline_strict,
        )
        self.default_model = default_model
        self.api_key = api_key
        self.expected_model_path = (
            os.path.normcase(os.path.abspath(expected_model_path))
            if expected_model_path
            else None
        )
        self.expected_model_sha256 = (
            expected_model_sha256.casefold() if expected_model_sha256 else None
        )
        if expected_context_size is not None and int(expected_context_size) < 1:
            raise ValueError("Expected llama-server context size must be positive")
        self.expected_context_size = (
            int(expected_context_size) if expected_context_size is not None else None
        )
        self.health_cache_seconds = max(0.0, float(health_cache_seconds))
        self.session = session or requests.Session()
        self.session.trust_env = False
        self._models: list[str] = []
        self._healthy_at = 0.0
        self._props: dict[str, Any] = {}
        self._verified_model_stat: tuple[int, int] | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _response_error(response: requests.Response) -> str:
        return f"OpenAI-compatible API error: status {response.status_code}"

    def check_availability(self, *, force_refresh: bool = False) -> bool:
        if not self._verify_expected_model_file():
            self._models = []
            self._healthy_at = 0.0
            self._props = {}
            return False
        if (
            not force_refresh
            and self._models
            and time.monotonic() - self._healthy_at <= self.health_cache_seconds
        ):
            return True

        try:
            health = self.session.get(
                f"{self.base_url}/health",
                headers=self._headers(),
                timeout=2,
                allow_redirects=False,
            )
            if health.status_code != 200:
                self._models = []
                self._healthy_at = 0.0
                return False

            response = self.session.get(
                f"{self.base_url}/v1/models",
                headers=self._headers(),
                timeout=5,
                allow_redirects=False,
            )
            if response.status_code != 200:
                self._models = []
                self._healthy_at = 0.0
                return False
            payload = response.json()
            self._models = [
                str(row["id"])
                for row in payload.get("data", [])
                if isinstance(row, dict) and row.get("id")
            ]
            if self.default_model not in self._models:
                self._models = []
                self._healthy_at = 0.0
                return False
            if self.expected_model_path or self.expected_context_size is not None:
                props_response = self.session.get(
                    f"{self.base_url}/props",
                    headers=self._headers(),
                    timeout=5,
                    allow_redirects=False,
                )
                if props_response.status_code != 200:
                    self._models = []
                    self._healthy_at = 0.0
                    return False
                self._props = props_response.json()
                if self.expected_model_path:
                    observed_path = self._props.get("model_path")
                    if not observed_path or os.path.normcase(
                        os.path.abspath(str(observed_path))
                    ) != self.expected_model_path:
                        self._models = []
                        self._healthy_at = 0.0
                        self._props = {}
                        return False
            if self.expected_context_size is not None:
                if not self._context_binding_matches(payload):
                    self._models = []
                    self._healthy_at = 0.0
                    self._props = {}
                    return False
            self._healthy_at = time.monotonic() if self._models else 0.0
            return bool(self._models)
        except (requests.RequestException, ValueError, TypeError):
            self._models = []
            self._healthy_at = 0.0
            self._props = {}
            return False

    def _context_binding_matches(self, models_payload: dict[str, Any]) -> bool:
        expected = self.expected_context_size
        if expected is None:
            return True

        defaults = self._props.get("default_generation_settings")
        if not isinstance(defaults, dict):
            return False
        observed_props = defaults.get("n_ctx")
        if observed_props is None and isinstance(defaults.get("params"), dict):
            observed_props = defaults["params"].get("n_ctx")
        if observed_props != expected:
            return False

        model_row = next(
            (
                row
                for row in models_payload.get("data", [])
                if isinstance(row, dict) and str(row.get("id")) == self.default_model
            ),
            None,
        )
        if not isinstance(model_row, dict) or not isinstance(model_row.get("meta"), dict):
            return False
        model_meta = model_row["meta"]
        if model_meta.get("n_ctx") != expected:
            return False
        n_ctx_train = model_meta.get("n_ctx_train")
        if not isinstance(n_ctx_train, int) or n_ctx_train < expected:
            return False

        slots_response = self.session.get(
            f"{self.base_url}/slots",
            headers=self._headers(),
            timeout=5,
            allow_redirects=False,
        )
        if slots_response.status_code != 200:
            return False
        slots = slots_response.json()
        if not isinstance(slots, list) or len(slots) != 1:
            return False
        return all(
            isinstance(slot, dict) and slot.get("n_ctx") == expected
            for slot in slots
        )

    def _verify_expected_model_file(self) -> bool:
        if not self.expected_model_path or not self.expected_model_sha256:
            return True
        try:
            stat = os.stat(self.expected_model_path)
            signature = (stat.st_size, stat.st_mtime_ns)
            if signature == self._verified_model_stat:
                return True
            digest = hashlib.sha256()
            with open(self.expected_model_path, "rb") as handle:
                for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest().casefold() != self.expected_model_sha256:
                self._verified_model_stat = None
                return False
            self._verified_model_stat = signature
            return True
        except OSError:
            self._verified_model_stat = None
            return False

    def get_available_models(self, *, force_refresh: bool = False) -> list[str]:
        self.check_availability(force_refresh=force_refresh)
        return list(self._models)

    def wait_for_sleep(self, *, timeout_seconds: float, poll_seconds: float = 0.25) -> bool:
        """Wait until llama-server releases its model after the idle-sleep timeout."""

        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while True:
            try:
                response = self.session.get(
                    f"{self.base_url}/props",
                    headers=self._headers(),
                    timeout=3,
                    allow_redirects=False,
                )
                if response.status_code == 200 and bool(response.json().get("is_sleeping")):
                    self._healthy_at = 0.0
                    return True
            except (requests.RequestException, ValueError, TypeError):
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(max(0.01, poll_seconds), remaining))

    def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        stream: bool = False,
        json_mode: bool = False,
        json_schema: dict[str, Any] | None = None,
        seed: int | None = None,
        connect_timeout: float = 10.0,
        read_timeout: float = 600.0,
    ) -> OpenAICompatibleResult:
        selected_model = model or self.default_model
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
            # llama-server maps this to non-thinking generation for Qwen models.
            "reasoning_effort": "none",
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if seed is not None:
            payload["seed"] = seed
        if json_schema is not None:
            # llama.cpp b10331 enforces the schema only with the json_object form.
            payload["response_format"] = {
                "type": "json_object",
                "schema": json_schema,
            }
        elif json_mode:
            payload["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        try:
            response = self.session.post(
                f"{self.base_url}/v1/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=(connect_timeout, read_timeout),
                stream=stream,
                allow_redirects=False,
            )
        except requests.Timeout as exc:
            raise OpenAICompatibleError(
                f"Local LLM request timed out after {read_timeout:g}s"
            ) from exc
        except requests.ConnectionError as exc:
            raise OpenAICompatibleError(
                f"Cannot connect to local LLM server at {self.base_url}"
            ) from exc

        if response.status_code != 200:
            raise OpenAICompatibleError(self._response_error(response))

        if stream:
            return self._read_stream(
                response,
                model=selected_model,
                started=started,
            )

        try:
            data = response.json()
            text = self._message_text(data)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise OpenAICompatibleError(
                "Local LLM returned an invalid chat-completion response"
            ) from exc
        self._validate_response_model(data, selected_model)
        self._validate_completion(text, data)
        return OpenAICompatibleResult(
            text=text,
            metadata=self._metadata(
                data,
                model=selected_model,
                wall_time_seconds=time.perf_counter() - started,
            ),
        )

    def _read_stream(
        self,
        response: requests.Response,
        *,
        model: str,
        started: float,
    ) -> OpenAICompatibleResult:
        parts: list[str] = []
        first_token_seconds: float | None = None
        final_data: dict[str, Any] = {}
        done_received = False
        try:
            for raw_line in response.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                line = line.strip()
                if line.startswith("data:"):
                    line = line[5:].strip()
                if not line or line.startswith(":"):
                    continue
                if line == "[DONE]":
                    done_received = True
                    break
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise OpenAICompatibleError(
                        "Local LLM returned a malformed SSE frame"
                    ) from exc
                if isinstance(data.get("error"), dict):
                    raise OpenAICompatibleError("Local LLM stream error")
                choices = data.get("choices") or []
                if choices:
                    final_data = {**final_data, **data}
                else:
                    for key in ("usage", "timings", "model", "created"):
                        if key in data:
                            final_data[key] = data[key]
                content = self._delta_text(data)
                if content:
                    if first_token_seconds is None:
                        first_token_seconds = time.perf_counter() - started
                    parts.append(content)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

        text = "".join(parts)
        if not done_received:
            raise OpenAICompatibleError("Local LLM stream ended without [DONE]")
        self._validate_response_model(final_data, model)
        self._validate_completion(text, final_data)
        return OpenAICompatibleResult(
            text=text,
            metadata=self._metadata(
                final_data,
                model=model,
                wall_time_seconds=time.perf_counter() - started,
                time_to_first_token_seconds=first_token_seconds,
            ),
        )

    @staticmethod
    def _message_text(data: dict[str, Any]) -> str:
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict)
            )
        raise TypeError("unsupported message content")

    @staticmethod
    def _delta_text(data: dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return ""
        delta = choices[0].get("delta") or {}
        content = delta.get("content") if isinstance(delta, dict) else ""
        return content if isinstance(content, str) else ""

    @staticmethod
    def _validate_completion(text: str, data: dict[str, Any]) -> None:
        if not text.strip():
            raise OpenAICompatibleError("Local LLM returned an empty completion")
        choices = data.get("choices") or []
        finish_reason = (
            choices[0].get("finish_reason")
            if choices and isinstance(choices[0], dict)
            else None
        )
        if finish_reason in {"length", "content_filter"}:
            raise OpenAICompatibleError(
                f"Local LLM completion was not safely finished: {finish_reason}"
            )
        if finish_reason not in {"stop", "eos"}:
            raise OpenAICompatibleError(
                f"Local LLM did not confirm a complete response: {finish_reason}"
            )

    @staticmethod
    def _validate_response_model(data: dict[str, Any], requested_model: str) -> None:
        observed_model = data.get("model")
        if observed_model is not None and str(observed_model) != requested_model:
            raise OpenAICompatibleError(
                "Local LLM response model does not match the requested alias"
            )

    @staticmethod
    def _metadata(
        data: dict[str, Any],
        *,
        model: str,
        wall_time_seconds: float,
        time_to_first_token_seconds: float | None = None,
    ) -> dict[str, Any]:
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        timings = data.get("timings") if isinstance(data.get("timings"), dict) else {}
        prompt_tokens = usage.get("prompt_tokens") or timings.get("prompt_n")
        completion_tokens = usage.get("completion_tokens") or timings.get("predicted_n")
        prompt_rate = timings.get("prompt_per_second")
        decode_rate = timings.get("predicted_per_second")
        choices = data.get("choices") or []
        finish_reason = (
            choices[0].get("finish_reason")
            if choices and isinstance(choices[0], dict)
            else None
        )
        return {
            "provider": "openai_compatible",
            "model": data.get("model") or model,
            "created_at": data.get("created"),
            "done_reason": finish_reason,
            "wall_time_seconds": round(wall_time_seconds, 6),
            "time_to_first_token_seconds": (
                round(time_to_first_token_seconds, 6)
                if time_to_first_token_seconds is not None
                else None
            ),
            "prompt_eval_count": prompt_tokens,
            "eval_count": completion_tokens,
            "prompt_tokens_per_second": (
                round(float(prompt_rate), 3) if prompt_rate is not None else None
            ),
            "decode_tokens_per_second": (
                round(float(decode_rate), 3) if decode_rate is not None else None
            ),
            "tokens_per_second": (
                round(float(decode_rate), 3) if decode_rate is not None else None
            ),
            "server_timings": timings or None,
            "lifecycle": "external_server",
        }
