import copy
import json
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

import pytest

from scripts import evaluate_adaptive_contract as harness
from src.services.investigation.contracts import (
    ADAPTIVE_CONTRACT_VERSION,
    build_run_manifest,
    hash_source_modules,
    sha256_utf8,
)

CASES_PATH = Path("tests/eval/adaptive_contract_cases.jsonl")


def _normalized_transcript(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _manifest(*, include_optional: bool = True) -> dict:
    manifest = build_run_manifest(
        prompt="Offline fixture prediction; no model was invoked.",
        prompt_version="adaptive-eval-fixture-v1",
        model_id="offline-fixture",
        model_digest="not-a-model-run",
        provider="offline-test",
        decoding_config={"temperature": 0, "seed": 0},
        source_module_hashes=hash_source_modules(
            {"fixture_builder": "tests/test_adaptive_eval_harness.py"}
        ),
        git_revision="fixture-revision",
        git_dirty=True,
        git_untracked=True,
    ).model_dump(mode="json", exclude_none=True)
    if not include_optional:
        manifest.pop("source_module_hashes")
        manifest.pop("git_revision")
    return manifest


def _prediction_for_case(case: dict) -> dict:
    transcript = case["transcript"]
    run_status = "success" if case["gold_claims"] else "no_extractable_claims"
    base: dict[str, Any] = {
        "schema_version": ADAPTIVE_CONTRACT_VERSION,
        "run_status": run_status,
        "claims": [],
        "provenance": {
            "source_revision_id": case["source_revision_id"],
            "raw_transcript_sha256": sha256_utf8(transcript),
            "normalized_transcript_sha256": sha256_utf8(
                _normalized_transcript(transcript)
            ),
            "segment_count": len(case["segments"]),
        },
        "safety": {
            "transcript_is_untrusted_data": True,
            "evidence_required_for_released_claims": True,
            "high_risk_requires_human_verification": True,
            "unsupported_high_risk_claims_released": False,
        },
        "manifest": _manifest(include_optional=run_status != "no_extractable_claims"),
    }
    if run_status == "no_extractable_claims":
        return base

    evidence_rows: list[dict[str, Any]] = []
    claim_rows: list[dict[str, Any]] = []
    for index, gold_claim in enumerate(case["gold_claims"], start=1):
        quote = gold_claim["evidence_quote"]
        segment = next(
            segment for segment in case["segments"] if quote in segment["text"]
        )
        start = transcript.index(quote)
        evidence_id = f"runtime-evidence-{index}"
        evidence_rows.append(
            {
                "evidence_id": evidence_id,
                "segment_id": segment["segment_id"],
                "quote_exact": quote,
                "raw_char_start": start,
                "raw_char_end": start + len(quote),
                "start_seconds": segment["start_seconds"],
                "end_seconds": segment["end_seconds"],
                "speaker_id": segment["speaker_id"],
                "quote_sha256": sha256_utf8(quote),
                "source_sha256": sha256_utf8(segment["text"]),
            }
        )
        claim_rows.append(
            {
                "claim_id": f"runtime-claim-{index}",
                "claim_type": gold_claim["claim_type"],
                "statement": quote,
                "polarity": gold_claim["polarity"],
                "disposition": "supported",
                "evidence_refs": [evidence_id],
                "attributes": copy.deepcopy(gold_claim["attributes"]),
            }
        )
    base["claims"] = claim_rows
    base["evidence"] = evidence_rows
    base["themes"] = [
        {
            "theme_id": "runtime-theme-1",
            "title": "Chủ đề thích ứng",
            "claim_refs": [claim["claim_id"] for claim in claim_rows],
        }
    ]
    return base


def _cases() -> list[dict]:
    return harness.load_jsonl(CASES_PATH)


def _prediction_rows(cases: list[dict]) -> list[dict]:
    return [
        {
            "case_id": case["id"],
            "prompt_example_case_ids": [],
            "prediction": _prediction_for_case(case),
        }
        for case in cases
    ]


def _case_result(report: dict, case_id: str) -> dict:
    return next(row for row in report["case_results"] if row["case_id"] == case_id)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
        + "\n",
        encoding="utf-8",
    )


def test_valid_offline_predictions_pass_and_claim_ids_are_not_match_keys():
    cases = _cases()
    rows = _prediction_rows(cases)
    prediction = rows[0]["prediction"]
    old_id = prediction["claims"][0]["claim_id"]
    prediction["claims"][0]["claim_id"] = "arbitrary-model-id"
    prediction["themes"][0]["claim_refs"][0] = "arbitrary-model-id"
    assert old_id != prediction["claims"][0]["claim_id"]

    report = harness.evaluate(cases, rows)

    assert report["gate"]["passed"] is True
    assert report["aggregate"]["weighted_salience_coverage"] == 1.0
    assert report["aggregate"]["critical_precision"] == 1.0
    assert report["aggregate"]["critical_recall"] == 1.0
    assert report["aggregate"]["exact_value_accuracy"] == 1.0


