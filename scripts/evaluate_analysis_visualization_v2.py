"""Read-only replay harness for the simple Analysis/Visualization v2 contract.

The harness calls the analysis service but never calls update_task or commits a
database session. It fingerprints every task before and after generation so an
unexpected mutation is a hard failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.summarization.models.context_analysis import (  # noqa: E402
    CONTEXT_PROMPT_VERSION,
)

PROTOCOL_PATH = ROOT / "docs/research/analysis-visualization-v2/protocol.json"
ARTIFACT_VERSION = "stt-analysis-visualization-readonly-replay-v1"
EXPECTED_SCHEMA = "investigation-analysis-simple-v2"
EXPECTED_GENERATION = "single_prompt_llm"
EXPECTED_PROMPT_VERSION = CONTEXT_PROMPT_VERSION
KNOWN_TASK_IDS = (
    "84c115af-c025-4d0e-b0ef-cf2d4b099cc6",
    "d59205bd-7955-4143-a721-3cb40ca4ba7c",
    "cd6f85d0-ac0a-438d-86b1-a1df43d0767d",
    "c5923a81-3c7a-4e9c-aa06-29ef2c8dd887",
)
CONTENT_FIELDS = (
    "analysis_text",
    "overview",
    "key_points",
    "participants",
    "events",
    "actions",
    "decisions",
    "commitments",
    "entities",
    "relationships",
    "contradictions",
    "uncertainties",
    "follow_ups",
)
COLLECTION_FIELDS = CONTENT_FIELDS[2:]
FACTUAL_FIELDS = (
    "overview",
    "key_points",
    "events",
    "actions",
    "decisions",
    "commitments",
    "entities",
    "relationships",
)
PLACEHOLDER_PATTERNS = (
    re.compile(r"^[\s\"'\[{(:,-]*khong\s+(?:xac\s+dinh|ro)\b"),
    re.compile(r"^[\s\"'\[{(:,-]*(?:unknown|not\s+specified|n/?a)\b"),
)
HEDGING_PATTERNS = (
    re.compile(r"\bco\s+(?:ve|the|le|kha\s+nang)\b"),
    re.compile(r"\bduong\s+nhu\b"),
    re.compile(r"\b(?:perhaps|possibly|seems?|appears?)\b"),
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_text(_canonical_json(value))


def _search_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _canonical_json(value)).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return text.replace("đ", "d")


def _pattern_hits(
    payload: dict[str, Any],
    fields: tuple[str, ...],
    patterns: tuple[re.Pattern[str], ...],
) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for field in fields:
        if field not in payload:
            continue
        text = _search_text(payload.get(field))
        for pattern in patterns:
            if pattern.search(text):
                hits.append({"field": field, "pattern": pattern.pattern})
    return hits


def _hedging_hits(
    payload: dict[str, Any],
    transcript: str | None,
) -> list[dict[str, str]]:
    """Flag model-added hedging, not hedging copied verbatim from the source."""

    hits = _pattern_hits(
        payload,
        tuple(field for field in FACTUAL_FIELDS if field != "key_points"),
        HEDGING_PATTERNS,
    )
    normalized_source = (
        " ".join(transcript.split()).casefold()
        if isinstance(transcript, str)
        else None
    )
    key_points = payload.get("key_points")
    if not isinstance(key_points, list):
        return hits

    for item in key_points:
        if isinstance(item, dict):
            text = item.get("text") or item.get("statement")
            quote = item.get("evidence_quote")
        else:
            text = item
            quote = None
        if not isinstance(text, str):
            continue
        normalized_text = " ".join(text.split()).casefold()
        source_backed = False
        if normalized_source is not None and isinstance(quote, str):
            normalized_quote = " ".join(quote.split()).casefold()
            source_backed = (
                normalized_quote == normalized_text
                and normalized_quote in normalized_source
            )
        if source_backed:
            continue
        searchable = _search_text(text)
        for pattern in HEDGING_PATTERNS:
            if pattern.search(searchable):
                hits.append({"field": "key_points", "pattern": pattern.pattern})
    return hits


def _iter_rows(payload: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = payload.get(field)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _evidence_quote_hits(
    payload: dict[str, Any],
    transcript: str,
) -> list[dict[str, str]]:
    """Require emitted evidence quotes to be contiguous transcript substrings."""

    normalized_source = " ".join(transcript.split()).casefold()
    hits: list[dict[str, str]] = []
    for field in ("key_points", "actions"):
        for row in _iter_rows(payload, field):
            quote = row.get("evidence_quote")
            if not isinstance(quote, str) or not quote.strip():
                hits.append({"field": field, "reason": "missing_evidence_quote"})
                continue
            normalized_quote = " ".join(quote.split()).casefold()
            if normalized_quote not in normalized_source:
                hits.append({"field": field, "reason": "quote_not_contiguous_source"})
    return hits


def _action_enum_hits(payload: dict[str, Any]) -> list[dict[str, str]]:
    allowed_kinds = {"request", "instruction", "decision", "commitment", "next_step"}
    allowed_statuses = {"requested", "planned", "ongoing"}
    hits: list[dict[str, str]] = []
    for row in _iter_rows(payload, "actions"):
        kind = row.get("kind")
        status = row.get("status")
        if kind is not None and str(kind) not in allowed_kinds:
            hits.append({"field": "actions.kind", "value": kind})
        if status is not None and str(status) not in allowed_statuses:
            hits.append({"field": "actions.status", "value": status})
    return hits


def _placeholder_hits(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Check each scalar value so mid-sentence conditions are not placeholders."""

    hits: list[dict[str, str]] = []

    def visit(field: str, value: Any) -> None:
        if isinstance(value, dict):
            for nested in value.values():
                visit(field, nested)
            return
        if isinstance(value, list):
            for nested in value:
                visit(field, nested)
            return
        if not isinstance(value, str):
            return
        text = _search_text(value)
        for pattern in PLACEHOLDER_PATTERNS:
            if pattern.search(text):
                hits.append({"field": field, "pattern": pattern.pattern})

    for field in CONTENT_FIELDS:
        if field in payload:
            visit(field, payload[field])
    return hits


