from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from scripts import verify_authenticated_analysis_e2e as harness
from src.services.summarization.models.context_analysis import (
    ANALYSIS_GENERATION,
    ANALYSIS_SCHEMA_VERSION,
    CONTEXT_PROMPT_VERSION,
)


@pytest.mark.parametrize(
    "value",
    [
        "http://127.0.0.1:8000/api/v1",
        "http://127.10.20.30:8000/api/v1/",
        "http://[::1]:8000/api/v1",
    ],
)
def test_e2e_base_url_accepts_only_literal_loopback_api(value: str) -> None:
    assert harness._validate_base_url(value).endswith("/api/v1")


@pytest.mark.parametrize(
    "value",
    [
        "http://localhost:8000/api/v1",
        "http://192.168.1.10:8000/api/v1",
        "https://127.0.0.1:8000/api/v1",
        "http://admin:secret@127.0.0.1:8000/api/v1",
        "http://127.0.0.1:8000/api/v1?next=remote",
        "http://127.0.0.1:8000/api/v1#fragment",
        "http://127.0.0.1:8000/api/v2",
        "http://127.0.0.1:bad/api/v1",
    ],
)
def test_e2e_base_url_rejects_credential_exfiltration_surfaces(value: str) -> None:
    with pytest.raises(ValueError):
        harness._validate_base_url(value)


def test_request_json_always_disables_redirects() -> None:
    observed: dict[str, object] = {}

    class Session:
        def request(self, method: str, url: str, **kwargs):
            observed.update({"method": method, "url": url, **kwargs})
            return SimpleNamespace(status_code=200, json=lambda: {"ok": True})

    status, payload = harness._request_json(
        Session(),  # type: ignore[arg-type]
        "POST",
        "http://127.0.0.1:8000/api/v1/auth/login",
        timeout=5,
        allow_redirects=True,
        json={"username": "not-recorded"},
    )

    assert status == 200
    assert payload == {"ok": True}
    assert observed["allow_redirects"] is False


def test_analysis_facts_match_current_persisted_and_public_schema() -> None:
    persisted = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "analysis_status": "success",
        "analysis_generation": ANALYSIS_GENERATION,
        "prompt_version": CONTEXT_PROMPT_VERSION,
        "analysis_text": "Phan tich noi dung.",
        "runtime": {"llm_call_count": 1},
        "metrics": {
            "transcript_word_count": 3,
            "transcript_segment_count": 2,
            "transcript_sha256": "a" * 64,
            "segments_sha256": "b" * 64,
            "source_task_id": "task-1",
        },
        "key_points": [],
        "speaker_contributions": [{"speaker": "SPEAKER_00"}],
    }
    public = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "analysis_status": "success",
        "analysis_text": "Phan tich noi dung.",
        "metrics": {
            "transcript_word_count": 3,
            "transcript_segment_count": 2,
            "transcript_duration_seconds": 1.5,
        },
        "key_points": [],
    }

    persisted_facts = harness._persisted_analysis_facts(persisted)
    public_facts = harness._public_analysis_facts(public)

    assert persisted_facts["transcript_segment_count"] == 2
    assert persisted_facts["analysis_generation"] == ANALYSIS_GENERATION
    assert persisted_facts["speaker_contribution_count"] == 1
    assert public_facts["transcript_segment_count"] == 2
    assert public_facts["forbidden_fields_present"] == []


def test_public_analysis_facts_detect_internal_fields_recursively() -> None:
    facts = harness._public_analysis_facts(
        {
            "schema_version": ANALYSIS_SCHEMA_VERSION,
            "analysis_status": "success",
            "analysis_text": "Phan tich.",
            "metrics": {"transcript_word_count": 1},
            "key_points": [{"text": "Diem chinh", "evidence_quote": "noi bo"}],
        }
    )

    assert facts["forbidden_fields_present"] == ["evidence_quote"]


def test_main_rejects_unsafe_endpoint_before_task_or_credentials(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        harness,
        "get_task",
        lambda _task_id: (_ for _ in ()).throw(AssertionError("task read occurred")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_authenticated_analysis_e2e.py",
            "--task-id",
            "task-1",
            "--output",
            str(tmp_path / "artifact.json"),
            "--base-url",
            "http://example.com/api/v1",
        ],
    )

    with pytest.raises(SystemExit, match="literal loopback IP"):
        harness.main()


def test_main_requires_auth_before_task_access(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(harness.settings, "AUTH_ENABLED", False)
    monkeypatch.setattr(
        harness,
        "get_task",
        lambda _task_id: (_ for _ in ()).throw(AssertionError("task read occurred")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_authenticated_analysis_e2e.py",
            "--task-id",
            "task-1",
            "--output",
            str(tmp_path / "artifact.json"),
        ],
    )

    with pytest.raises(SystemExit, match="AUTH_ENABLED=true"):
        harness.main()
