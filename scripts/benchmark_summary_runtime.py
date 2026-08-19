"""Benchmark the local investigation summary pipeline without oversubscribing GPU.

The harness fails closed before model generation when the requested model is missing
or the single GPU does not have enough free memory. Passing this synthetic harness is
not evidence of investigative correctness; production promotion still requires a
human-labelled Vietnamese/noisy-ASR corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Iterable, Sequence

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import evaluate_context_analysis as context_eval  # noqa: E402
from src.core.config import settings  # noqa: E402
from src.services.model_runtime import GpuLeaseTimeout, gpu_lease  # noqa: E402
from src.services.summarization.models.context_analysis import (  # noqa: E402
    CONTEXT_PROMPT_VERSION,
    ContextAnalysisPayload,
)
from src.services.summarization.models.investigation_knowledge import (  # noqa: E402
    KNOWLEDGE_SCHEMA_VERSION,
)
from src.services.summarization.models.llm_manager import get_llm_manager  # noqa: E402
from src.services.summarization.models.openai_compatible_client import (  # noqa: E402
    validate_local_base_url,
)
from src.services.summarization.summary_service_v2 import (  # noqa: E402
    SUMMARY_PROMPT_VERSION,
    summarize_transcript_v2,
)


PROTOCOL_VERSION = "local-summary-runtime-v1"
QUALITY_CLAIM = "SYNTHETIC_RUNTIME_GATE_ONLY_NO_PRODUCTION_QUALITY_CLAIM"
DEFAULT_CASES = Path("tests/eval/context_cases.jsonl")
DEFAULT_OUTPUT_DIR = Path("docs/evals/runs")
DEFAULT_SAFETY_HEADROOM_MIB = 1536
DEFAULT_MIN_REMAINING_VRAM_MIB = 1024
DEFAULT_POLL_SECONDS = 0.25
TTFT_PROBE_PROMPT = "Reply with exactly OK."
NUMBER_RE = re.compile(r"(?<!\w)(?:\d[\d.,:/-]*\d|\d{2,})(?!\w)")


@dataclass(frozen=True)
class BenchmarkConfig:
    cases: Path
    models: tuple[str, ...]
    provider: str
    base_url: str
    case_ids: frozenset[str] | None
    max_cases: int | None
    warmup: int
    repetitions: int
    load_states: tuple[str, ...]
    summary_type: str
    summary_max_length: int
    summary_min_length: int
    min_free_vram_mib: int | None
    min_remaining_vram_mib: int
    safety_headroom_mib: int
    resource_poll_seconds: float
    lease_timeout_seconds: float
    preflight_only: bool
    measure_ttft: bool
    output: Path


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _canonical_sha256(value: Any) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256_text(rendered)


def _file_sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _artifact_integrity_verified(path: Path, spec: dict[str, Any]) -> bool:
    try:
        expected_size = int(spec["size_bytes"])
        expected_sha256 = str(spec["sha256"]).casefold()
        if path.stat().st_size != expected_size:
            return False
    except (OSError, KeyError, TypeError, ValueError):
        return False
    return _file_sha256(path) == expected_sha256


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def _distribution(values: Iterable[float | int | None]) -> dict[str, float | None]:
    materialized = [float(value) for value in values if value is not None]
    if not materialized:
        return {"min": None, "mean": None, "p50": None, "p95": None, "max": None}
    return {
        "min": round(min(materialized), 6),
        "mean": round(mean(materialized), 6),
        "p50": round(_percentile(materialized, 0.50) or 0.0, 6),
        "p95": round(_percentile(materialized, 0.95) or 0.0, 6),
        "max": round(max(materialized), 6),
    }


def _run_command(command: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=timeout,
    )


def _gpu_snapshot() -> dict[str, Any]:
    try:
        completed = _run_command(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu",
                "--format=csv,noheader,nounits",
            ]
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "error": type(exc).__name__, "gpus": []}

    gpus = []
    for line in completed.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 6:
            continue
        try:
            gpus.append(
                {
                    "index": int(parts[0]),
                    "name": parts[1],
                    "memory_total_mib": int(parts[2]),
                    "memory_used_mib": int(parts[3]),
                    "memory_free_mib": int(parts[4]),
                    "utilization_percent": int(parts[5]),
                }
            )
        except ValueError:
            continue
    return {"available": bool(gpus), "gpus": gpus}


def _system_memory_used_mib() -> float | None:
    if os.name == "nt":
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("memory_load", ctypes.c_ulong),
                    ("total_physical", ctypes.c_ulonglong),
                    ("available_physical", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong),
                    ("available_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended_virtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(MemoryStatus)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return round(
                (status.total_physical - status.available_physical) / (1024 * 1024),
                3,
            )
        except (AttributeError, OSError):
            return None

    try:
        rows = {}
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            key, raw = line.split(":", 1)
            rows[key] = int(raw.strip().split()[0])
        return round((rows["MemTotal"] - rows["MemAvailable"]) / 1024, 3)
    except (OSError, KeyError, ValueError):
        return None


def _ollama_metadata(base_url: str, models: Sequence[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "available": False,
        "base_url": base_url,
        "version": None,
        "models": {},
        "errors": [],
    }
    try:
        base_url = validate_local_base_url(base_url, offline_strict=True)
    except ValueError as exc:
        metadata["errors"].append(f"base_url:{exc}")
        return metadata
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.get(
            f"{base_url}/api/version",
            timeout=3,
            allow_redirects=False,
        )
        response.raise_for_status()
        metadata["version"] = response.json().get("version")
    except Exception as exc:
        metadata["errors"].append(f"version:{type(exc).__name__}")

    try:
        response = session.get(
            f"{base_url}/api/tags",
            timeout=5,
            allow_redirects=False,
        )
        response.raise_for_status()
        tags = {
            row.get("name"): row
            for row in response.json().get("models", [])
            if isinstance(row, dict) and row.get("name")
        }
        metadata["available"] = True
    except Exception as exc:
        tags = {}
        metadata["errors"].append(f"tags:{type(exc).__name__}")

    for model in models:
        tag = tags.get(model) or {}
        row: dict[str, Any] = {
            "installed": model in tags,
            "digest": tag.get("digest"),
            "size_bytes": tag.get("size"),
            "details": tag.get("details") or {},
            "template_sha256": None,
        }
        if model in tags:
            try:
                response = session.post(
                    f"{base_url}/api/show",
                    json={"model": model},
                    timeout=10,
                    allow_redirects=False,
                )
                response.raise_for_status()
                shown = response.json()
                row["template_sha256"] = _sha256_text(shown.get("template") or "")
                row["capabilities"] = shown.get("capabilities") or []
                row["default_parameters_sha256"] = _sha256_text(
                    shown.get("parameters") or ""
                )
            except Exception as exc:
                row["metadata_error"] = type(exc).__name__
        metadata["models"][model] = row
    return metadata


def _llama_server_metadata(base_url: str, models: Sequence[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "available": False,
        "base_url": base_url,
        "models": {},
        "errors": [],
        "props": {},
        "slots": [],
    }
    try:
        base_url = validate_local_base_url(base_url, offline_strict=True)
    except ValueError as exc:
        metadata["errors"].append(f"base_url:{exc}")
        return metadata
    session = requests.Session()
    session.trust_env = False
    healthy = False
    try:
        response = session.get(
            f"{base_url}/health",
            timeout=3,
            allow_redirects=False,
        )
        response.raise_for_status()
        healthy = True
    except Exception as exc:
        metadata["errors"].append(f"health:{type(exc).__name__}")

    loaded = {}
    observed_model_path: str | None = None
    slots: list[dict[str, Any]] = []
    if healthy:
        try:
            response = session.get(
                f"{base_url}/v1/models",
                timeout=5,
                allow_redirects=False,
            )
            response.raise_for_status()
            loaded = {
                row.get("id"): row
                for row in response.json().get("data", [])
                if isinstance(row, dict) and row.get("id")
            }
            metadata["available"] = True
        except Exception as exc:
            metadata["errors"].append(f"models:{type(exc).__name__}")

    if healthy:
        try:
            response = session.get(
                f"{base_url}/props",
                timeout=5,
                allow_redirects=False,
            )
            response.raise_for_status()
            props = response.json()
            observed_model_path = str(props.get("model_path") or "") or None
            metadata["props"] = {
                "model_path_sha256": _sha256_text(
                    str(props.get("model_path") or "")
                ),
                "chat_template_sha256": _sha256_text(
                    str(props.get("chat_template") or "")
                ),
                "total_slots": props.get("total_slots"),
                "context_size": (
                    props.get("default_generation_settings") or {}
                ).get("n_ctx"),
            }
        except Exception as exc:
            metadata["errors"].append(f"props:{type(exc).__name__}")

    if healthy:
        try:
            response = session.get(
                f"{base_url}/slots",
                timeout=5,
                allow_redirects=False,
            )
            response.raise_for_status()
            slots_payload = response.json()
            if isinstance(slots_payload, list):
                slots = [row for row in slots_payload if isinstance(row, dict)]
            metadata["slots"] = [
                {"id": row.get("id"), "context_size": row.get("n_ctx")}
                for row in slots
            ]
        except Exception as exc:
            metadata["errors"].append(f"slots:{type(exc).__name__}")

    manifest_path = PROJECT_ROOT / "config/models/qwen3-8b-q4_k_m.manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        model_spec = manifest["model"]
        primary_file = next(
            row for row in model_spec["files"] if str(row["path"]).endswith(".gguf")
        )
        expected_model_path = (
            PROJECT_ROOT
            / "models"
            / str(model_spec["relative_path"])
            / str(primary_file["path"])
        ).resolve()
    except (OSError, ValueError, KeyError, StopIteration, TypeError):
        primary_file = {}
        expected_model_path = None

    path_binding_verified = False
    if observed_model_path and expected_model_path is not None:
        try:
            path_binding_verified = Path(str(observed_model_path)).resolve() == expected_model_path
        except OSError:
            path_binding_verified = False
    artifact_integrity_verified = bool(
        path_binding_verified
        and expected_model_path is not None
        and _artifact_integrity_verified(expected_model_path, primary_file)
    )
    metadata["props"]["model_path_binding_verified"] = path_binding_verified
    metadata["props"]["model_artifact_integrity_verified"] = (
        artifact_integrity_verified
    )
    expected_context_size = int(settings.LLAMA_SERVER_CONTEXT_SIZE)

    for model in models:
        row = loaded.get(model) or {}
        model_meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        context_binding_verified = bool(
            metadata["props"].get("context_size") == expected_context_size
            and model_meta.get("n_ctx") == expected_context_size
            and isinstance(model_meta.get("n_ctx_train"), int)
            and model_meta["n_ctx_train"] >= expected_context_size
            and len(slots) == 1
            and slots[0].get("n_ctx") == expected_context_size
        )
        binding_verified = bool(
            model in loaded
            and path_binding_verified
            and artifact_integrity_verified
            and context_binding_verified
        )
        metadata["models"][model] = {
            "installed": model in loaded,
            "binding_verified": binding_verified,
            "path_binding_verified": bool(model in loaded and path_binding_verified),
            "artifact_integrity_verified": bool(
                model in loaded and artifact_integrity_verified
            ),
            "context_binding_verified": bool(
                model in loaded and context_binding_verified
            ),
            "expected_context_size": expected_context_size,
            "observed_context_size": model_meta.get("n_ctx"),
            "training_context_size": model_meta.get("n_ctx_train"),
            "digest": primary_file.get("sha256") if binding_verified else None,
            "size_bytes": primary_file.get("size_bytes") if binding_verified else None,
            "template_sha256": metadata["props"].get("chat_template_sha256"),
            "owned_by": row.get("owned_by"),
        }
    return metadata


def _required_free_vram_mib(
    model_metadata: dict[str, Any],
    *,
    override_mib: int | None,
    safety_headroom_mib: int,
) -> int:
    if override_mib is not None:
        return max(0, override_mib)
    size_bytes = int(model_metadata.get("size_bytes") or 0)
    weight_mib = math.ceil(size_bytes / (1024 * 1024))
    return weight_mib + max(0, safety_headroom_mib)


def build_preflight(config: BenchmarkConfig) -> dict[str, Any]:
    gpu = _gpu_snapshot()
    provider = config.provider.casefold()
    if provider == "llama_cpp_server":
        runtime = _llama_server_metadata(config.base_url, config.models)
    else:
        runtime = _ollama_metadata(config.base_url, config.models)
    failures: list[str] = []
    resource_blocks: list[str] = []

    if not gpu.get("available"):
        failures.append("NVIDIA_GPU_UNAVAILABLE")
        primary_gpu = None
    else:
        primary_gpu = gpu["gpus"][0]

    if not runtime.get("available"):
        failures.append(
            "LLAMA_SERVER_UNAVAILABLE"
            if provider == "llama_cpp_server"
            else "OLLAMA_UNAVAILABLE"
        )

    model_checks = {}
    for model in config.models:
        metadata = runtime.get("models", {}).get(model) or {}
        if provider == "llama_cpp_server":
            required = max(0, config.min_remaining_vram_mib)
        else:
            required = _required_free_vram_mib(
                metadata,
                override_mib=config.min_free_vram_mib,
                safety_headroom_mib=config.safety_headroom_mib,
            )
        free = primary_gpu.get("memory_free_mib") if primary_gpu else None
        installed = bool(metadata.get("installed"))
        enough_memory = free is not None and free >= required
        if not installed:
            failures.append(
                f"MODEL_NOT_LOADED:{model}"
                if provider == "llama_cpp_server"
                else f"MODEL_NOT_INSTALLED:{model}"
            )
        elif provider == "llama_cpp_server" and not metadata.get(
            "path_binding_verified"
        ):
            failures.append(f"MODEL_BINDING_MISMATCH:{model}")
        elif provider == "llama_cpp_server" and not metadata.get(
            "artifact_integrity_verified"
        ):
            failures.append(f"MODEL_INTEGRITY_MISMATCH:{model}")
        elif provider == "llama_cpp_server" and not metadata.get(
            "context_binding_verified",
            metadata.get("binding_verified"),
        ):
            failures.append(f"CONTEXT_BINDING_MISMATCH:{model}")
        elif not enough_memory:
            resource_blocks.append(
                f"INSUFFICIENT_FREE_VRAM:{model}:required={required}:free={free}"
            )
        model_checks[model] = {
            "installed": installed,
            "loaded": installed if provider == "llama_cpp_server" else None,
            "required_free_vram_mib": required,
            "observed_free_vram_mib": free,
            "resource_ready": installed
            and enough_memory
            and (
                provider != "llama_cpp_server"
                or bool(metadata.get("binding_verified"))
            ),
            "binding_verified": metadata.get("binding_verified"),
            "path_binding_verified": metadata.get("path_binding_verified"),
            "artifact_integrity_verified": metadata.get(
                "artifact_integrity_verified"
            ),
            "context_binding_verified": metadata.get(
                "context_binding_verified"
            ),
            "expected_context_size": metadata.get("expected_context_size"),
            "observed_context_size": metadata.get("observed_context_size"),
            "training_context_size": metadata.get("training_context_size"),
            "digest": metadata.get("digest"),
            "size_bytes": metadata.get("size_bytes"),
            "template_sha256": metadata.get("template_sha256"),
        }

    if failures:
        status = "FAIL_PRECONDITION"
    elif resource_blocks:
        status = "BLOCKED_BY_RESOURCE"
    else:
        status = "PASS"
    return {
        "status": status,
        "failures": failures,
        "resource_blocks": resource_blocks,
        "provider": provider,
        "gpu": gpu,
        "runtime": runtime,
        "models": model_checks,
    }


class ResourceSampler:
    def __init__(self, poll_seconds: float) -> None:
        self.poll_seconds = max(0.05, poll_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._samples: list[dict[str, float | None]] = []

    def _sample(self) -> None:
        gpu = _gpu_snapshot()
        first_gpu = gpu.get("gpus", [{}])[0] if gpu.get("gpus") else {}
        self._samples.append(
            {
                "gpu_used_mib": first_gpu.get("memory_used_mib"),
                "gpu_free_mib": first_gpu.get("memory_free_mib"),
                "host_ram_used_mib": _system_memory_used_mib(),
            }
        )

    def _run(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            self._sample()

    def __enter__(self) -> ResourceSampler:
        self._sample()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.poll_seconds * 4))
        self._sample()

    def report(self) -> dict[str, Any]:
        gpu_used = [row["gpu_used_mib"] for row in self._samples]
        gpu_free = [row["gpu_free_mib"] for row in self._samples]
        ram_used = [row["host_ram_used_mib"] for row in self._samples]
        return {
            "sample_count": len(self._samples),
            "gpu_used_mib": _distribution(gpu_used),
            "gpu_free_mib": _distribution(gpu_free),
            "host_ram_used_mib": _distribution(ram_used),
        }


def _unsupported_numeric_tokens(summary: str, transcript: str) -> list[str]:
    transcript_numbers = set(NUMBER_RE.findall(transcript))
    return sorted(set(NUMBER_RE.findall(summary)) - transcript_numbers)


def _run_pipeline_once(
    model: str,
    case: dict[str, Any],
    config: BenchmarkConfig,
) -> dict[str, Any]:
    manager = get_llm_manager()
    generation_count_start = manager.get_generation_count()
    started = time.perf_counter()
    result = summarize_transcript_v2(
        case["transcript"],
        model_name=model,
        summary_type=config.summary_type,
        include_context=True,
        max_length=config.summary_max_length,
        min_length=config.summary_min_length,
        transcript_segments=case.get("segments") or [],
        source_metadata={
            "task_id": f"eval-{case['id']}",
            "audio_integrity_status": "synthetic_fixture",
        },
    )
    elapsed = time.perf_counter() - started
    context_result = context_eval._score_context_analysis(
        result.get("context"),
        case,
        elapsed,
    )
    summary_result = context_eval._score_summary_result(
        result,
        model,
        case,
        latency=elapsed,
        summary_type=config.summary_type,
        max_length=config.summary_max_length,
        min_length=config.summary_min_length,
    )
    pipeline_runtime = manager.get_last_generation_metadata()
    summary_text = str(result.get("summary") or "")
    unsupported_numbers = _unsupported_numeric_tokens(
        summary_text,
        case["transcript"],
    )

    return {
        "case_id": case["id"],
        "category": case["category"],
        "pipeline_wall_time_seconds": round(elapsed, 6),
        "context": context_result,
        "summary": summary_result,
        "context_runtime": pipeline_runtime,
        "summary_runtime": None,
        "shared_single_pass_runtime": True,
        "llm_call_count": manager.get_generation_count() - generation_count_start,
        "unsupported_summary_numeric_tokens": unsupported_numbers,
        "summary_claim_support_evaluable": False,
        "raw_output_persisted": False,
        "summary_chars": len(summary_text) if summary_text else summary_result.get("summary_chars"),
    }


def _ttft_probe(model: str) -> dict[str, Any]:
    manager = get_llm_manager()
    started = time.perf_counter()
    response = manager.generate(
        TTFT_PROBE_PROMPT,
        model=model,
        temperature=0.0,
        max_tokens=8,
        stream=True,
    )
    return {
        "wall_time_seconds": round(time.perf_counter() - started, 6),
        "response_sha256": _sha256_text(response),
        "prompt_sha256": _sha256_text(TTFT_PROBE_PROMPT),
        "runtime": manager.get_last_generation_metadata(),
    }


def _aggregate_runs(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    context_rows = [run["context"] for run in runs]
    summary_rows = [run["summary"] for run in runs]
    runtime_rows = [
        runtime
        for run in runs
        for runtime in (run.get("context_runtime"), run.get("summary_runtime"))
        if isinstance(runtime, dict)
    ]
    unsupported_claims = sum(
        max(
            0,
            int(row.get("knowledge_item_count") or 0)
            - int(row.get("grounded_knowledge_item_count") or 0),
        )
        for row in context_rows
    )
    return {
        "run_count": len(runs),
        "llm_call_count": _distribution(run.get("llm_call_count") for run in runs),
        "pipeline_wall_time_seconds": _distribution(
            run.get("pipeline_wall_time_seconds") for run in runs
        ),
        "time_to_first_token_seconds": _distribution(
            row.get("time_to_first_token_seconds") for row in runtime_rows
        ),
        "prompt_tokens_per_second": _distribution(
            row.get("prompt_tokens_per_second") for row in runtime_rows
        ),
        "decode_tokens_per_second": _distribution(
            row.get("decode_tokens_per_second") for row in runtime_rows
        ),
        "context_pass_rate": round(
            sum(bool(row.get("passed")) for row in context_rows) / len(context_rows),
            6,
        )
        if context_rows
        else None,
        "summary_pass_rate": round(
            sum(bool(row.get("passed")) for row in summary_rows) / len(summary_rows),
            6,
        )
        if summary_rows
        else None,
        "schema_valid_rate": round(
            sum(bool(row.get("structured_output_valid")) for row in context_rows)
            / len(context_rows),
            6,
        )
        if context_rows
        else None,
        "critical_recall": round(
            mean(float(row.get("critical_field_recall") or 0.0) for row in context_rows),
            6,
        )
        if context_rows
        else None,
        "summary_critical_recall": round(
            mean(float(row.get("critical_field_recall") or 0.0) for row in summary_rows),
            6,
        )
        if summary_rows
        else None,
        "evidence_precision": round(
            mean(float(row.get("grounded_evidence_rate") or 0.0) for row in context_rows),
            6,
        )
        if context_rows
        else None,
        "unsupported_grounded_claim_count": unsupported_claims,
        "unsupported_high_risk_release_count": sum(
            row.get("unsupported_high_risk_claims_released") is not False
            for row in context_rows
        ),
        "summary_claim_support_evaluable": False,
    }


def _promotion_gate(
    aggregate: dict[str, Any],
    resources: dict[str, Any],
    config: BenchmarkConfig,
) -> dict[str, Any]:
    remaining_vram = (resources.get("gpu_free_mib") or {}).get("min")
    checks = {
        "schema_valid_rate_1_0": aggregate.get("schema_valid_rate") == 1.0,
        "critical_recall_at_least_0_95": (aggregate.get("critical_recall") or 0) >= 0.95,
        "summary_critical_recall_at_least_0_95": (
            aggregate.get("summary_critical_recall") or 0
        )
        >= 0.95,
        "evidence_precision_at_least_0_98": (
            aggregate.get("evidence_precision") or 0
        )
        >= 0.98,
        "zero_unsupported_grounded_claims": aggregate.get(
            "unsupported_grounded_claim_count"
        )
        == 0,
        "zero_unsupported_high_risk_releases": aggregate.get(
            "unsupported_high_risk_release_count"
        )
        == 0,
        "minimum_remaining_vram": remaining_vram is not None
        and remaining_vram >= config.min_remaining_vram_mib,
        "single_llm_call_per_case": (
            (aggregate.get("llm_call_count") or {}).get("max") is not None
            and (aggregate.get("llm_call_count") or {}).get("max") <= 1
        ),
        # This cannot pass until summaries expose evidence-backed atomic claims.
        "summary_claim_support_evaluable": aggregate.get(
            "summary_claim_support_evaluable"
        )
        is True,
    }
    return {"passed": all(checks.values()), "checks": checks}


def _source_provenance(config: BenchmarkConfig) -> dict[str, Any]:
    fixture_bytes = config.cases.read_bytes()
    context_schema = ContextAnalysisPayload.model_json_schema()
    files = {
        "llm_manager": PROJECT_ROOT
        / "src/services/summarization/models/llm_manager.py",
        "openai_compatible_client": PROJECT_ROOT
        / "src/services/summarization/models/openai_compatible_client.py",
        "context_analysis": PROJECT_ROOT
        / "src/services/summarization/models/context_analysis.py",
        "investigation_knowledge": PROJECT_ROOT
        / "src/services/summarization/models/investigation_knowledge.py",
        "summary_service": PROJECT_ROOT
        / "src/services/summarization/summary_service_v2.py",
        "projections": PROJECT_ROOT
        / "src/services/summarization/projections.py",
        "context_evaluator": PROJECT_ROOT / "scripts/evaluate_context_analysis.py",
        "benchmark": Path(__file__).resolve(),
    }
    return {
        "fixture": {
            "path": str(config.cases),
            "size_bytes": len(fixture_bytes),
            "sha256": _sha256_bytes(fixture_bytes),
        },
        "prompt_versions": {
            "context": CONTEXT_PROMPT_VERSION,
            "summary": SUMMARY_PROMPT_VERSION,
        },
        "schema_versions": {
            "investigation_knowledge": KNOWLEDGE_SCHEMA_VERSION,
            "context_schema_sha256": _canonical_sha256(context_schema),
        },
        "source_sha256": {
            name: _file_sha256(path) for name, path in files.items()
        },
    }


def _git_metadata() -> dict[str, Any]:
    def run(*args: str) -> str | None:
        try:
            return _run_command(["git", *args]).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None

    status = run("status", "--porcelain", "--untracked-files=no")
    return {
        "revision": run("rev-parse", "HEAD"),
        "tracked_worktree_dirty": bool(status) if status is not None else None,
    }


def _base_report(config: BenchmarkConfig, cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": PROTOCOL_VERSION,
        "quality_claim": QUALITY_CLAIM,
        "config": {
            **asdict(config),
            "cases": str(config.cases),
            "case_ids": sorted(config.case_ids) if config.case_ids else None,
            "models": list(config.models),
            "load_states": list(config.load_states),
            "output": str(config.output),
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "logical_cpu_count": os.cpu_count(),
            "git": _git_metadata(),
        },
        "provenance": _source_provenance(config),
        "dataset": {
            "case_count": len(cases),
            "case_ids": [case["id"] for case in cases],
            "categories": sorted({case["category"] for case in cases}),
        },
        "preflight": None,
        "models": {},
    }


def _execute_model(
    model: str,
    cases: Sequence[dict[str, Any]],
    config: BenchmarkConfig,
    pipeline_runner: Callable[[str, dict[str, Any], BenchmarkConfig], dict[str, Any]],
) -> dict[str, Any]:
    manager = get_llm_manager()
    model_report: dict[str, Any] = {"load_states": {}}
    previous_unload = settings.UNLOAD_MODELS_AFTER_TASK
    settings.UNLOAD_MODELS_AFTER_TASK = False
    try:
        with gpu_lease(
            "benchmark",
            f"model:{model}",
            timeout_seconds=config.lease_timeout_seconds,
        ):
            for load_state in config.load_states:
                manager.unload_model(model)
                warmups = []
                if load_state == "warm":
                    for _ in range(config.warmup):
                        warmups.append(pipeline_runner(model, cases[0], config))

                ttft = None
                if config.measure_ttft:
                    if load_state == "cold":
                        manager.unload_model(model)
                    ttft = _ttft_probe(model)

                runs = []
                with ResourceSampler(config.resource_poll_seconds) as sampler:
                    for repetition in range(config.repetitions):
                        for case in cases:
                            if load_state == "cold":
                                manager.unload_model(model)
                            run = pipeline_runner(model, case, config)
                            run["repetition"] = repetition + 1
                            runs.append(run)
                resources = sampler.report()
                aggregate = _aggregate_runs(runs)
                model_report["load_states"][load_state] = {
                    "warmup_count": len(warmups),
                    "ttft_probe": ttft,
                    "runs": runs,
                    "aggregate": aggregate,
                    "resources": resources,
                    "promotion_gate": _promotion_gate(aggregate, resources, config),
                }
    finally:
        settings.UNLOAD_MODELS_AFTER_TASK = previous_unload
        manager.unload_model(model)
    return model_report


def run_benchmark(
    config: BenchmarkConfig,
    *,
    preflight_builder: Callable[[BenchmarkConfig], dict[str, Any]] = build_preflight,
    pipeline_runner: Callable[
        [str, dict[str, Any], BenchmarkConfig], dict[str, Any]
    ] = _run_pipeline_once,
) -> tuple[dict[str, Any], int]:
    cases = context_eval._load_cases(config.cases, config.case_ids, config.max_cases)
    if not cases:
        raise ValueError("No benchmark cases selected")
    report = _base_report(config, cases)
    preflight = preflight_builder(config)
    report["preflight"] = preflight

    if preflight.get("status") != "PASS":
        report["overall_status"] = preflight.get("status") or "FAIL_PRECONDITION"
        return report, 2
    if config.preflight_only:
        report["overall_status"] = "PREFLIGHT_PASS"
        return report, 0

    previous_provider = settings.LOCAL_LLM_PROVIDER
    previous_ollama_base_url = settings.OLLAMA_BASE_URL
    previous_base_url = settings.LLAMA_SERVER_BASE_URL
    previous_server_model = settings.LLAMA_SERVER_MODEL
    settings.LOCAL_LLM_PROVIDER = config.provider
    if config.provider == "llama_cpp_server":
        settings.LLAMA_SERVER_BASE_URL = config.base_url
        settings.LLAMA_SERVER_MODEL = config.models[0]
    else:
        settings.OLLAMA_BASE_URL = config.base_url
    try:
        for model in config.models:
            report["models"][model] = _execute_model(
                model,
                cases,
                config,
                pipeline_runner,
            )
    except GpuLeaseTimeout as exc:
        report["overall_status"] = "BLOCKED_BY_RESOURCE"
        report["execution_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        return report, 2
    except Exception as exc:
        report["overall_status"] = "BENCHMARK_FAILED"
        report["execution_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        return report, 1
    finally:
        settings.LOCAL_LLM_PROVIDER = previous_provider
        settings.OLLAMA_BASE_URL = previous_ollama_base_url
        settings.LLAMA_SERVER_BASE_URL = previous_base_url
        settings.LLAMA_SERVER_MODEL = previous_server_model

    gates = [
        state["promotion_gate"]["passed"]
        for model in report["models"].values()
        for state in model.get("load_states", {}).values()
    ]
    report["overall_status"] = (
        "PASS" if gates and all(gates) else "QUALITY_GATE_NOT_MET"
    )
    return report, 0 if report["overall_status"] == "PASS" else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark local Vietnamese investigation summary runtime."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--models", default=settings.DEFAULT_AI_MODEL)
    parser.add_argument(
        "--provider",
        choices=("ollama", "llama_cpp_server"),
        default=settings.LOCAL_LLM_PROVIDER,
    )
    parser.add_argument("--base-url")
    parser.add_argument("--case-ids", default="")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--load-states", default="cold,warm")
    parser.add_argument("--summary-type", default="investigation")
    parser.add_argument("--summary-max-length", type=int, default=240)
    parser.add_argument("--summary-min-length", type=int, default=60)
    parser.add_argument("--min-free-vram-mib", type=int)
    parser.add_argument(
        "--min-remaining-vram-mib",
        type=int,
        default=DEFAULT_MIN_REMAINING_VRAM_MIB,
    )
    parser.add_argument(
        "--safety-headroom-mib",
        type=int,
        default=DEFAULT_SAFETY_HEADROOM_MIB,
    )
    parser.add_argument(
        "--resource-poll-seconds",
        type=float,
        default=DEFAULT_POLL_SECONDS,
    )
    parser.add_argument("--lease-timeout-seconds", type=float, default=5.0)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--skip-ttft", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def _config(args: argparse.Namespace) -> BenchmarkConfig:
    models = tuple(item.strip() for item in args.models.split(",") if item.strip())
    load_states = tuple(
        item.strip() for item in args.load_states.split(",") if item.strip()
    )
    invalid_states = sorted(set(load_states) - {"cold", "warm"})
    if not models:
        raise ValueError("At least one model is required")
    if invalid_states or not load_states:
        raise ValueError(f"Invalid load states: {', '.join(invalid_states)}")
    if args.warmup < 0 or args.repetitions < 1:
        raise ValueError("warmup must be >= 0 and repetitions must be >= 1")
    if args.provider == "llama_cpp_server" and "cold" in load_states:
        raise ValueError(
            "llama_cpp_server cold-load measurement requires managed process restart; "
            "use --load-states warm for the external-server benchmark"
        )
    case_ids = frozenset(
        item.strip() for item in args.case_ids.split(",") if item.strip()
    ) or None
    output = args.output
    if output is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = DEFAULT_OUTPUT_DIR / f"summary-runtime-{stamp}.json"
    return BenchmarkConfig(
        cases=args.cases,
        models=models,
        provider=args.provider,
        base_url=(
            args.base_url
            or (
                settings.LLAMA_SERVER_BASE_URL
                if args.provider == "llama_cpp_server"
                else settings.OLLAMA_BASE_URL
            )
        ).rstrip("/"),
        case_ids=case_ids,
        max_cases=args.max_cases,
        warmup=args.warmup,
        repetitions=args.repetitions,
        load_states=load_states,
        summary_type=args.summary_type,
        summary_max_length=args.summary_max_length,
        summary_min_length=args.summary_min_length,
        min_free_vram_mib=args.min_free_vram_mib,
        min_remaining_vram_mib=max(0, args.min_remaining_vram_mib),
        safety_headroom_mib=max(0, args.safety_headroom_mib),
        resource_poll_seconds=max(0.05, args.resource_poll_seconds),
        lease_timeout_seconds=max(0.0, args.lease_timeout_seconds),
        preflight_only=args.preflight_only,
        measure_ttft=not args.skip_ttft,
        output=output,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = _config(args)
        report, exit_code = run_benchmark(config)
    except Exception as exc:
        output = args.output or DEFAULT_OUTPUT_DIR / "summary-runtime-invalid-config.json"
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "protocol": PROTOCOL_VERSION,
            "overall_status": "HARNESS_ERROR",
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
        exit_code = 2
        config = None

    output_path = config.output if config is not None else output
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output_path),
                "overall_status": report.get("overall_status"),
            },
            ensure_ascii=False,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