def _task_fingerprint(task: dict[str, Any]) -> str:
    return _sha256_json(task)


def _git_metadata() -> dict[str, Any]:
    def run(*args: str) -> str | None:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            return completed.stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    status = run("status", "--porcelain")
    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty": bool(status) if status is not None else None,
    }


def _load_protocol() -> dict[str, Any]:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def _runtime(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("runtime")
    return value if isinstance(value, dict) else {}


def _status(payload: dict[str, Any]) -> str:
    value = payload.get("analysis_status", payload.get("status", ""))
    return str(value or "").strip().casefold()


def _schema(payload: dict[str, Any]) -> str | None:
    value = payload.get("schema_version")
    return str(value) if value is not None else None


def _generation(payload: dict[str, Any]) -> str | None:
    runtime = _runtime(payload)
    for key in ("generation", "analysis_generation"):
        value = runtime.get(key)
        if value is not None:
            return str(value)
    for key in ("generation", "analysis_generation"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return None


def _call_count(payload: dict[str, Any]) -> int | None:
    value = _runtime(payload).get("llm_call_count")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _runtime_provenance(payload: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime(payload)
    fingerprint = runtime.get("config_fingerprint")
    return {
        "provider": runtime.get("provider"),
        "model_id": runtime.get("model_id"),
        "seed": runtime.get("seed"),
        "temperature": runtime.get("temperature"),
        "context_window_tokens": runtime.get("context_window_tokens"),
        "completion_token_budget": runtime.get("completion_token_budget"),
        "full_transcript_included": runtime.get("full_transcript_included"),
        "fits_context_window": runtime.get("fits_context_window"),
        "config_fingerprint": fingerprint,
        "config_fingerprint_valid": isinstance(fingerprint, str)
        and re.fullmatch(r"[0-9a-f]{64}", fingerprint) is not None,
    }


def _direct_text_contract(payload: dict[str, Any]) -> dict[str, Any]:
    text = payload.get("analysis_text")
    text = text.strip() if isinstance(text, str) else ""
    structured_fields = {
        field: len(payload.get(field))
        for field in COLLECTION_FIELDS
        if isinstance(payload.get(field), list) and payload.get(field)
    }
    return {
        "prompt_version": payload.get("prompt_version"),
        "analysis_text_present": bool(text),
        "plain_text": bool(text)
        and not text.startswith(("{", "[", "```"))
        and "```" not in text,
        "nonempty_structured_collections": structured_fields,
    }


def _has_useful_content(payload: dict[str, Any]) -> bool:
    for field in CONTENT_FIELDS:
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, (list, dict)) and value:
            return True
    return False


def _gate(
    gate_id: str,
    passed: bool,
    observed: Any,
    expected: Any,
) -> dict[str, Any]:
    return {
        "id": gate_id,
        "result": "PASS" if passed else "FAIL",
        "observed": observed,
        "expected": expected,
    }


def _evaluate_payload(
    payload: dict[str, Any],
    *,
    transcript: str | None = None,
) -> list[dict[str, Any]]:
    status = _status(payload)
    schema = _schema(payload)
    generation = _generation(payload)
    call_count = _call_count(payload)
    valid_status = status in {"success", "partial", "failed"}
    expected_calls: Any = 1 if status in {"success", "partial"} else "diagnostic only"
    calls_ok = (
        call_count == 1
        if status in {"success", "partial"}
        else True
    )
    collection_shapes = {
        field: type(payload.get(field)).__name__
        for field in COLLECTION_FIELDS
        if field in payload
    }
    collection_shapes_ok = all(
        isinstance(payload.get(field), list)
        for field in COLLECTION_FIELDS
        if field in payload
    )
    useful_content_ok = status == "failed" or _has_useful_content(payload)
    placeholder_hits = _placeholder_hits(payload)
    hedging_hits = _hedging_hits(payload, transcript)
    evidence_hits = (
        _evidence_quote_hits(payload, transcript)
        if isinstance(transcript, str)
        else []
    )
    action_enum_hits = _action_enum_hits(payload)
    direct = _direct_text_contract(payload)
    provenance = _runtime_provenance(payload)

    return [
        _gate("schema_version", schema == EXPECTED_SCHEMA, schema, EXPECTED_SCHEMA),
        _gate(
            "analysis_status",
            valid_status,
            status,
            ["success", "partial", "failed"],
        ),
        _gate("llm_call_count", calls_ok, call_count, expected_calls),
        _gate(
            "single_prompt_generation",
            status == "failed" or generation == EXPECTED_GENERATION,
            generation,
            EXPECTED_GENERATION,
        ),
        _gate(
            "prompt_version",
            status == "failed" or direct["prompt_version"] == EXPECTED_PROMPT_VERSION,
            direct["prompt_version"],
            EXPECTED_PROMPT_VERSION,
        ),
        _gate(
            "direct_analysis_text_present",
            status == "failed" or direct["analysis_text_present"],
            direct["analysis_text_present"],
            True,
        ),
        _gate(
            "direct_analysis_text_is_plain",
            status == "failed" or direct["plain_text"],
            direct["plain_text"],
            True,
        ),
        _gate(
            "no_model_structured_collections",
            status == "failed" or not direct["nonempty_structured_collections"],
            direct["nonempty_structured_collections"],
            {},
        ),
        _gate(
            "runtime_provenance_recorded",
            status == "failed"
            or (
                all(
                    provenance.get(field) is not None
                    for field in (
                        "provider",
                        "model_id",
                        "seed",
                        "temperature",
                        "context_window_tokens",
                        "completion_token_budget",
                    )
                )
                and provenance["config_fingerprint_valid"]
            ),
            provenance,
            "model/provider/seed/temperature/budget and SHA-256 config fingerprint",
        ),
        _gate(
            "full_transcript_budgeted_without_truncation",
            status == "failed"
            or (
                provenance["full_transcript_included"] is True
                and provenance["fits_context_window"] is True
            ),
            {
                "full_transcript_included": provenance["full_transcript_included"],
                "fits_context_window": provenance["fits_context_window"],
            },
            {
                "full_transcript_included": True,
                "fits_context_window": True,
            },
        ),
        _gate(
            "useful_content_for_nonfailed",
            useful_content_ok,
            _has_useful_content(payload),
            True if status in {"success", "partial"} else "not required",
        ),
        _gate(
            "optional_collection_shapes",
            collection_shapes_ok,
            collection_shapes,
            "all present optional collections are arrays",
        ),
        _gate(
            "no_optional_placeholders",
            status == "failed" or not placeholder_hits,
            placeholder_hits,
            [],
        ),
        _gate(
            "no_factual_hedging",
            status == "failed" or not hedging_hits,
            hedging_hits,
            [],
        ),
        _gate(
            "evidence_quotes_are_contiguous_source",
            status == "failed" or not evidence_hits,
            evidence_hits,
            [],
        ),
        _gate(
            "action_kind_and_status_are_controlled",
            status == "failed" or not action_enum_hits,
            action_enum_hits,
            [],
        ),
    ]


def _source_metadata(
    task_id: str,
    task: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "audio_id": result.get("audio_id"),
        "audio_sha256": result.get("audio_sha256"),
        "case_id": task.get("case_id") or result.get("case_id"),
        "file_name": task.get("filename") or result.get("filename"),
        "num_speakers": result.get("num_speakers"),
        "has_diarization": result.get("has_diarization"),
        "diarization_status": result.get("diarization_status"),
        "diarization_method_used": result.get("diarization_method_used"),
    }


def _replay_task(task_id: str) -> dict[str, Any]:
    from src.services.summarization.context_service import (
        analyze_conversation_context,
    )
    from src.services.task_service import get_task

    task_before = get_task(task_id)
    if not task_before:
        raise RuntimeError(f"Task not found: {task_id}")
    result = task_before.get("result")
    result = result if isinstance(result, dict) else {}
    transcript = result.get("transcription")
    segments = result.get("segments")
    if not isinstance(transcript, str) or not transcript.strip():
        raise RuntimeError(f"Task has no non-empty transcription: {task_id}")
    if not isinstance(segments, list):
        segments = []

    before_fingerprint = _task_fingerprint(task_before)
    started = time.perf_counter()
    payload = analyze_conversation_context(
        transcript,
        segments=segments,
        source_metadata=_source_metadata(task_id, task_before, result),
    )
    elapsed = time.perf_counter() - started
    task_after = get_task(task_id)
    if not task_after:
        raise RuntimeError(f"Task disappeared during replay: {task_id}")
    after_fingerprint = _task_fingerprint(task_after)
    payload = payload if isinstance(payload, dict) else {}

    gates = _evaluate_payload(payload, transcript=transcript)
    gates.append(
        _gate(
            "task_unchanged",
            before_fingerprint == after_fingerprint,
            {
                "before": before_fingerprint,
                "after": after_fingerprint,
            },
            "identical fingerprints",
        )
    )
    return {
        "task_id": task_id,
        "input": {
            "transcript_char_count": len(transcript),
            "transcript_word_count": len(transcript.split()),
            "transcript_sha256": _sha256_text(transcript),
            "segment_count": len(segments),
            "segments_sha256": _sha256_json(segments),
        },
        "result": {
            "analysis": payload,
            "analysis_sha256": _sha256_json(payload),
            "analysis_status": _status(payload),
            "schema_version": _schema(payload),
            "generation": _generation(payload),
            "llm_call_count": _call_count(payload),
            "elapsed_seconds": round(elapsed, 6),
            "section_counts": {
                field: len(payload.get(field, []))
                for field in COLLECTION_FIELDS
                if isinstance(payload.get(field), list)
            },
        },
        "gates": gates,
        "verdict": "PASS"
        if all(item["result"] == "PASS" for item in gates)
        else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument(
        "--all-known",
        action="store_true",
        help="Replay the four known persisted regression tasks.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    task_ids = list(dict.fromkeys(args.task_id))
    if args.all_known:
        task_ids.extend(item for item in KNOWN_TASK_IDS if item not in task_ids)
    if not task_ids:
        parser.error("Provide --task-id or --all-known")

    protocol = _load_protocol()
    artifact: dict[str, Any] = {
        "schema_version": ARTIFACT_VERSION,
        "protocol_version": protocol.get("schema_version"),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "workspace": str(ROOT),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "git": _git_metadata(),
        },
        "claim_boundary": protocol.get("claim_boundary"),
        "replays": [],
    }

    for task_id in task_ids:
        try:
            artifact["replays"].append(_replay_task(task_id))
        except Exception as exc:
            artifact["replays"].append(
                {
                    "task_id": task_id,
                    "verdict": "ERROR",
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                }
            )

    verdicts = [item.get("verdict") for item in artifact["replays"]]
    artifact["overall_verdict"] = (
        "PASS" if verdicts and all(item == "PASS" for item in verdicts) else "FAIL"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "overall_verdict": artifact["overall_verdict"],
                "task_count": len(artifact["replays"]),
                "verdicts": verdicts,
            },
            ensure_ascii=False,
        )
    )
    return 0 if artifact["overall_verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
