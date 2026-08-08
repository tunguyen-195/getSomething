"""Score canonical adaptive Summary/Analysis predictions without loading a model.

The pilot evaluator is deliberately deterministic and offline. It validates the
shared contract, compares atomic claims against versioned Vietnamese fixtures,
and emits only metrics and integrity metadata (never transcripts or predictions).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.investigation.contracts import (  # noqa: E402
    AdaptiveSummaryAnalysisContract,
    canonical_json,
    sha256_canonical_json,
    sha256_utf8,
    validate_adaptive_contract,
)

PROTOCOL_VERSION = "adaptive-intelligence-eval-v3-pilot"
DATASET_VERSION = "adaptive-intelligence-pilot-v1.0"
FROZEN_SPLIT_SHA256 = "2e9f7dd7d2bada9d07fb7813345899b5eee68cfae5e844b77688ea133dd50b54"
SALIENCE_WEIGHTS = {"critical": 5, "important": 2, "optional": 1}
VALID_SPLITS = frozenset({"train", "dev", "blind"})
VALID_POLARITIES = frozenset(
    {"affirmed", "negated", "uncertain", "reported", "quoted_instruction"}
)
PLACEHOLDER_VALUES = frozenset(
    {
        "không có thông tin",
        "cần xác minh thêm",
        "không rõ",
        "n/a",
        "null",
    }
)
OPTIONAL_PROPERTY_NAMES = frozenset(
    {
        "evidence",
        "concepts",
        "relationships",
        "themes",
        "narrative",
        "attributes",
        "concept_refs",
        "quote_prefix",
        "quote_suffix",
        "raw_char_start",
        "raw_char_end",
        "start_seconds",
        "end_seconds",
        "speaker_id",
        "task_id",
        "audio_id",
        "audio_sha256",
        "asr_model_id",
        "diarization_model_id",
        "source_module_hashes",
        "git_revision",
        "thematic_groups",
    }
)
COLLECTION_PROPERTY_NAMES = frozenset(
    {
        "claims",
        "evidence",
        "concepts",
        "relationships",
        "themes",
        "overview",
        "thematic_groups",
        "sentences",
    }
)
LEGACY_SLOT_KEYS = frozenset(
    {
        "people",
        "persons",
        "time",
        "location",
        "financial_info",
        "sensitive_info",
        "risk_assessment",
        "timeline",
        "actions",
        "decisions",
    }
)
NUMBER_PATTERN = re.compile(r"(?<![\w])\d(?:[\d.,:/-]*\d)?(?![\w])", re.UNICODE)


class EvaluationInputError(ValueError):
    """Raised when fixtures or predictions violate the evaluation protocol."""


def _normalize_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value))
    return " ".join(normalized.split()).casefold()


def _normalize_scalar(value: Any) -> str:
    if isinstance(value, str):
        return _normalize_text(value)
    return canonical_json(value)


def _is_empty_optional_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        normalized = _normalize_text(value)
        return not normalized or normalized in PLACEHOLDER_VALUES
    if isinstance(value, (list, dict)):
        return not value
    return False


def _empty_optional_metrics(payload: Any) -> dict[str, float | int]:
    """Count explicitly emitted optional properties/rows.

    The denominator is the number of optional properties plus collection rows
    actually emitted. If none are emitted, the rate is defined as 0.0.
    """

    emitted = 0
    invalid = 0

    def walk(value: Any, *, inside_attributes: bool = False) -> None:
        nonlocal emitted, invalid
        if isinstance(value, Mapping):
            for raw_key, item in value.items():
                key = str(raw_key)
                is_optional = inside_attributes or key in OPTIONAL_PROPERTY_NAMES
                if is_optional:
                    emitted += 1
                    if _is_empty_optional_value(item):
                        invalid += 1
                if isinstance(item, list) and key in COLLECTION_PROPERTY_NAMES:
                    for row in item:
                        emitted += 1
                        if _is_empty_optional_value(row):
                            invalid += 1
                if not _is_empty_optional_value(item):
                    walk(
                        item, inside_attributes=inside_attributes or key == "attributes"
                    )
        elif isinstance(value, list):
            for item in value:
                if not _is_empty_optional_value(item):
                    walk(item, inside_attributes=inside_attributes)

    walk(payload)
    rate = invalid / emitted if emitted else 0.0
    return {
        "empty_optional_emission_count": invalid,
        "optional_emission_denominator": emitted,
        "empty_optional_emission_rate": round(rate, 6),
    }


def _flatten_attributes(
    value: Any,
    prefix: tuple[str, ...] = (),
) -> dict[str, str]:
    flattened: dict[str, str] = {}
    if isinstance(value, Mapping):
        for key in sorted(value, key=str):
            flattened.update(_flatten_attributes(value[key], (*prefix, str(key))))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            flattened.update(_flatten_attributes(item, (*prefix, str(index))))
    else:
        flattened[".".join(prefix)] = _normalize_scalar(value)
    return flattened


def _claim_base_key(claim: Mapping[str, Any]) -> tuple[str, str]:
    return (
        _normalize_text(claim.get("claim_type", "")),
        _normalize_text(claim.get("polarity", "")),
    )


def _claim_signature(claim: Mapping[str, Any], attribute_key: str) -> tuple[Any, ...]:
    attributes = _flatten_attributes(claim.get(attribute_key) or {})
    return (*_claim_base_key(claim), tuple(sorted(attributes.items())))


def _validate_gold_claim(claim: Mapping[str, Any], case_id: str) -> None:
    required = {"claim_type", "polarity", "salience", "attributes", "evidence_quote"}
    missing = sorted(required - set(claim))
    if missing:
        raise EvaluationInputError(
            f"case {case_id} gold claim is missing: {', '.join(missing)}"
        )
    if claim["polarity"] not in VALID_POLARITIES:
        raise EvaluationInputError(f"case {case_id} has invalid gold polarity")
    if claim["salience"] not in SALIENCE_WEIGHTS:
        raise EvaluationInputError(f"case {case_id} has invalid salience")
    if not isinstance(claim.get("attributes"), dict):
        raise EvaluationInputError(f"case {case_id} attributes must be an object")
    if not str(claim.get("evidence_quote", "")):
        raise EvaluationInputError(f"case {case_id} gold claim requires evidence_quote")


def _gold_run_status(case: Mapping[str, Any]) -> str:
    if case.get("gold_claims"):
        return "success"
    return "no_extractable_claims" if case.get("allow_no_claims") is True else "invalid"


def _gold_evidence_segment(
    case: Mapping[str, Any], claim: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    quote = str(claim.get("evidence_quote", ""))
    matches = [segment for segment in case["segments"] if quote in str(segment["text"])]
    return matches[0] if len(matches) == 1 else None


def _split_fingerprint(cases: Sequence[Mapping[str, Any]]) -> str:
    split_rows = [
        {"case_id": str(case["id"]), "split": str(case["split"])}
        for case in sorted(cases, key=lambda item: str(item["id"]))
    ]
    return sha256_canonical_json(split_rows)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, raw_line in enumerate(source, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvaluationInputError(
                    f"{path}:{line_number}: invalid JSON"
                ) from exc
            if not isinstance(row, dict):
                raise EvaluationInputError(
                    f"{path}:{line_number}: row must be an object"
                )
            rows.append(row)
    if not rows:
        raise EvaluationInputError(f"{path}: no JSONL rows")
    return rows


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Public deterministic JSONL loader used by the pilot tests and CLI."""

    return _load_jsonl(path)


