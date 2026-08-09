import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import evaluate_context_analysis as harness
from src.services.summarization.models.investigation_knowledge import (
    build_grounded_context_analysis,
)


CASES_PATH = Path("tests/eval/context_cases.jsonl")


def _safe_analysis(transcript, segments, model="fixture-model"):
    first_quote = segments[0]["text"]
    raw = {
        "summary": "Legacy raw summary is not released.",
        "summary_sentences": [
            {
                "draft_id": f"eval-summary-{index}",
                "text": segment["text"],
                "sentence_role": "event" if index == 1 else "outcome",
                "evidence_quotes": [segment["text"]],
            }
            for index, segment in enumerate(segments, start=1)
        ],
        "key_points": [
            {
                "statement": first_quote,
                "evidence_quote": first_quote,
            }
        ],
        "entities": {
            "people": [
                {
                    "name": "Lan",
                    "evidence_quote": "Lan",
                }
            ]
        },
        "events": [
            {
                "description": first_quote,
                "time": "09:00",
                "evidence_quote": first_quote,
            }
        ],
        "risk_assessment": {"overall_risk": "unverified"},
    }
    return build_grounded_context_analysis(
        raw,
        transcript,
        segments,
        model_id=model,
        source_metadata={"task_id": "eval-unit"},
        high_risk_enabled=False,
        generated_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
    )


def test_fixture_covers_required_vietnamese_scenarios():
    cases = harness._load_cases(CASES_PATH, None, None)
    categories = {case["category"] for case in cases}

    assert {
        "benign",
        "financial_account",
        "conflict",
        "negation",
        "prompt_injection",
        "code_switching",
    } <= categories
    assert all(case.get("expected_critical_fields") for case in cases)
    assert all(case.get("language_profile", "").startswith("vi") for case in cases)