def test_missing_critical_claim_fails_recall_and_weighted_coverage():
    cases = _cases()
    rows = _prediction_rows(cases)
    target = rows[0]["prediction"]
    removed = target["claims"].pop(0)
    target["evidence"] = [
        span
        for span in target["evidence"]
        if span["evidence_id"] not in removed["evidence_refs"]
    ]
    target["themes"][0]["claim_refs"].remove(removed["claim_id"])

    report = harness.evaluate(cases, rows)
    result = _case_result(report, rows[0]["case_id"])

    assert result["passed"] is False
    assert result["metrics"]["critical_recall"] == 0.0
    assert result["metrics"]["weighted_salience_coverage"] < 1.0


def test_slot_only_output_misses_open_discovery_and_fails_adaptive_gate():
    cases = _cases()
    rows = _prediction_rows(cases)
    prediction = rows[0]["prediction"]
    removed = next(
        claim
        for claim in prediction["claims"]
        if claim["claim_type"] == "financial.verification_condition"
    )
    prediction["claims"].remove(removed)
    prediction["evidence"] = [
        span
        for span in prediction["evidence"]
        if span["evidence_id"] not in removed["evidence_refs"]
    ]
    prediction["themes"][0]["claim_refs"].remove(removed["claim_id"])

    report = harness.evaluate(cases, rows)
    result = _case_result(report, rows[0]["case_id"])

    assert result["metrics"]["critical_recall"] == 1.0
    assert result["metrics"]["claim_recall"] < 1.0
    assert result["metrics"]["adaptive_discovery_gate_passed"] is False
    assert result["passed"] is False


def test_legacy_fixed_slot_shell_is_rejected_as_non_adaptive_output():
    cases = _cases()
    rows = _prediction_rows(cases)
    rows[0]["prediction"]["people"] = [{"name": "Nguyễn An"}]
    rows[0]["prediction"]["financial_info"] = {"amount": "50 triệu"}

    report = harness.evaluate(cases, rows)
    result = _case_result(report, rows[0]["case_id"])

    assert result["metrics"]["schema_valid"] is False
    assert result["metrics"]["legacy_slot_artifact_count"] == 2
    assert result["metrics"]["adaptive_discovery_gate_passed"] is False


def test_fake_number_is_unsupported_and_severe_hallucination():
    cases = _cases()
    rows = _prediction_rows(cases)
    claim = rows[0]["prediction"]["claims"][0]
    claim["attributes"]["amount"]["normalized"] = "70000000"
    claim["statement"] = "Hùng yêu cầu chuyển 70 triệu đồng."

    report = harness.evaluate(cases, rows)
    result = _case_result(report, rows[0]["case_id"])

    assert result["metrics"]["exact_value_accuracy"] < 1.0
    assert result["metrics"]["unsupported_claim_count"] >= 1
    assert result["metrics"]["hallucinated_number_count"] >= 1
    assert result["metrics"]["unsupported_claim_severity_counts"]["severe"] >= 1
    assert result["metrics"]["hallucinated_number_severity_counts"]["severe"] >= 1
    assert result["metrics"]["severe_hallucination_count"] >= 1


@pytest.mark.parametrize("tamper", ["quote", "quote_hash", "source_hash", "offset"])
def test_tampered_evidence_quote_hash_source_or_offset_fails(tamper):
    cases = _cases()
    rows = _prediction_rows(cases)
    span = rows[1]["prediction"]["evidence"][0]
    if tamper == "quote":
        span["quote_exact"] = "một span không có trong nguồn"
        span["quote_sha256"] = sha256_utf8(span["quote_exact"])
    elif tamper == "quote_hash":
        span["quote_sha256"] = "0" * 64
    elif tamper == "source_hash":
        span["source_sha256"] = "0" * 64
    else:
        span["raw_char_start"] += 1
        span["raw_char_end"] += 1

    report = harness.evaluate(cases, rows)
    result = _case_result(report, rows[1]["case_id"])

    assert result["metrics"]["evidence_gate_passed"] is False
    assert result["passed"] is False


@pytest.mark.parametrize(
    ("field", "tampered_value", "metric"),
    [
        ("source_revision_id", "fixture:wrong-revision", "source_revision_id_matches"),
        ("raw_transcript_sha256", "0" * 64, "raw_transcript_sha256_matches"),
        (
            "normalized_transcript_sha256",
            "0" * 64,
            "normalized_transcript_sha256_matches",
        ),
        ("segment_count", 999, "segment_count_matches"),
    ],
)
def test_source_revision_and_provenance_tamper_fails(field, tampered_value, metric):
    cases = _cases()
    rows = _prediction_rows(cases)
    rows[1]["prediction"]["provenance"][field] = tampered_value

    report = harness.evaluate(cases, rows)
    result = _case_result(report, rows[1]["case_id"])

    assert result["metrics"][metric] is False
    assert result["metrics"]["provenance_gate_passed"] is False
    assert result["passed"] is False