def _load_dataset(path: Path) -> tuple[list[dict[str, Any]], str]:
    cases = _load_jsonl(path)
    seen_ids: set[str] = set()
    seen_source_revisions: set[str] = set()
    splits: set[str] = set()
    for case in cases:
        required = {
            "dataset_version",
            "id",
            "split",
            "source_revision_id",
            "transcript",
            "segments",
            "gold_claims",
            "allow_no_claims",
        }
        missing = sorted(required - set(case))
        if missing:
            raise EvaluationInputError(
                f"fixture row missing fields: {', '.join(missing)}"
            )
        if case["dataset_version"] != DATASET_VERSION:
            raise EvaluationInputError(f"case {case['id']} has unknown dataset version")
        case_id = str(case["id"])
        if case_id in seen_ids:
            raise EvaluationInputError(f"duplicate fixture case ID: {case_id}")
        seen_ids.add(case_id)
        source_revision_id = str(case["source_revision_id"])
        expected_revision_id = f"fixture:{DATASET_VERSION}:{case_id}"
        if source_revision_id != expected_revision_id:
            raise EvaluationInputError(
                f"case {case_id} source_revision_id must equal {expected_revision_id}"
            )
        if source_revision_id in seen_source_revisions:
            raise EvaluationInputError(
                f"duplicate source_revision_id: {source_revision_id}"
            )
        seen_source_revisions.add(source_revision_id)
        split = str(case["split"])
        if split not in VALID_SPLITS:
            raise EvaluationInputError(f"case {case_id} has invalid split: {split}")
        splits.add(split)
        segments = case["segments"]
        if not isinstance(segments, list) or not segments:
            raise EvaluationInputError(f"case {case_id} requires source segments")
        segment_ids: set[str] = set()
        for segment in segments:
            segment_id = str(segment.get("segment_id", ""))
            text = str(segment.get("text", ""))
            if not segment_id or not text or segment_id in segment_ids:
                raise EvaluationInputError(f"case {case_id} has invalid segments")
            segment_ids.add(segment_id)
        claims = case["gold_claims"]
        if not isinstance(claims, list):
            raise EvaluationInputError(f"case {case_id} gold_claims must be a list")
        if not isinstance(case["allow_no_claims"], bool):
            raise EvaluationInputError(
                f"case {case_id} allow_no_claims must be boolean"
            )
        if _gold_run_status(case) == "invalid":
            raise EvaluationInputError(
                f"case {case_id} has no gold claims but allow_no_claims is false"
            )
        signatures: set[tuple[Any, ...]] = set()
        for claim in claims:
            _validate_gold_claim(claim, case_id)
            signature = _claim_signature(claim, "attributes")
            if signature in signatures:
                raise EvaluationInputError(
                    f"case {case_id} has duplicate gold claim signature"
                )
            signatures.add(signature)
            if _gold_evidence_segment(case, claim) is None:
                raise EvaluationInputError(
                    f"case {case_id} gold quote must resolve to exactly one segment"
                )
    if splits != VALID_SPLITS:
        raise EvaluationInputError("dataset must contain train, dev, and blind splits")
    fingerprint = _split_fingerprint(cases)
    if fingerprint != FROZEN_SPLIT_SHA256:
        raise EvaluationInputError(
            "frozen split fingerprint mismatch; create a new dataset version instead"
        )
    return cases, fingerprint