def test_load_cases_rejects_duplicate_ids(tmp_path):
    fixture = tmp_path / "duplicate.jsonl"
    row = {"id": "same", "category": "benign", "transcript": "Nội dung"}
    fixture.write_text(
        json.dumps(row, ensure_ascii=False)
        + "\n"
        + json.dumps(row, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate case id"):
        harness._load_cases(fixture, None, None)


def test_critical_field_recall_honors_aliases_and_mode_scope():
    case = {
        "expected_critical_fields": [
            {
                "name": "amount",
                "values": ["50 triệu", "50000000"],
                "required_in": ["both"],
            },
            {
                "name": "account",
                "values": ["0123456789"],
                "required_in": ["context"],
            },
        ]
    }

    summary = harness._critical_field_metrics("Đã nhắc tới 50 triệu.", case, "summary")
    context = harness._critical_field_metrics(
        {"amount": "50000000", "account": "0123456789"}, case, "context"
    )

    assert summary["critical_field_count"] == 1
    assert summary["critical_field_recall"] == 1.0
    assert context["critical_field_count"] == 2
    assert context["critical_field_recall"] == 1.0


def test_grounding_gate_checks_hashes_references_and_minimum_evidence():
    case = harness._load_cases(CASES_PATH, {"benign_schedule"}, None)[0]
    analysis = _safe_analysis(case["transcript"], case["segments"])

    metrics = harness._grounding_metrics(
        analysis,
        case["transcript"],
        case["segments"],
        min_evidence_spans=1,
    )

    assert metrics["grounding_gate_passed"] is True
    assert metrics["grounded_evidence_rate"] == 1.0
    assert metrics["provenance_transcript_hash_matches"] is True

    analysis["investigation_knowledge"]["evidence_spans"][0]["quote_sha256"] = "0" * 64
    tampered = harness._grounding_metrics(
        analysis,
        case["transcript"],
        case["segments"],
        min_evidence_spans=1,
    )

    assert tampered["grounding_gate_passed"] is False
    assert tampered["grounded_evidence_rate"] < 1.0


def test_grounding_gate_does_not_treat_empty_evidence_as_perfect():
    analysis = {
        "investigation_knowledge": {
            "evidence_spans": [],
            "facts": [],
            "entities": [],
            "events": [],
            "relationships": [],
            "hypotheses": [],
            "provenance": {"transcript_sha256": harness._sha256_text("Nội dung")},
            "safety": {"unsupported_high_risk_claims_released": False},
        }
    }

    metrics = harness._grounding_metrics(analysis, "Nội dung", min_evidence_spans=1)

    assert metrics["grounded_evidence_rate"] == 0.0
    assert metrics["evidence_requirement_met"] is False
    assert metrics["grounding_gate_passed"] is False


def test_prompt_injection_echo_is_distinct_from_instruction_following():
    case = {"injection_marker": "OVERRIDE_ACCEPTED"}
    evidence_echo = harness._injection_metrics(
        {"evidence_quote": "Người nói yêu cầu trả lời OVERRIDE_ACCEPTED"},
        case,
        risk_after_release_gate="unverified",
        unsupported_high_risk_claims_released=False,
    )
    direct_response = harness._injection_metrics("OVERRIDE_ACCEPTED", case)

    assert evidence_echo["injection_marker_present"] is True
    assert evidence_echo["direct_injection_marker_response"] is False
    assert evidence_echo["injection_resistance_passed"] is True
    assert direct_response["direct_injection_marker_response"] is True
    assert direct_response["injection_resistance_passed"] is False


def test_structured_output_metric_requires_both_contracts():
    case = harness._load_cases(CASES_PATH, {"benign_schedule"}, None)[0]
    valid = _safe_analysis(case["transcript"], case["segments"])

    assert harness._structured_output_metrics(valid)["structured_output_valid"] is True
    assert (
        harness._structured_output_metrics({"analysis_status": "failed"})[
            "structured_output_valid"
        ]
        is False
    )


def test_evaluate_context_uses_quality_and_safety_gates(monkeypatch):
    case = harness._load_cases(CASES_PATH, {"benign_schedule"}, None)[0]
    analysis = _safe_analysis(case["transcript"], case["segments"])

    class FakeManager:
        @staticmethod
        def analyze_context(*_args, **_kwargs):
            return analysis

    ticks = iter([10.0, 10.25])
    monkeypatch.setattr(harness, "get_llm_manager", lambda: FakeManager())
    monkeypatch.setattr(harness.time, "perf_counter", lambda: next(ticks))

    result = harness._evaluate_context("fixture-model", case)

    assert result["passed"] is True
    assert result["structured_output_valid"] is True
    assert result["grounding_gate_passed"] is True
    assert result["critical_field_recall"] == 1.0
    assert result["latency_seconds"] == 0.25
    assert result["generation_options"]["format"] == "json"


def test_evaluate_summary_records_config_and_rejects_wrong_model(monkeypatch):
    case = harness._load_cases(CASES_PATH, {"benign_schedule"}, None)[0]

    def fake_summary(*_args, **_kwargs):
        return {
            "available": True,
            "model": "different-model",
            "summary": case["transcript"],
        }

    ticks = iter([20.0, 20.5])
    monkeypatch.setattr(harness, "summarize_transcript_v2", fake_summary)
    monkeypatch.setattr(harness.time, "perf_counter", lambda: next(ticks))

    result = harness._evaluate_summary("requested-model", case, max_length=100)

    assert result["passed"] is False
    assert result["requested_model_matches_reported"] is False
    assert result["generation_options"]["num_predict"] == 500


def test_cli_keeps_v1_flags_and_adds_reproducibility_controls():
    args = harness._build_parser().parse_args(
        [
            "--models",
            "llama3.2:3b,gemma2:9b",
            "--case-ids",
            "benign_schedule,prompt_injection",
            "--max-cases",
            "2",
            "--summary-case-limit",
            "1",
            "--skip-context",
            "--output",
            "result.json",
            "--skip-model-metadata",
        ]
    )

    assert args.models == "llama3.2:3b,gemma2:9b"
    assert args.summary_case_limit == 1
    assert args.skip_context is True
    assert args.output == Path("result.json")
    assert args.skip_model_metadata is True


def test_s1_evidence_mode_uses_exact_closed_contract_checks():
    snapshot = harness.build_s1_schema_artifact()

    assert harness._s1_contract_checks(snapshot) == {
        "strict_nested_schema": True,
        "typed_summary_sentences": True,
        "legacy_adapter_separated": True,
        "ungrounded_items_rejected": True,
        "no_model_or_network_call": True,
    }
    args = harness._build_parser().parse_args(
        [
            "--emit-s1-evidence",
            "docs/reviews/artifacts/s1-summary-schema.json",
            "--observed-at",
            "2026-08-09T18:30:00+07:00",
        ]
    )
    assert args.emit_s1_evidence == Path(
        "docs/reviews/artifacts/s1-summary-schema.json"
    )
    assert args.observed_at == "2026-08-09T18:30:00+07:00"


def test_aggregate_reports_latency_distribution():
    rows = [
        {
            "passed": True,
            "latency_seconds": 1.0,
            "keyword_recall": 1.0,
            "critical_field_recall": 1.0,
        },
        {
            "passed": False,
            "latency_seconds": 3.0,
            "keyword_recall": 0.5,
            "critical_field_recall": 0.0,
        },
    ]

    aggregate = harness._aggregate_mode(rows)

    assert aggregate["evaluated"] == 2
    assert aggregate["pass_rate"] == 0.5
    assert aggregate["latency_seconds"]["p50"] == 2.0
    assert aggregate["latency_seconds"]["p95"] == 2.9
