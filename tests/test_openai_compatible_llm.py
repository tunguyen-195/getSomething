from __future__ import annotations

import hashlib
import json

import pytest

from src.core.config import settings
from src.services.summarization.models.llm_manager import LLMManager
from src.services.summarization.models.openai_compatible_client import (
    OpenAICompatibleClient,
    OpenAICompatibleError,
    OpenAICompatibleResult,
)


class FakeResponse:
    def __init__(self, payload, *, status_code=200, lines=None):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)
        self._lines = lines or []
        self.closed = False

    def json(self):
        return self._payload

    def iter_lines(self):
        yield from self._lines

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self):
        self.posts = []

    def get(self, url, **_kwargs):
        if url.endswith("/health"):
            return FakeResponse({"status": "ok"})
        return FakeResponse(
            {"data": [{"id": "speechintel-qwen3-8b-q4_k_m"}]}
        )

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse(
            {
                "model": "speechintel-qwen3-8b-q4_k_m",
                "choices": [
                    {
                        "message": {"content": '{"summary":"hop le"}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5},
                "timings": {
                    "prompt_per_second": 40.0,
                    "predicted_per_second": 25.0,
                },
            }
        )


def test_llama_server_client_requests_schema_and_non_thinking():
    session = FakeSession()
    client = OpenAICompatibleClient(
        base_url="http://127.0.0.1:8088",
        default_model="speechintel-qwen3-8b-q4_k_m",
        session=session,
    )

    assert client.check_availability() is True
    result = client.generate(
        "PROMPT",
        json_schema={"type": "object", "required": ["summary"]},
        seed=42,
    )

    assert result.text == '{"summary":"hop le"}'
    assert result.metadata["prompt_tokens_per_second"] == 40.0
    assert result.metadata["decode_tokens_per_second"] == 25.0
    _, request = session.posts[0]
    payload = request["json"]
    assert payload["reasoning_effort"] == "none"
    assert payload["seed"] == 42
    assert payload["response_format"] == {
        "type": "json_object",
        "schema": {"type": "object", "required": ["summary"]},
    }


def test_llama_server_client_streams_sse_and_records_ttft():
    class StreamingSession(FakeSession):
        def post(self, url, **kwargs):
            self.posts.append((url, kwargs))
            return FakeResponse(
                {},
                lines=[
                    b'data: {"choices":[{"delta":{"content":"Xin"}}]}',
                    b'data: {"choices":[{"delta":{"content":" chao"}}]}',
                    b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
                    b"data: [DONE]",
                ],
            )

    client = OpenAICompatibleClient(
        base_url="http://127.0.0.1:8088",
        default_model="speechintel-qwen3-8b-q4_k_m",
        session=StreamingSession(),
    )

    result = client.generate("PROMPT", stream=True)

    assert result.text == "Xin chao"
    assert result.metadata["time_to_first_token_seconds"] is not None


@pytest.mark.parametrize("base_url", ["http://example.com", "http://localhost:8088"])
def test_offline_client_rejects_non_literal_loopback_endpoint(base_url):
    with pytest.raises(ValueError, match="literal loopback"):
        OpenAICompatibleClient(
            base_url=base_url,
            default_model="model",
            offline_strict=True,
        )


def test_client_disables_environment_proxies_and_redirects():
    session = FakeSession()
    client = OpenAICompatibleClient(
        base_url="http://127.0.0.1:8088",
        default_model="speechintel-qwen3-8b-q4_k_m",
        session=session,
    )

    client.generate("PROMPT")

    assert session.trust_env is False
    assert session.posts[0][1]["allow_redirects"] is False


def test_client_rejects_model_path_mismatch(tmp_path):
    class MismatchSession(FakeSession):
        def get(self, url, **_kwargs):
            if url.endswith("/health"):
                return FakeResponse({"status": "ok"})
            if url.endswith("/props"):
                return FakeResponse({"model_path": str(tmp_path / "rogue.gguf")})
            return FakeResponse(
                {"data": [{"id": "speechintel-qwen3-8b-q4_k_m"}]}
            )

    client = OpenAICompatibleClient(
        base_url="http://127.0.0.1:8088",
        default_model="speechintel-qwen3-8b-q4_k_m",
        expected_model_path=str(tmp_path / "expected.gguf"),
        session=MismatchSession(),
    )

    assert client.check_availability() is False


class ContextBoundSession(FakeSession):
    def __init__(
        self,
        *,
        props_context=12288,
        model_context=12288,
        train_context=40960,
        slot_contexts=(12288,),
    ):
        super().__init__()
        self.props_context = props_context
        self.model_context = model_context
        self.train_context = train_context
        self.slot_contexts = slot_contexts

    def get(self, url, **_kwargs):
        if url.endswith("/health"):
            return FakeResponse({"status": "ok"})
        if url.endswith("/props"):
            return FakeResponse(
                {"default_generation_settings": {"n_ctx": self.props_context}}
            )
        if url.endswith("/slots"):
            return FakeResponse(
                [
                    {"id": index, "n_ctx": context, "is_processing": False}
                    for index, context in enumerate(self.slot_contexts)
                ]
            )
        return FakeResponse(
            {
                "data": [
                    {
                        "id": "speechintel-qwen3-8b-q4_k_m",
                        "meta": {
                            "n_ctx": self.model_context,
                            "n_ctx_train": self.train_context,
                        },
                    }
                ]
            }
        )


def test_client_accepts_exact_context_binding_across_runtime_endpoints():
    client = OpenAICompatibleClient(
        base_url="http://127.0.0.1:8088",
        default_model="speechintel-qwen3-8b-q4_k_m",
        expected_context_size=12288,
        session=ContextBoundSession(),
    )

    assert client.check_availability() is True


@pytest.mark.parametrize(
    "session",
    [
        ContextBoundSession(props_context=8192),
        ContextBoundSession(props_context=16384),
        ContextBoundSession(props_context="12288"),
        ContextBoundSession(props_context=None),
        ContextBoundSession(model_context=8192),
        ContextBoundSession(train_context=8192),
        ContextBoundSession(slot_contexts=(8192,)),
        ContextBoundSession(slot_contexts=(12288, 12288)),
    ],
)
def test_client_rejects_context_binding_mismatch(session):
    client = OpenAICompatibleClient(
        base_url="http://127.0.0.1:8088",
        default_model="speechintel-qwen3-8b-q4_k_m",
        expected_context_size=12288,
        session=session,
    )

    assert client.check_availability() is False


def test_client_rejects_expected_model_sha256_mismatch(tmp_path):
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"unexpected model bytes")
    session = FakeSession()
    client = OpenAICompatibleClient(
        base_url="http://127.0.0.1:8088",
        default_model="speechintel-qwen3-8b-q4_k_m",
        expected_model_path=str(model_path),
        expected_model_sha256="0" * 64,
        session=session,
    )

    assert client.check_availability() is False


def test_client_rechecks_model_integrity_before_using_health_cache(tmp_path):
    model_path = tmp_path / "model.gguf"
    original = b"trusted model bytes"
    model_path.write_bytes(original)
    expected_sha256 = hashlib.sha256(original).hexdigest()

    class BoundSession(FakeSession):
        def get(self, url, **_kwargs):
            if url.endswith("/health"):
                return FakeResponse({"status": "ok"})
            if url.endswith("/props"):
                return FakeResponse({"model_path": str(model_path)})
            return super().get(url)

    client = OpenAICompatibleClient(
        base_url="http://127.0.0.1:8088",
        default_model="speechintel-qwen3-8b-q4_k_m",
        expected_model_path=str(model_path),
        expected_model_sha256=expected_sha256,
        health_cache_seconds=60,
        session=BoundSession(),
    )

    assert client.check_availability() is True
    model_path.write_bytes(b"tampered model bytes with different size")

    assert client.check_availability() is False


@pytest.mark.parametrize(
    "lines",
    [
        [b"data: not-json", b"data: [DONE]"],
        [b'data: {"choices":[{"delta":{"content":"partial"}}]}'],
        [
            b'data: {"choices":[{"delta":{"content":"partial"}}]}',
            b'data: {"choices":[{"delta":{},"finish_reason":"length"}]}',
            b"data: [DONE]",
        ],
    ],
)
def test_client_rejects_malformed_or_truncated_stream(lines):
    class BrokenSession(FakeSession):
        def post(self, url, **kwargs):
            self.posts.append((url, kwargs))
            return FakeResponse({}, lines=lines)

    client = OpenAICompatibleClient(
        base_url="http://127.0.0.1:8088",
        default_model="speechintel-qwen3-8b-q4_k_m",
        session=BrokenSession(),
    )

    with pytest.raises(OpenAICompatibleError):
        client.generate("PROMPT", stream=True)


def test_client_rejects_response_from_different_model_alias():
    class WrongModelSession(FakeSession):
        def post(self, url, **kwargs):
            response = super().post(url, **kwargs)
            response._payload["model"] = "rogue-model"
            return response

    client = OpenAICompatibleClient(
        base_url="http://127.0.0.1:8088",
        default_model="speechintel-qwen3-8b-q4_k_m",
        session=WrongModelSession(),
    )

    with pytest.raises(OpenAICompatibleError, match="requested alias"):
        client.generate("PROMPT")


def test_client_never_exposes_http_or_stream_error_bodies():
    secret = "SENSITIVE_TRANSCRIPT_FRAGMENT_0912345678"

    class ErrorSession(FakeSession):
        def post(self, url, **kwargs):
            self.posts.append((url, kwargs))
            return FakeResponse({"error": secret}, status_code=500)

    http_client = OpenAICompatibleClient(
        base_url="http://127.0.0.1:8088",
        default_model="speechintel-qwen3-8b-q4_k_m",
        session=ErrorSession(),
    )
    with pytest.raises(OpenAICompatibleError) as http_error:
        http_client.generate("PROMPT")

    stream_client = OpenAICompatibleClient(
        base_url="http://127.0.0.1:8088",
        default_model="speechintel-qwen3-8b-q4_k_m",
        session=FakeSession(),
    )
    response = FakeResponse(
        {},
        lines=[
            json.dumps({"error": {"message": secret}}).encode("utf-8"),
        ],
    )
    with pytest.raises(OpenAICompatibleError) as stream_error:
        stream_client._read_stream(response, model="model", started=0.0)

    assert secret not in str(http_error.value)
    assert secret not in str(stream_error.value)


def test_client_waits_for_idle_sleep_before_gpu_handoff():
    class SleepSession(FakeSession):
        def __init__(self):
            super().__init__()
            self.props_calls = 0

        def get(self, url, **_kwargs):
            if url.endswith("/props"):
                self.props_calls += 1
                return FakeResponse({"is_sleeping": self.props_calls >= 2})
            return super().get(url, **_kwargs)

    session = SleepSession()
    client = OpenAICompatibleClient(
        base_url="http://127.0.0.1:8088",
        default_model="speechintel-qwen3-8b-q4_k_m",
        session=session,
    )

    assert client.wait_for_sleep(timeout_seconds=1, poll_seconds=0.01) is True
    assert session.props_calls == 2


def test_llm_manager_routes_to_configured_llama_server(monkeypatch):
    manager = LLMManager()
    starting_count = manager.get_generation_count()
    calls = []

    class FakeClient:
        def check_availability(self, *, force_refresh=False):
            calls.append(("health", force_refresh))
            return True

        def get_available_models(self, *, force_refresh=False):
            return ["speechintel-qwen3-8b-q4_k_m"]

        def generate(self, prompt, **kwargs):
            calls.append((prompt, kwargs))
            return OpenAICompatibleResult(
                text="Ket qua",
                metadata={"provider": "openai_compatible", "model": kwargs["model"]},
            )

    monkeypatch.setattr(settings, "LOCAL_LLM_PROVIDER", "llama_cpp_server")
    monkeypatch.setattr(manager, "_get_openai_client", lambda: FakeClient())

    result = manager.generate("PROMPT", model=None, temperature=0.1)

    assert result == "Ket qua"
    assert manager.get_generation_count() == starting_count + 1
    assert manager.get_last_generation_metadata()["provider"] == "openai_compatible"
    assert calls[-1][1]["model"] == "speechintel-qwen3-8b-q4_k_m"


def test_llm_manager_rebuilds_client_when_expected_context_changes(monkeypatch):
    manager = LLMManager()
    manager._openai_client = None
    manager._openai_client_key = None
    monkeypatch.setattr(settings, "LLAMA_SERVER_CONTEXT_SIZE", 12288)

    first = manager._get_openai_client()
    monkeypatch.setattr(settings, "LLAMA_SERVER_CONTEXT_SIZE", 16384)
    second = manager._get_openai_client()

    assert first is not second
    assert first.expected_context_size == 12288
    assert second.expected_context_size == 16384


def test_llm_manager_rejects_extra_llama_server_alias(monkeypatch):
    manager = LLMManager()
    monkeypatch.setattr(settings, "LOCAL_LLM_PROVIDER", "llama_cpp_server")
    monkeypatch.setattr(
        settings,
        "LLAMA_SERVER_MODEL",
        "speechintel-qwen3-8b-q4_k_m",
    )
    monkeypatch.setattr(
        manager,
        "get_available_models",
        lambda **_kwargs: [
            "speechintel-qwen3-8b-q4_k_m",
            "rogue-model",
        ],
    )

    with pytest.raises(ValueError, match="configured llama-server alias"):
        manager.select_best_model("rogue-model")


@pytest.mark.parametrize(
    "lines",
    [
        [b"not-json"],
        [json.dumps({"response": "partial", "done": False}).encode()],
        [json.dumps({"response": "", "done": True}).encode()],
    ],
)
def test_ollama_stream_rejects_malformed_truncated_or_empty_output(
    monkeypatch,
    lines,
):
    manager = LLMManager()

    class OllamaResponse:
        status_code = 200

        @staticmethod
        def iter_lines():
            yield from lines

        @staticmethod
        def close():
            return None

    monkeypatch.setattr(settings, "LOCAL_LLM_PROVIDER", "ollama")
    monkeypatch.setattr(manager, "check_availability", lambda: True)
    monkeypatch.setattr(manager._session, "post", lambda *_args, **_kwargs: OllamaResponse())

    with pytest.raises(RuntimeError):
        manager.generate("PROMPT", model="qwen3.5:9b", stream=True)