def _load_predictions(
    path: Path,
    case_ids: set[str],
) -> dict[str, dict[str, Any]]:
    rows = _load_jsonl(path)
    predictions: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = str(row.get("case_id", ""))
        if not case_id or case_id not in case_ids:
            raise EvaluationInputError(f"prediction has unknown case ID: {case_id!r}")
        if case_id in predictions:
            raise EvaluationInputError(f"duplicate prediction case ID: {case_id}")
        if "prediction" not in row:
            raise EvaluationInputError(f"prediction row {case_id} has no prediction")
        prompt_examples = row.get("prompt_example_case_ids", [])
        if not isinstance(prompt_examples, list):
            raise EvaluationInputError(
                f"prediction row {case_id} prompt examples must be a list"
            )
        predictions[case_id] = row
    missing = sorted(case_ids - set(predictions))
    if missing:
        raise EvaluationInputError(f"missing predictions: {', '.join(missing)}")
    return predictions


def _leakage_metrics(
    cases: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    split_by_id = {str(case["id"]): str(case["split"]) for case in cases}
    violations: list[dict[str, str]] = []
    for case_id in sorted(predictions):
        examples = predictions[case_id].get("prompt_example_case_ids") or []
        for example_id_raw in examples:
            example_id = str(example_id_raw)
            if example_id not in split_by_id:
                violations.append(
                    {
                        "case_id": case_id,
                        "example_case_id": example_id,
                        "reason": "unknown_prompt_example",
                    }
                )
            elif example_id == case_id:
                violations.append(
                    {
                        "case_id": case_id,
                        "example_case_id": example_id,
                        "reason": "self_example_leakage",
                    }
                )
            elif split_by_id[example_id] != "train":
                violations.append(
                    {
                        "case_id": case_id,
                        "example_case_id": example_id,
                        "reason": f"{split_by_id[example_id]}_example_forbidden",
                    }
                )
    return {
        "prompt_example_policy": "train_only_no_self_reference",
        "leakage_violation_count": len(violations),
        "leakage_violations": violations,
        "leakage_gate_passed": not violations,
    }


def _assign_claims(
    gold_claims: Sequence[Mapping[str, Any]],
    predicted_claims: Sequence[Mapping[str, Any]],
) -> tuple[dict[int, int], dict[int, int], int, int]:
    """Greedily pair same-type/polarity claims by explicit attribute agreement."""

    assignments: dict[int, int] = {}
    exact_matches: dict[int, int] = {}
    used_predictions: set[int] = set()
    exact_correct = 0
    exact_total = 0
    for gold_index, gold in enumerate(gold_claims):
        expected = _flatten_attributes(gold.get("attributes") or {})
        exact_total += len(expected)
        best: tuple[int, int] | None = None
        for prediction_index, prediction in enumerate(predicted_claims):
            if prediction_index in used_predictions:
                continue
            if _claim_base_key(prediction) != _claim_base_key(gold):
                continue
            actual = _flatten_attributes(prediction.get("attributes") or {})
            correct = sum(
                1 for path, value in expected.items() if actual.get(path) == value
            )
            candidate = (correct, -prediction_index)
            if best is None or candidate > best:
                best = candidate
        if best is None:
            continue
        correct, negative_prediction_index = best
        prediction_index = -negative_prediction_index
        assignments[gold_index] = prediction_index
        used_predictions.add(prediction_index)
        exact_correct += correct
        if correct == len(expected):
            exact_matches[gold_index] = prediction_index
    return assignments, exact_matches, exact_correct, exact_total


def _number_tokens(value: Any) -> set[str]:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return {_normalize_text(match.group(0)) for match in NUMBER_PATTERN.finditer(text)}


def _prediction_factual_content(prediction: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "claims": [
            {
                "statement": claim.get("statement"),
                "attributes": claim.get("attributes"),
            }
            for claim in prediction.get("claims") or []
        ],
        "narrative": prediction.get("narrative"),
    }


def _duplicate_primary_theme_count(prediction: Mapping[str, Any]) -> int:
    seen: set[str] = set()
    duplicate_count = 0
    for theme in prediction.get("themes") or []:
        if not isinstance(theme, Mapping):
            continue
        for claim_ref in theme.get("claim_refs") or []:
            normalized = str(claim_ref)
            if normalized in seen:
                duplicate_count += 1
            else:
                seen.add(normalized)
    return duplicate_count


def _legacy_slot_artifact_count(prediction: Any) -> int:
    """Count fixed-template business slots outside deliberately open attributes."""

    if not isinstance(prediction, Mapping):
        return 0
    return sum(1 for key in prediction if str(key) in LEGACY_SLOT_KEYS)


def _evidence_metrics(
    prediction: Mapping[str, Any],
    case: Mapping[str, Any],
) -> dict[str, Any]:
    segment_text = {
        str(segment["segment_id"]): str(segment["text"]) for segment in case["segments"]
    }
    transcript = str(case["transcript"])
    evidence = prediction.get("evidence") or []
    resolved = 0
    quote_hash_matches = 0
    source_hash_matches = 0
    offset_matches = 0
    offset_checks = 0
    for span in evidence:
        if not isinstance(span, Mapping):
            continue
        segment_id = str(span.get("segment_id", ""))
        quote = str(span.get("quote_exact", ""))
        source = segment_text.get(segment_id)
        if source is not None and quote and quote in source:
            resolved += 1
        if quote and span.get("quote_sha256") == sha256_utf8(quote):
            quote_hash_matches += 1
        if source is not None and span.get("source_sha256") == sha256_utf8(source):
            source_hash_matches += 1
        start = span.get("raw_char_start")
        end = span.get("raw_char_end")
        if isinstance(start, int) and isinstance(end, int):
            offset_checks += 1
            if 0 <= start < end <= len(transcript) and transcript[start:end] == quote:
                offset_matches += 1
    total = len(evidence)
    evidence_gate = (
        total == 0 and _gold_run_status(case) == "no_extractable_claims"
    ) or (
        total > 0
        and resolved == total
        and quote_hash_matches == total
        and source_hash_matches == total
        and offset_matches == offset_checks
    )
    return {
        "evidence_span_count": total,
        "evidence_quote_resolved_count": resolved,
        "evidence_quote_hash_match_count": quote_hash_matches,
        "evidence_source_hash_match_count": source_hash_matches,
        "evidence_offset_match_count": offset_matches,
        "evidence_offset_check_count": offset_checks,
        "evidence_gate_passed": evidence_gate,
    }


def _provenance_metrics(
    prediction: Mapping[str, Any], case: Mapping[str, Any]
) -> dict[str, Any]:
    provenance = prediction.get("provenance") or {}
    transcript = str(case["transcript"])
    source_revision_matches = (
        provenance.get("source_revision_id") == case["source_revision_id"]
    )
    raw_hash_matches = provenance.get("raw_transcript_sha256") == sha256_utf8(
        transcript
    )
    normalized_hash_matches = provenance.get(
        "normalized_transcript_sha256"
    ) == sha256_utf8(_normalize_text(transcript))
    segment_count_matches = provenance.get("segment_count") == len(case["segments"])
    return {
        "source_revision_id_matches": source_revision_matches,
        "raw_transcript_sha256_matches": raw_hash_matches,
        "normalized_transcript_sha256_matches": normalized_hash_matches,
        "segment_count_matches": segment_count_matches,
        "provenance_gate_passed": (
            source_revision_matches
            and raw_hash_matches
            and normalized_hash_matches
            and segment_count_matches
        ),
    }


def _gold_evidence_alignment(
    gold_claims: Sequence[Mapping[str, Any]],
    predicted_claims: Sequence[Mapping[str, Any]],
    exact_matches: Mapping[int, int],
    prediction: Mapping[str, Any],
) -> tuple[int, int]:
    evidence_by_id = {
        str(span.get("evidence_id")): span
        for span in prediction.get("evidence") or []
        if isinstance(span, Mapping)
    }
    aligned = 0
    total = 0
    for gold_index, prediction_index in exact_matches.items():
        gold = gold_claims[gold_index]
        predicted = predicted_claims[prediction_index]
        predicted_spans = [
            evidence_by_id[reference]
            for reference in predicted.get("evidence_refs") or []
            if reference in evidence_by_id
        ]
        total += 1
        if any(
            str(span.get("quote_exact")) == str(gold.get("evidence_quote"))
            for span in predicted_spans
        ):
            aligned += 1
    return aligned, total


def _score_case(
    case: Mapping[str, Any],
    prediction_row: Mapping[str, Any],
) -> dict[str, Any]:
    raw_prediction = prediction_row["prediction"]
    schema_valid = False
    schema_error: str | None = None
    try:
        validated = validate_adaptive_contract(raw_prediction)
        prediction = validated.model_dump(mode="json", exclude_none=True)
        schema_valid = True
    except Exception as exc:  # Pydantic exposes multiple validation exception types.
        prediction = raw_prediction if isinstance(raw_prediction, dict) else {}
        schema_error = type(exc).__name__

    gold_claims = list(case.get("gold_claims") or [])
    predicted_claims = [
        claim for claim in prediction.get("claims") or [] if isinstance(claim, Mapping)
    ]
    _, exact_matches, exact_correct, exact_total = _assign_claims(
        gold_claims, predicted_claims
    )
    matched_gold = set(exact_matches)
    matched_predictions = set(exact_matches.values())
    weighted_total = sum(
        SALIENCE_WEIGHTS[str(claim["salience"])] for claim in gold_claims
    )
    weighted_matched = sum(
        SALIENCE_WEIGHTS[str(gold_claims[index]["salience"])] for index in matched_gold
    )
    critical_gold = {
        index
        for index, claim in enumerate(gold_claims)
        if claim["salience"] == "critical"
    }
    critical_base_keys = {
        _claim_base_key(gold_claims[index]) for index in critical_gold
    }
    critical_prediction_candidates = {
        index
        for index, claim in enumerate(predicted_claims)
        if _claim_base_key(claim) in critical_base_keys
    }
    matched_critical_gold = critical_gold & matched_gold
    matched_critical_predictions = {
        prediction_index
        for gold_index, prediction_index in exact_matches.items()
        if gold_index in critical_gold
    }
    unsupported_prediction_indexes = (
        set(range(len(predicted_claims))) - matched_predictions
    )

    allowed_numbers = _number_tokens(case["transcript"])
    allowed_numbers |= _number_tokens(
        [claim.get("attributes") or {} for claim in gold_claims]
    )
    predicted_numbers = _number_tokens(_prediction_factual_content(prediction))
    hallucinated_numbers = sorted(predicted_numbers - allowed_numbers)
    unsupported_high_risk = sum(
        1
        for index in unsupported_prediction_indexes
        if predicted_claims[index].get("risk_tier") == "high_risk"
    )
    severe_hallucinations = len(hallucinated_numbers) + unsupported_high_risk
    severe_unsupported_indexes = {
        index
        for index in unsupported_prediction_indexes
        if predicted_claims[index].get("risk_tier") == "high_risk"
        or bool(_number_tokens(predicted_claims[index]) - allowed_numbers)
    }
    critical_unsupported_indexes = {
        index
        for index in unsupported_prediction_indexes - severe_unsupported_indexes
        if _claim_base_key(predicted_claims[index]) in critical_base_keys
    }
    important_unsupported_indexes = (
        unsupported_prediction_indexes
        - severe_unsupported_indexes
        - critical_unsupported_indexes
    )

    evidence = _evidence_metrics(prediction, case)
    provenance = _provenance_metrics(prediction, case)
    aligned_evidence, gold_evidence_total = _gold_evidence_alignment(
        gold_claims,
        predicted_claims,
        exact_matches,
        prediction,
    )
    empty = _empty_optional_metrics(raw_prediction)
    duplicate_primary_theme = _duplicate_primary_theme_count(prediction)
    legacy_slot_artifacts = _legacy_slot_artifact_count(raw_prediction)

    gold_run_status = _gold_run_status(case)
    predicted_run_status = str(prediction.get("run_status", ""))
    no_extractable_valid = gold_run_status != "no_extractable_claims" or (
        predicted_run_status == "no_extractable_claims"
        and prediction.get("claims") == []
        and all(
            key not in prediction
            for key in (
                "evidence",
                "concepts",
                "relationships",
                "themes",
                "narrative",
            )
        )
    )
    run_status_matches = gold_run_status == predicted_run_status

    metrics: dict[str, Any] = {
        "schema_valid": schema_valid,
        "schema_error_type": schema_error,
        "gold_claim_count": len(gold_claims),
        "predicted_claim_count": len(predicted_claims),
        "matched_claim_count": len(matched_gold),
        "claim_precision": (
            round(len(matched_predictions) / len(predicted_claims), 6)
            if predicted_claims
            else 1.0
        ),
        "claim_recall": (
            round(len(matched_gold) / len(gold_claims), 6) if gold_claims else 1.0
        ),
        "weighted_salience_matched": weighted_matched,
        "weighted_salience_total": weighted_total,
        "weighted_salience_coverage": (
            round(weighted_matched / weighted_total, 6) if weighted_total else 1.0
        ),
        "critical_claim_matched": len(matched_critical_gold),
        "critical_claim_total": len(critical_gold),
        "critical_prediction_candidate_count": len(critical_prediction_candidates),
        "critical_precision": (
            round(
                len(matched_critical_predictions) / len(critical_prediction_candidates),
                6,
            )
            if critical_prediction_candidates
            else 1.0
        ),
        "critical_recall": (
            round(len(matched_critical_gold) / len(critical_gold), 6)
            if critical_gold
            else 1.0
        ),
        "exact_value_correct_count": exact_correct,
        "exact_value_total": exact_total,
        "exact_value_accuracy": (
            round(exact_correct / exact_total, 6) if exact_total else 1.0
        ),
        "unsupported_claim_count": len(unsupported_prediction_indexes),
        "unsupported_high_risk_claim_count": unsupported_high_risk,
        "unsupported_claim_severity_counts": {
            "severe": len(severe_unsupported_indexes),
            "critical": len(critical_unsupported_indexes),
            "important": len(important_unsupported_indexes),
        },
        "hallucinated_number_count": len(hallucinated_numbers),
        "hallucinated_number_severity_counts": {"severe": len(hallucinated_numbers)},
        "severe_hallucination_count": severe_hallucinations,
        "gold_evidence_aligned_count": aligned_evidence,
        "gold_evidence_total": gold_evidence_total,
        "gold_evidence_alignment_rate": (
            round(aligned_evidence / gold_evidence_total, 6)
            if gold_evidence_total
            else 1.0
        ),
        "duplicate_primary_theme_assignment_count": duplicate_primary_theme,
        "legacy_slot_artifact_count": legacy_slot_artifacts,
        "run_status_matches": run_status_matches,
        "no_extractable_state_valid": no_extractable_valid,
        **empty,
        **evidence,
        **provenance,
    }
    metrics["adaptive_discovery_gate_passed"] = (
        metrics["claim_recall"] == 1.0
        and metrics["critical_recall"] == 1.0
        and metrics["exact_value_accuracy"] == 1.0
        and metrics["empty_optional_emission_count"] == 0
        and metrics["legacy_slot_artifact_count"] == 0
    )
    passed = (
        schema_valid
        and run_status_matches
        and no_extractable_valid
        and metrics["weighted_salience_coverage"] == 1.0
        and metrics["critical_precision"] == 1.0
        and metrics["critical_recall"] == 1.0
        and metrics["exact_value_accuracy"] == 1.0
        and metrics["unsupported_claim_count"] == 0
        and metrics["severe_hallucination_count"] == 0
        and metrics["empty_optional_emission_count"] == 0
        and metrics["duplicate_primary_theme_assignment_count"] == 0
        and metrics["adaptive_discovery_gate_passed"]
        and metrics["evidence_gate_passed"]
        and metrics["provenance_gate_passed"]
        and metrics["gold_evidence_alignment_rate"] == 1.0
    )
    return {
        "case_id": case["id"],
        "split": case["split"],
        "passed": passed,
        "metrics": metrics,
    }


def score_case(
    case: Mapping[str, Any], prediction: Mapping[str, Any]
) -> dict[str, Any]:
    """Score one raw canonical prediction against one gold fixture case."""

    return _score_case(case, {"prediction": prediction})


def _sum(case_results: Sequence[Mapping[str, Any]], key: str) -> int:
    return sum(int(result["metrics"][key]) for result in case_results)


def _aggregate(case_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    evaluated = len(case_results)
    passed = sum(1 for result in case_results if result["passed"])
    weighted_matched = _sum(case_results, "weighted_salience_matched")
    weighted_total = _sum(case_results, "weighted_salience_total")
    critical_matched = _sum(case_results, "critical_claim_matched")
    critical_total = _sum(case_results, "critical_claim_total")
    critical_predictions = _sum(case_results, "critical_prediction_candidate_count")
    exact_correct = _sum(case_results, "exact_value_correct_count")
    exact_total = _sum(case_results, "exact_value_total")
    optional_invalid = _sum(case_results, "empty_optional_emission_count")
    optional_total = _sum(case_results, "optional_emission_denominator")
    return {
        "evaluated": evaluated,
        "passed": passed,
        "failed": evaluated - passed,
        "schema_valid_rate": (
            round(
                sum(1 for result in case_results if result["metrics"]["schema_valid"])
                / evaluated,
                6,
            )
            if evaluated
            else 0.0
        ),
        "weighted_salience_coverage": (
            round(weighted_matched / weighted_total, 6) if weighted_total else 1.0
        ),
        "critical_precision": (
            round(critical_matched / critical_predictions, 6)
            if critical_predictions
            else 1.0
        ),
        "critical_recall": (
            round(critical_matched / critical_total, 6) if critical_total else 1.0
        ),
        "exact_value_accuracy": (
            round(exact_correct / exact_total, 6) if exact_total else 1.0
        ),
        "unsupported_claim_count": _sum(case_results, "unsupported_claim_count"),
        "unsupported_claim_severity_counts": {
            severity: sum(
                int(result["metrics"]["unsupported_claim_severity_counts"][severity])
                for result in case_results
            )
            for severity in ("severe", "critical", "important")
        },
        "hallucinated_number_count": _sum(case_results, "hallucinated_number_count"),
        "hallucinated_number_severity_counts": {
            "severe": _sum(case_results, "hallucinated_number_count")
        },
        "severe_hallucination_count": _sum(case_results, "severe_hallucination_count"),
        "empty_optional_emission_count": optional_invalid,
        "optional_emission_denominator": optional_total,
        "empty_optional_emission_rate": (
            round(optional_invalid / optional_total, 6) if optional_total else 0.0
        ),
        "duplicate_primary_theme_assignment_count": _sum(
            case_results, "duplicate_primary_theme_assignment_count"
        ),
        "legacy_slot_artifact_count": _sum(case_results, "legacy_slot_artifact_count"),
        "adaptive_discovery_pass_rate": (
            round(
                sum(
                    1
                    for result in case_results
                    if result["metrics"]["adaptive_discovery_gate_passed"]
                )
                / evaluated,
                6,
            )
            if evaluated
            else 0.0
        ),
        "evidence_gate_pass_rate": (
            round(
                sum(
                    1
                    for result in case_results
                    if result["metrics"]["evidence_gate_passed"]
                )
                / evaluated,
                6,
            )
            if evaluated
            else 0.0
        ),
        "provenance_gate_pass_rate": (
            round(
                sum(
                    1
                    for result in case_results
                    if result["metrics"]["provenance_gate_passed"]
                )
                / evaluated,
                6,
            )
            if evaluated
            else 0.0
        ),
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_repo_path(path: Path) -> str | None:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return None


def _git_metadata(relevant_paths: Iterable[Path]) -> dict[str, Any]:
    def run(*args: str) -> str | None:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=PROJECT_ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return completed.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None

    revision = run("rev-parse", "HEAD")
    status_text = run("status", "--porcelain=v1", "--untracked-files=all")
    status_lines = sorted(status_text.splitlines()) if status_text else []
    relevant = {
        relative
        for path in relevant_paths
        if (relative := _relative_repo_path(path)) is not None
    }
    relevant_status = []
    for line in status_lines:
        path_text = line[3:].replace("\\", "/") if len(line) > 3 else ""
        if path_text in relevant:
            relevant_status.append(line)
    return {
        "revision": revision,
        "tracked_dirty": any(not line.startswith("??") for line in status_lines),
        "untracked": any(line.startswith("??") for line in status_lines),
        "relevant_status": relevant_status,
        "relevant_untracked": any(line.startswith("??") for line in relevant_status),
    }


def evaluate(
    cases: Sequence[Mapping[str, Any]],
    prediction_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate in-memory cases/predictions without filesystem or model access."""

    if {str(case.get("split", "")) for case in cases} != VALID_SPLITS:
        raise EvaluationInputError("dataset must contain train, dev, and blind splits")
    if _split_fingerprint(cases) != FROZEN_SPLIT_SHA256:
        raise EvaluationInputError(
            "frozen split fingerprint mismatch; create a new dataset version instead"
        )
    case_ids = {str(case["id"]) for case in cases}
    predictions: dict[str, Mapping[str, Any]] = {}
    for row in prediction_rows:
        case_id = str(row.get("case_id", ""))
        if case_id not in case_ids or case_id in predictions:
            raise EvaluationInputError(
                f"invalid or duplicate prediction case ID: {case_id}"
            )
        predictions[case_id] = row
    missing = sorted(case_ids - set(predictions))
    if missing:
        raise EvaluationInputError(f"missing predictions: {', '.join(missing)}")
    leakage = _leakage_metrics(cases, predictions)
    case_results = [
        _score_case(case, predictions[str(case["id"])])
        for case in sorted(cases, key=lambda item: str(item["id"]))
    ]
    aggregate = _aggregate(case_results)
    overall_passed = aggregate["failed"] == 0 and leakage["leakage_gate_passed"]
    return {
        "case_results": case_results,
        "aggregate": aggregate,
        "leakage": leakage,
        "gate": {
            "passed": overall_passed,
            "status": "PILOT_PASS" if overall_passed else "PILOT_HAS_FAILURES",
        },
    }


def evaluate_files(fixtures_path: Path, predictions_path: Path) -> dict[str, Any]:
    fixtures_path = fixtures_path.resolve()
    predictions_path = predictions_path.resolve()
    cases, split_fingerprint = _load_dataset(fixtures_path)
    case_ids = {str(case["id"]) for case in cases}
    predictions = _load_predictions(predictions_path, case_ids)
    evaluation = evaluate(cases, list(predictions.values()))
    leakage = evaluation["leakage"]
    case_results = evaluation["case_results"]
    aggregate = evaluation["aggregate"]
    scorer_path = Path(__file__).resolve()
    contract_path = PROJECT_ROOT / "src/services/investigation/contracts.py"
    evaluation_payload = {
        "cases": case_results,
        "aggregate": aggregate,
        "leakage": leakage,
    }
    overall_passed = evaluation["gate"]["passed"]
    report: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "quality_claim": "SYNTHETIC_OFFLINE_SCORER_PILOT_NOT_HUMAN_QUALITY_EVIDENCE",
        "dataset": {
            "version": DATASET_VERSION,
            "case_count": len(cases),
            "split_counts": {
                split: sum(1 for case in cases if case["split"] == split)
                for split in sorted(VALID_SPLITS)
            },
            "frozen_split_sha256": split_fingerprint,
        },
        "metric_contract": {
            "salience_weights": SALIENCE_WEIGHTS,
            "claim_match": (
                "open claim_type + polarity + explicit normalized gold attributes; "
                "claim/model IDs are ignored"
            ),
            "adaptive_discovery": (
                "all discovered gold claims and salient exact values must be covered; "
                "fixed legacy top-level slots and absent placeholders are forbidden"
            ),
            "empty_optional_denominator": (
                "optional properties plus collection rows explicitly emitted; "
                "0.0 when denominator is zero"
            ),
        },
        "case_results": case_results,
        "aggregate": aggregate,
        "leakage": leakage,
        "gate": {
            "passed": overall_passed,
            "status": "PILOT_PASS" if overall_passed else "PILOT_HAS_FAILURES",
        },
        "integrity": {
            "input_sha256": {
                "fixtures": _sha256_file(fixtures_path),
                "predictions": _sha256_file(predictions_path),
            },
            "source_sha256": {
                _relative_repo_path(scorer_path)
                or str(scorer_path): _sha256_file(scorer_path),
                _relative_repo_path(contract_path)
                or str(contract_path): _sha256_file(contract_path),
            },
            "evaluation_payload_sha256": sha256_canonical_json(evaluation_payload),
            "git": _git_metadata(
                [scorer_path, contract_path, fixtures_path, predictions_path]
            ),
        },
    }
    report["integrity"]["report_payload_sha256"] = sha256_canonical_json(report)
    return report


def deterministic_report_json(report: Mapping[str, Any]) -> str:
    return (
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path("tests/eval/adaptive_contract_cases.jsonl"),
    )
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report = evaluate_files(args.fixtures, args.predictions)
    except EvaluationInputError as exc:
        print(f"evaluation input error: {exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(deterministic_report_json(report), encoding="utf-8")
    print(
        f"{report['gate']['status']} | {report['aggregate']['passed']}/"
        f"{report['aggregate']['evaluated']} cases | {args.output}"
    )
    return 0 if report["gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
