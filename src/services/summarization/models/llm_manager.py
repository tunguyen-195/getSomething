"""
LLM Manager - Singleton Pattern for Ollama
Lazy loading, optional usage (không gọi mặc định)
"""
import logging
import requests
import json
from typing import Any, Optional, Dict, List

from pydantic import ValidationError

from src.core.config import settings
from .context_analysis import (
    CONTEXT_PROMPT_VERSION,
    ContextAnalysisPayload,
    StructuredOutputError,
    build_context_prompt,
    context_analysis_failure,
    validate_context_analysis,
)
from .investigation_knowledge import build_grounded_context_analysis

logger = logging.getLogger(__name__)


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
            self._api_url = "http://localhost:11434/api/generate"
            # Default to gpt-oss:latest if available, otherwise fallback to gemma2:9b
            self._default_model = settings.DEFAULT_AI_MODEL if hasattr(settings, 'DEFAULT_AI_MODEL') else "gpt-oss:latest"
            self._last_model_used: str | None = None
            self._initialized = True
            logger.info(f"[LLM_MANAGER] Initialized (lazy mode)")

    def check_availability(self) -> bool:
        """Check if Ollama is running and available"""
        try:
            response = requests.get("http://localhost:11434/api/tags", timeout=2)
            if response.status_code == 200:
                data = response.json()
                self._available_models = [m['name'] for m in data.get('models', [])]
                logger.info(f"[LLM_MANAGER] Available models: {self._available_models}")
                return True
        except Exception as exc:
            logger.warning(
                "[LLM_MANAGER] Ollama unavailable | error_type=%s",
                type(exc).__name__,
            )
        return False

    def get_available_models(self) -> List[str]:
        """Get list of available models"""
        if not self._available_models:
            self.check_availability()
        return self._available_models

    def select_best_model(self, preferred: str = None) -> str:
        """
        Select best available model
        Priority: preferred > gpt-oss:20b > gpt-oss:latest > gemma2:9b > deepseek-r1:7b > first available
        """
        models = self.get_available_models()

        if not models:
            logger.warning("[LLM_MANAGER] No models available, using default")
            return self._default_model

        if preferred and preferred in models:
            return preferred

        # Priority list: DeepSeek R1 (Strongest), then others
        priority = [
            "deepseek-r1:8b",        # State-of-the-art Reasoning
            "gemma2:9b",             # High quality general model
            "llama3.1:8b",           # Meta's latest
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
        if not self.check_availability():
            raise Exception("Ollama is not available")

        if model is None:
            model = self.select_best_model()
        self._last_model_used = model

        logger.info(f"[LLM_MANAGER] Generating with model: {model}")

        try:
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": stream,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            }
            if json_schema is not None:
                payload["format"] = json_schema
            elif json_mode:
                payload["format"] = "json"

            logger.debug(f"[LLM_MANAGER] Sending request to {self._api_url} | model={model} | prompt_length={len(prompt)}")

            # Use longer timeout for large prompts
            # (connect timeout, read timeout) - 30s to connect, 300s (5min) to read
            # For very long transcripts, may need even longer
            connect_timeout = 30
            read_timeout = min(600, max(300, len(prompt) // 100))  # 5-10 min based on prompt length

            response = requests.post(
                self._api_url,
                json=payload,
                timeout=(connect_timeout, read_timeout),
                stream=stream
            )

            if response.status_code == 200:
                if stream:
                    # Handle streaming response
                    full_response = ""
                    for line in response.iter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                if 'response' in data:
                                    full_response += data['response']
                                if data.get('done', False):
                                    break
                            except json.JSONDecodeError:
                                continue
                    return full_response
                else:
                    # Handle single response
                    data = response.json()
                    result = data.get('response', '')
                    logger.debug(f"[LLM_MANAGER] Received response | length={len(result)}")
                    return result
            else:
                logger.error(
                    "[LLM_MANAGER] API error | status_code=%s",
                    response.status_code,
                )
                raise Exception(f"LLM API error: {response.status_code}")

        except requests.exceptions.Timeout:
            logger.error("[LLM_MANAGER] Request timeout")
            raise Exception(f"LLM request timeout after {read_timeout}s. The prompt may be too long or Ollama is slow.")
        except requests.exceptions.ConnectionError:
            logger.error("[LLM_MANAGER] Connection error")
            raise Exception("Cannot connect to Ollama. Please ensure Ollama is running on localhost:11434")
        except Exception as exc:
            logger.error(
                "[LLM_MANAGER] Generation failed | error_type=%s",
                type(exc).__name__,
            )
            raise

    def analyze_context(
        self,
        text: str,
        model: str = None,
        additional_instructions: str = None,
        segments: list[dict] | None = None,
        source_metadata: dict | None = None,
    ) -> Dict:
        """Generate, validate, ground, and revalidate investigation context."""

        prompt = build_context_prompt(
            text,
            additional_instructions=additional_instructions,
        )
        try:
            response = self.generate(
                prompt,
                model=model,
                temperature=0.2,
                json_mode=True,
                json_schema=ContextAnalysisPayload.model_json_schema(),
            )
        except Exception as exc:
            logger.error(
                "[LLM_MANAGER] Context generation failed | prompt_version=%s | error_type=%s",
                CONTEXT_PROMPT_VERSION,
                type(exc).__name__,
            )
            return context_analysis_failure(
                "LLM_GENERATION_FAILED",
                "The context model did not produce a response.",
            )

        try:
            parsed = validate_context_analysis(response)
        except (StructuredOutputError, ValidationError):
            logger.warning(
                "[LLM_MANAGER] Context response rejected | prompt_version=%s",
                CONTEXT_PROMPT_VERSION,
            )
            return context_analysis_failure(
                "INVALID_STRUCTURED_OUTPUT",
                "The model response was not valid investigation JSON.",
            )

        effective_model = self._last_model_used or model or self._default_model
        try:
            grounded = build_grounded_context_analysis(
                parsed,
                text,
                segments,
                model_id=effective_model,
                source_metadata=source_metadata,
            )
        except Exception:
            logger.exception(
                "[LLM_MANAGER] Knowledge grounding failed | prompt_version=%s",
                CONTEXT_PROMPT_VERSION,
            )
            return context_analysis_failure(
                "KNOWLEDGE_GROUNDING_FAILED",
                "The model output could not be grounded in transcript evidence.",
            )

        logger.info(
            "[LLM_MANAGER] Context analysis complete | prompt_version=%s | fields=%s",
            CONTEXT_PROMPT_VERSION,
            len(grounded),
        )
        return grounded
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
