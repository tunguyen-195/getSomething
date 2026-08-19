"""Verify authenticated Analysis generation, persistence, cache, and projection."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import settings
from src.services.summarization.models.context_analysis import (
    ANALYSIS_GENERATION,
    ANALYSIS_SCHEMA_VERSION,
    CONTEXT_PROMPT_VERSION,
)
from src.services.summarization.public_projection import (
    public_context_analysis_payload,
)
from src.services.task_service import get_task


ENDPOINT_SAFETY_POLICY = "literal-loopback-api-v1-no-redirect-v1"
_COLLECTION_FIELDS = (
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
_FORBIDDEN_PUBLIC_FIELDS = {
    "analysis_generation",
    "evidence_quote",
    "internal",
    "model_generated",
    "prompt_version",
    "provenance",
    "raw_llm_response",
    "raw_response",
    "requires_human_verification",
    "runtime",
    "segments_sha256",
    "signature",
    "source_metadata",
    "source_task_id",
    "transcript_sha256",
}


def _validate_base_url(value: str) -> str:
    normalized = value.rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme != "http" or not parsed.hostname:
        raise ValueError("E2E API URL must use HTTP with a literal loopback IP")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("E2E API URL cannot contain credentials, query, or fragment")
    try:
        is_loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError as exc:
        raise ValueError("E2E API URL must use a literal loopback IP") from exc
    if not is_loopback:
        raise ValueError("E2E API URL must stay on the local machine")
    if parsed.path.rstrip("/") != "/api/v1":
        raise ValueError("E2E API URL path must be exactly /api/v1")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("E2E API URL port is invalid") from exc
    return normalized


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _collection_counts(analysis: dict[str, Any]) -> dict[str, int]:
    return {
        key: len(analysis.get(key) or [])
        for key in _COLLECTION_FIELDS
        if isinstance(analysis.get(key), list)
    }


def _persisted_analysis_facts(value: Any) -> dict[str, Any]:
    analysis = value if isinstance(value, dict) else {}
    runtime = analysis.get("runtime") if isinstance(analysis.get("runtime"), dict) else {}
    metrics = analysis.get("metrics") if isinstance(analysis.get("metrics"), dict) else {}
    return {
        "sha256": _canonical_hash(analysis),
        "schema_version": analysis.get("schema_version"),
        "analysis_status": analysis.get("analysis_status"),
        "analysis_generation": analysis.get("analysis_generation"),
        "prompt_version": analysis.get("prompt_version"),
        "llm_call_count": runtime.get("llm_call_count"),
        "transcript_word_count": metrics.get("transcript_word_count"),
        "transcript_segment_count": metrics.get("transcript_segment_count"),
        "transcript_sha256": metrics.get("transcript_sha256"),
        "segments_sha256": metrics.get("segments_sha256"),
        "source_task_id": metrics.get("source_task_id"),
        "speaker_contribution_count": len(analysis.get("speaker_contributions") or [])
        if isinstance(analysis.get("speaker_contributions"), list)
        else 0,
        "collection_counts": _collection_counts(analysis),
        "has_analysis_text": bool(str(analysis.get("analysis_text") or "").strip()),
    }


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            nested
            for item in value.values()
            for nested in _all_keys(item)
        }
    if isinstance(value, list):
        return {nested for item in value for nested in _all_keys(item)}
    return set()


def _public_analysis_facts(value: Any) -> dict[str, Any]:
    analysis = value if isinstance(value, dict) else {}
    metrics = analysis.get("metrics") if isinstance(analysis.get("metrics"), dict) else {}
    return {
        "sha256": _canonical_hash(analysis),
        "schema_version": analysis.get("schema_version"),
        "analysis_status": analysis.get("analysis_status"),
        "transcript_word_count": metrics.get("transcript_word_count"),
        "transcript_segment_count": metrics.get("transcript_segment_count"),
        "transcript_duration_seconds": metrics.get("transcript_duration_seconds"),
        "collection_counts": _collection_counts(analysis),
        "has_analysis_text": bool(str(analysis.get("analysis_text") or "").strip()),
        "forbidden_fields_present": sorted(_all_keys(analysis) & _FORBIDDEN_PUBLIC_FIELDS),
    }


def _result_analysis(task: dict[str, Any] | None) -> tuple[dict[str, Any] | None, Any]:
    result = task.get("result") if isinstance(task, dict) else None
    result = result if isinstance(result, dict) else {}
    analysis = result.get("context_analysis")
    return (analysis if isinstance(analysis, dict) else None), result.get(
        "context_analysis_attestation"
    )


def _request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout: float,
    **kwargs: Any,
) -> tuple[int, Any]:
    kwargs["allow_redirects"] = False
    response = session.request(method, url, timeout=timeout, **kwargs)
    try:
        payload: Any = response.json()
    except ValueError:
        payload = None
    return response.status_code, payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    try:
        base_url = _validate_base_url(args.base_url)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if settings.AUTH_ENABLED is not True:
        raise SystemExit("Authenticated E2E requires AUTH_ENABLED=true")

    task_before = get_task(args.task_id)
    if not task_before:
        raise SystemExit("Task not found")
    result_before = (
        task_before.get("result")
        if isinstance(task_before.get("result"), dict)
        else {}
    )
    transcript = result_before.get("transcription")
    if not isinstance(transcript, str) or not transcript.strip():
        raise SystemExit("Task has no transcript")
    if isinstance(result_before.get("context_analysis"), dict):
        raise SystemExit("Task already has persisted Analysis; cache-miss gate unavailable")

    session = requests.Session()
    session.trust_env = False
    checks: list[dict[str, Any]] = [
        {"name": "endpoint_policy", "passed": True},
        {"name": "auth_enabled", "passed": True},
    ]

    csrf_status, csrf_payload = _request_json(
        session,
        "GET",
        f"{base_url}/auth/csrf",
        timeout=args.timeout,
    )
    csrf_token = (
        csrf_payload.get("csrf_token") if isinstance(csrf_payload, dict) else None
    )
    if csrf_status != 200 or not csrf_token:
        raise SystemExit("Unauthenticated CSRF preflight failed; credentials were not sent")
    checks.append({"name": "csrf_preflight", "passed": True, "http": csrf_status})

    username = os.getenv("STT_API_USERNAME")
    password = os.getenv("STT_API_PASSWORD")
    if not username or not password:
        raise SystemExit("Set STT_API_USERNAME and STT_API_PASSWORD for the E2E run")

    login_status, login_payload = _request_json(
        session,
        "POST",
        f"{base_url}/auth/login",
        timeout=args.timeout,
        json={"username": username, "password": str(password)},
        headers={"x-csrf-token": str(csrf_token or "")},
    )
    authenticated = login_status == 200 and isinstance(login_payload, dict)
    if not authenticated:
        raise SystemExit("Authenticated E2E login failed")
    checks.append({"name": "login", "passed": True, "http": login_status})

    refreshed_status, refreshed_payload = _request_json(
        session,
        "GET",
        f"{base_url}/auth/csrf",
        timeout=args.timeout,
    )
    refreshed_csrf = (
        refreshed_payload.get("csrf_token")
        if isinstance(refreshed_payload, dict)
        else None
    )
    if refreshed_status != 200 or not refreshed_csrf:
        raise SystemExit("Authenticated CSRF refresh failed")
    checks.append(
        {"name": "authenticated_csrf", "passed": True, "http": refreshed_status}
    )

    request_body = {
        "summary": "Authenticated runtime verification request.",
        "task_id": args.task_id,
    }
    segments = (
        result_before.get("segments")
        if isinstance(result_before.get("segments"), list)
        else []
    )
    normalized_transcript = " ".join(transcript.split())
    expected_transcript_sha256 = hashlib.sha256(
        normalized_transcript.encode("utf-8")
    ).hexdigest()
    expected_segments_sha256 = hashlib.sha256(
        json.dumps(
            segments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    started = time.perf_counter()
    first_status, first_payload = _request_json(
        session,
        "POST",
        f"{base_url}/summaries/analyze",
        timeout=args.timeout,
        json=request_body,
        headers={"x-csrf-token": str(refreshed_csrf or "")},
    )
    first_seconds = round(time.perf_counter() - started, 6)
    first_public_analysis = (
        first_payload.get("context_analysis")
        if isinstance(first_payload, dict)
        else None
    )
    first_public_facts = _public_analysis_facts(first_public_analysis)
    task_after_first = get_task(args.task_id)
    persisted, persisted_attestation = _result_analysis(task_after_first)
    persisted_facts = _persisted_analysis_facts(persisted)
    expected_public = public_context_analysis_payload(persisted)
    checks.append(
        {
            "name": "first_call_generation",
            "passed": (
                first_status == 200
                and isinstance(first_payload, dict)
                and first_payload.get("cache_hit") is False
                and persisted_facts["schema_version"] == ANALYSIS_SCHEMA_VERSION
                and persisted_facts["analysis_status"] == "success"
                and persisted_facts["analysis_generation"] == ANALYSIS_GENERATION
                and persisted_facts["prompt_version"] == CONTEXT_PROMPT_VERSION
                and type(persisted_facts["llm_call_count"]) is int
                and persisted_facts["llm_call_count"] == 1
                and persisted_facts["has_analysis_text"] is True
                and first_public_analysis == expected_public
            ),
            "http": first_status,
        }
    )

    checks.append(
        {
            "name": "source_binding",
            "passed": (
                persisted_facts["transcript_word_count"] == len(transcript.split())
                and persisted_facts["transcript_segment_count"] == len(segments)
                and persisted_facts["transcript_sha256"]
                == expected_transcript_sha256
                and persisted_facts["segments_sha256"] == expected_segments_sha256
                and persisted_facts["source_task_id"] == str(args.task_id)
            ),
        }
    )

    checks.append(
        {
            "name": "persistence",
            "passed": (
                isinstance(persisted, dict)
                and isinstance(persisted_attestation, dict)
                and bool(persisted_attestation.get("signature"))
            ),
        }
    )

    started = time.perf_counter()
    second_status, second_payload = _request_json(
        session,
        "POST",
        f"{base_url}/summaries/analyze",
        timeout=args.timeout,
        json=request_body,
        headers={"x-csrf-token": str(refreshed_csrf or "")},
    )
    second_seconds = round(time.perf_counter() - started, 6)
    second_public_analysis = (
        second_payload.get("context_analysis")
        if isinstance(second_payload, dict)
        else None
    )
    second_public_facts = _public_analysis_facts(second_public_analysis)
    checks.append(
        {
            "name": "second_call_cache",
            "passed": (
                second_status == 200
                and isinstance(second_payload, dict)
                and second_payload.get("cache_hit") is True
                and second_public_analysis == expected_public
            ),
            "http": second_status,
        }
    )

    public_status, public_payload = _request_json(
        session,
        "GET",
        f"{base_url}/audio/tasks/{args.task_id}",
        timeout=args.timeout,
    )
    public_analysis = (
        public_payload.get("context_analysis")
        if isinstance(public_payload, dict)
        else None
    )
    public_facts = _public_analysis_facts(public_analysis)
    checks.append(
        {
            "name": "public_projection",
            "passed": (
                public_status == 200
                and isinstance(public_analysis, dict)
                and public_analysis == expected_public
                and public_facts["schema_version"] == ANALYSIS_SCHEMA_VERSION
                and public_facts["analysis_status"] == "success"
                and public_facts["has_analysis_text"] is True
                and public_facts["transcript_word_count"]
                == len(transcript.split())
                and public_facts["transcript_segment_count"] == len(segments)
                and not public_facts["forbidden_fields_present"]
            ),
            "http": public_status,
        }
    )

    passed = all(check["passed"] for check in checks)
    artifact = {
        "schema_version": "stt-authenticated-analysis-e2e-v3",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "task_id": args.task_id,
        "endpoint_safety": {
            "policy": ENDPOINT_SAFETY_POLICY,
            "base_url": base_url,
            "literal_loopback": True,
            "trust_env": False,
            "redirects_allowed": False,
        },
        "expected_analysis_contract": {
            "schema_version": ANALYSIS_SCHEMA_VERSION,
            "analysis_status": "success",
            "analysis_generation": ANALYSIS_GENERATION,
            "prompt_version": CONTEXT_PROMPT_VERSION,
            "llm_call_count": 1,
        },
        "input": {
            "transcript_sha256": hashlib.sha256(transcript.encode("utf-8")).hexdigest(),
            "transcript_word_count": len(transcript.split()),
            "segment_count": len(segments),
            "had_analysis_before": False,
        },
        "authentication": {
            "auth_enabled": bool(settings.AUTH_ENABLED),
            "authenticated": authenticated,
            "credentials_recorded": False,
        },
        "first_call": {
            "cache_hit": first_payload.get("cache_hit") if isinstance(first_payload, dict) else None,
            "seconds": first_seconds,
            "public_analysis": first_public_facts,
        },
        "persistence": {
            "analysis_contract": persisted_facts,
            "attestation_present": isinstance(persisted_attestation, dict),
            "attestation_signature_present": bool(
                persisted_attestation.get("signature")
            ) if isinstance(persisted_attestation, dict) else False,
        },
        "second_call": {
            "cache_hit": second_payload.get("cache_hit") if isinstance(second_payload, dict) else None,
            "seconds": second_seconds,
            "public_analysis": second_public_facts,
        },
        "public_projection": {
            "public_contract": public_facts,
            "forbidden_internal_fields_present": public_facts[
                "forbidden_fields_present"
            ],
        },
        "checks": checks,
        "status": "PASS" if passed else "FAIL",
        "privacy": {
            "transcript_recorded": False,
            "analysis_text_recorded": False,
            "credentials_recorded": False,
            "cookies_recorded": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "status": artifact["status"],
                "checks": {row["name"]: row["passed"] for row in checks},
                "first_seconds": first_seconds,
                "second_seconds": second_seconds,
            },
            ensure_ascii=False,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
