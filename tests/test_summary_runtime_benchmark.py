from __future__ import annotations

import json
from pathlib import Path

from scripts import benchmark_summary_runtime as benchmark


def _case_file(tmp_path: Path) -> Path:
    path = tmp_path / "cases.jsonl"
    path.write_text(
        json.dumps(
            {
                "id": "case-1",
                "category": "test",
                "transcript": "Lan hen Minh luc 09:00.",
                "expected_keywords": ["Lan", "Minh", "09:00"],
                "expected_critical_fields": [],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _config(tmp_path: Path, **overrides) -> benchmark.BenchmarkConfig:
    values = {
        "cases": _case_file(tmp_path),
        "models": ("qwen3.5:9b",),
        "provider": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "case_ids": None,
        "max_cases": None,
        "warmup": 0,
        "repetitions": 1,
        "load_states": ("warm",),
        "summary_type": "investigation",
        "summary_max_length": 120,
        "summary_min_length": 30,
        "min_free_vram_mib": None,
        "min_remaining_vram_mib": 1024,
        "safety_headroom_mib": 1536,
        "resource_poll_seconds": 0.25,
        "lease_timeout_seconds": 0.1,
        "preflight_only": False,
        "measure_ttft": False,
        "output": tmp_path / "report.json",
    }
    values.update(overrides)
    return benchmark.BenchmarkConfig(**values)


def test_preflight_blocks_before_any_model_generation(tmp_path):
    config = _config(tmp_path)
    called = False

    def fail_pipeline(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("model generation must not run")

    report, exit_code = benchmark.run_benchmark(
        config,
        preflight_builder=lambda _config: {
            "status": "BLOCKED_BY_RESOURCE",
            "resource_blocks": ["INSUFFICIENT_FREE_VRAM"],
        },
        pipeline_runner=fail_pipeline,
    )

    assert exit_code == 2
    assert report["overall_status"] == "BLOCKED_BY_RESOURCE"
    assert called is False


def test_preflight_only_never_executes_pipeline(tmp_path):
    config = _config(tmp_path, preflight_only=True)

    def fail_pipeline(*_args, **_kwargs):
        raise AssertionError("preflight-only mode must not execute the pipeline")

    report, exit_code = benchmark.run_benchmark(
        config,
        preflight_builder=lambda _config: {"status": "PASS"},
        pipeline_runner=fail_pipeline,
    )

    assert exit_code == 0
    assert report["overall_status"] == "PREFLIGHT_PASS"


def test_aggregate_records_latency_quality_and_unsupported_claims():
    run = {
        "pipeline_wall_time_seconds": 2.5,
        "llm_call_count": 1,
        "context_runtime": {
            "time_to_first_token_seconds": 0.4,
            "prompt_tokens_per_second": 100.0,
            "decode_tokens_per_second": 25.0,
        },
        "summary_runtime": {
            "time_to_first_token_seconds": None,
            "prompt_tokens_per_second": 80.0,
            "decode_tokens_per_second": 20.0,
        },
        "context": {
            "passed": True,
            "structured_output_valid": True,
            "critical_field_recall": 1.0,
            "grounded_evidence_rate": 1.0,
            "knowledge_item_count": 3,
            "grounded_knowledge_item_count": 2,
            "unsupported_high_risk_claims_released": False,
        },
        "summary": {"passed": True, "critical_field_recall": 1.0},
    }

    aggregate = benchmark._aggregate_runs([run])

    assert aggregate["pipeline_wall_time_seconds"]["p95"] == 2.5
    assert aggregate["llm_call_count"]["max"] == 1.0
    assert aggregate["time_to_first_token_seconds"]["p50"] == 0.4
    assert aggregate["unsupported_grounded_claim_count"] == 1
    assert aggregate["summary_claim_support_evaluable"] is False


def test_real_preflight_computes_model_size_plus_headroom(monkeypatch, tmp_path):
    config = _config(tmp_path)
    monkeypatch.setattr(
        benchmark,
        "_gpu_snapshot",
        lambda: {
            "available": True,
            "gpus": [
                {
                    "memory_total_mib": 12282,
                    "memory_used_mib": 10000,
                    "memory_free_mib": 2282,
                }
            ],
        },
    )
    monkeypatch.setattr(
        benchmark,
        "_ollama_metadata",
        lambda _base_url, _models: {
            "available": True,
            "models": {
                "qwen3.5:9b": {
                    "installed": True,
                    "size_bytes": 6 * 1024 * 1024 * 1024,
                    "digest": "a" * 64,
                }
            },
        },
    )

    preflight = benchmark.build_preflight(config)

    assert preflight["status"] == "BLOCKED_BY_RESOURCE"
    assert preflight["models"]["qwen3.5:9b"]["required_free_vram_mib"] == 7680


def test_llama_server_preflight_checks_remaining_vram(monkeypatch, tmp_path):
    config = _config(
        tmp_path,
        models=("speechintel-qwen3-8b-q4_k_m",),
        provider="llama_cpp_server",
        base_url="http://127.0.0.1:8088",
        min_remaining_vram_mib=1024,
    )
    monkeypatch.setattr(
        benchmark,
        "_gpu_snapshot",
        lambda: {
            "available": True,
            "gpus": [
                {
                    "memory_total_mib": 12282,
                    "memory_used_mib": 11600,
                    "memory_free_mib": 682,
                }
            ],
        },
    )
    monkeypatch.setattr(
        benchmark,
        "_llama_server_metadata",
        lambda _base_url, _models: {
            "available": True,
            "models": {
                "speechintel-qwen3-8b-q4_k_m": {
                    "installed": True,
                    "binding_verified": True,
                    "path_binding_verified": True,
                    "artifact_integrity_verified": True,
                    "size_bytes": 5_027_783_488,
                    "digest": "d" * 64,
                }
            },
        },
    )

    preflight = benchmark.build_preflight(config)

    assert preflight["status"] == "BLOCKED_BY_RESOURCE"
    assert preflight["provider"] == "llama_cpp_server"
    assert (
        preflight["models"]["speechintel-qwen3-8b-q4_k_m"][
            "required_free_vram_mib"
        ]
        == 1024
    )


def test_llama_server_preflight_rejects_unbound_model_alias(monkeypatch, tmp_path):
    config = _config(
        tmp_path,
        models=("speechintel-qwen3-8b-q4_k_m",),
        provider="llama_cpp_server",
        base_url="http://127.0.0.1:8088",
    )
    monkeypatch.setattr(
        benchmark,
        "_gpu_snapshot",
        lambda: {
            "available": True,
            "gpus": [{"memory_free_mib": 8000}],
        },
    )
    monkeypatch.setattr(
        benchmark,
        "_llama_server_metadata",
        lambda _base_url, _models: {
            "available": True,
            "models": {
                "speechintel-qwen3-8b-q4_k_m": {
                    "installed": True,
                    "binding_verified": False,
                    "path_binding_verified": False,
                    "artifact_integrity_verified": False,
                    "digest": None,
                    "size_bytes": None,
                }
            },
        },
    )

    preflight = benchmark.build_preflight(config)

    assert preflight["status"] == "FAIL_PRECONDITION"
    assert "MODEL_BINDING_MISMATCH:speechintel-qwen3-8b-q4_k_m" in preflight[
        "failures"
    ]
    assert preflight["models"]["speechintel-qwen3-8b-q4_k_m"]["digest"] is None


def test_llama_server_preflight_rejects_model_integrity_mismatch(
    monkeypatch,
    tmp_path,
):
    config = _config(
        tmp_path,
        models=("speechintel-qwen3-8b-q4_k_m",),
        provider="llama_cpp_server",
        base_url="http://127.0.0.1:8088",
    )
    monkeypatch.setattr(
        benchmark,
        "_gpu_snapshot",
        lambda: {
            "available": True,
            "gpus": [{"memory_free_mib": 8000}],
        },
    )
    monkeypatch.setattr(
        benchmark,
        "_llama_server_metadata",
        lambda _base_url, _models: {
            "available": True,
            "models": {
                "speechintel-qwen3-8b-q4_k_m": {
                    "installed": True,
                    "binding_verified": False,
                    "path_binding_verified": True,
                    "artifact_integrity_verified": False,
                    "digest": None,
                    "size_bytes": None,
                }
            },
        },
    )

    preflight = benchmark.build_preflight(config)

    assert preflight["status"] == "FAIL_PRECONDITION"
    assert "MODEL_INTEGRITY_MISMATCH:speechintel-qwen3-8b-q4_k_m" in preflight[
        "failures"
    ]


def test_llama_server_preflight_rejects_context_binding_mismatch(
    monkeypatch,
    tmp_path,
):
    config = _config(
        tmp_path,
        models=("speechintel-qwen3-8b-q4_k_m",),
        provider="llama_cpp_server",
        base_url="http://127.0.0.1:8088",
    )
    monkeypatch.setattr(
        benchmark,
        "_gpu_snapshot",
        lambda: {"available": True, "gpus": [{"memory_free_mib": 8000}]},
    )
    monkeypatch.setattr(
        benchmark,
        "_llama_server_metadata",
        lambda _base_url, _models: {
            "available": True,
            "models": {
                "speechintel-qwen3-8b-q4_k_m": {
                    "installed": True,
                    "binding_verified": False,
                    "path_binding_verified": True,
                    "artifact_integrity_verified": True,
                    "context_binding_verified": False,
                    "expected_context_size": 12288,
                    "observed_context_size": 8192,
                    "digest": "d" * 64,
                    "size_bytes": 5_027_783_488,
                }
            },
        },
    )

    preflight = benchmark.build_preflight(config)

    assert preflight["status"] == "FAIL_PRECONDITION"
    assert (
        "CONTEXT_BINDING_MISMATCH:speechintel-qwen3-8b-q4_k_m"
        in preflight["failures"]
    )


def test_artifact_integrity_requires_matching_size_and_sha256(tmp_path):
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"trusted")
    spec = {
        "size_bytes": 7,
        "sha256": "f" * 64,
    }

    assert benchmark._artifact_integrity_verified(model_path, spec) is False

    spec["sha256"] = benchmark._file_sha256(model_path)
    assert benchmark._artifact_integrity_verified(model_path, spec) is True


def test_llama_metadata_never_assigns_official_digest_to_rogue_path(
    monkeypatch,
    tmp_path,
):
    class Response:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, **_kwargs):
        if url.endswith("/health"):
            return Response({"status": "ok"})
        if url.endswith("/v1/models"):
            return Response(
                {
                    "data": [
                        {
                            "id": "speechintel-qwen3-8b-q4_k_m",
                            "meta": {"n_ctx": 12288, "n_ctx_train": 40960},
                        }
                    ]
                }
            )
        if url.endswith("/props"):
            return Response(
                {
                    "model_path": str(tmp_path / "rogue.gguf"),
                    "chat_template": "rogue",
                    "total_slots": 1,
                    "default_generation_settings": {"n_ctx": 12288},
                }
            )
        if url.endswith("/slots"):
            return Response([{"id": 0, "n_ctx": 12288}])
        raise AssertionError(url)

    class FakeSession:
        trust_env = True

        @staticmethod
        def get(url, **kwargs):
            assert kwargs["allow_redirects"] is False
            return fake_get(url, **kwargs)

    session = FakeSession()
    monkeypatch.setattr(benchmark.requests, "Session", lambda: session)

    metadata = benchmark._llama_server_metadata(
        "http://127.0.0.1:8088",
        ("speechintel-qwen3-8b-q4_k_m",),
    )

    model = metadata["models"]["speechintel-qwen3-8b-q4_k_m"]
    assert model["installed"] is True
    assert model["binding_verified"] is False
    assert model["context_binding_verified"] is True
    assert model["digest"] is None
    assert session.trust_env is False


def test_runtime_metadata_rejects_non_loopback_without_network(monkeypatch):
    monkeypatch.setattr(
        benchmark.requests,
        "Session",
        lambda: (_ for _ in ()).throw(AssertionError("network session created")),
    )

    for loader in (benchmark._ollama_metadata, benchmark._llama_server_metadata):
        metadata = loader("http://example.com", ("model",))
        assert metadata["available"] is False
        assert metadata["errors"][0].startswith("base_url:")