@pytest.mark.parametrize("invalid_value", [None, "Không có thông tin"])
def test_null_or_placeholder_optional_row_is_counted_and_rejected(invalid_value):
    cases = _cases()
    rows = _prediction_rows(cases)
    rows[0]["prediction"]["claims"][0]["attributes"]["empty_row"] = invalid_value

    report = harness.evaluate(cases, rows)
    result = _case_result(report, rows[0]["case_id"])

    assert result["metrics"]["schema_valid"] is False
    assert result["metrics"]["empty_optional_emission_count"] >= 1
    assert result["metrics"]["empty_optional_emission_rate"] > 0


def test_duplicate_primary_theme_assignment_is_detected_before_release():
    cases = _cases()
    rows = _prediction_rows(cases)
    prediction = rows[0]["prediction"]
    prediction["themes"].append(
        {
            "theme_id": "runtime-theme-2",
            "title": "Chủ đề trùng",
            "claim_refs": [prediction["claims"][0]["claim_id"]],
        }
    )

    report = harness.evaluate(cases, rows)
    result = _case_result(report, rows[0]["case_id"])

    assert result["metrics"]["schema_valid"] is False
    assert result["metrics"]["duplicate_primary_theme_assignment_count"] == 1
    assert result["passed"] is False


def test_invalid_no_extractable_state_fails_closed():
    cases = _cases()
    rows = _prediction_rows(cases)
    empty_row = next(row for row in rows if row["case_id"] == "vi-no-claim-blind")
    populated = _prediction_for_case(cases[0])
    empty_row["prediction"]["evidence"] = populated["evidence"]

    report = harness.evaluate(cases, rows)
    result = _case_result(report, "vi-no-claim-blind")

    assert result["metrics"]["schema_valid"] is False
    assert result["metrics"]["no_extractable_state_valid"] is False
    assert result["passed"] is False


def test_empty_optional_rate_is_zero_when_no_optional_row_is_emitted():
    case = next(case for case in _cases() if case["id"] == "vi-no-claim-blind")
    result = harness.score_case(case, _prediction_for_case(case))

    assert result["metrics"]["empty_optional_emission_count"] == 0
    assert result["metrics"]["optional_emission_denominator"] == 0
    assert result["metrics"]["empty_optional_emission_rate"] == 0.0


def test_blind_or_dev_prompt_example_is_a_leakage_failure():
    cases = _cases()
    rows = _prediction_rows(cases)
    rows[0]["prompt_example_case_ids"] = ["vi-code-switch-blind"]

    report = harness.evaluate(cases, rows)

    assert report["leakage"]["leakage_gate_passed"] is False
    assert report["leakage"]["leakage_violation_count"] == 1
    assert report["gate"]["passed"] is False


def test_frozen_split_tamper_requires_a_new_dataset_version(tmp_path):
    cases = _cases()
    cases[0]["split"], cases[1]["split"] = cases[1]["split"], cases[0]["split"]
    fixture_path = tmp_path / "tampered-cases.jsonl"
    _write_jsonl(fixture_path, cases)

    with pytest.raises(
        harness.EvaluationInputError, match="split fingerprint mismatch"
    ):
        harness._load_dataset(fixture_path)


def test_cli_report_is_deterministic_and_records_all_integrity_hashes(tmp_path):
    cases = _cases()
    predictions_path = tmp_path / "predictions.jsonl"
    first_output = tmp_path / "report-1.json"
    second_output = tmp_path / "report-2.json"
    _write_jsonl(predictions_path, _prediction_rows(cases))

    command = [
        sys.executable,
        "scripts/evaluate_adaptive_contract.py",
        "--fixtures",
        str(CASES_PATH),
        "--predictions",
        str(predictions_path),
        "--output",
    ]
    first = subprocess.run(
        [*command, str(first_output)],
        check=False,
        capture_output=True,
        text=True,
    )
    second = subprocess.run(
        [*command, str(second_output)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert first.returncode == second.returncode == 0
    assert first_output.read_bytes() == second_output.read_bytes()
    report = json.loads(first_output.read_text(encoding="utf-8"))
    assert report["integrity"]["input_sha256"]["fixtures"]
    assert report["integrity"]["input_sha256"]["predictions"]
    assert (
        "scripts/evaluate_adaptive_contract.py" in report["integrity"]["source_sha256"]
    )
    assert (
        "src/services/investigation/contracts.py"
        in report["integrity"]["source_sha256"]
    )
    assert report["integrity"]["evaluation_payload_sha256"]
    assert report["integrity"]["report_payload_sha256"]
    assert isinstance(report["integrity"]["git"]["tracked_dirty"], bool)
    assert isinstance(report["integrity"]["git"]["untracked"], bool)
