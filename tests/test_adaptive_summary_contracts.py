import hashlib
import json
import subprocess
import sys

import pytest
from pydantic import ValidationError

from src.services.investigation.contracts import (
    ADAPTIVE_CONTRACT_VERSION,
    ADAPTIVE_DISCOVERY_PROMPT_VERSION,
    AdaptiveAnalysisContract,
    AdaptiveSummaryAnalysisContract,
    AdaptiveSummaryContract,
    adaptive_contract_json_schema,
    adaptive_contract_schema_sha256,
    build_run_manifest,
    canonical_json,
    hash_source_modules,
    sanitize_sparse_payload,
    sha256_canonical_json,
    sha256_utf8,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _manifest(prompt: str = "Khám phá dữ kiện có bằng chứng.") -> dict:
    return build_run_manifest(
        prompt=prompt,
        prompt_version=ADAPTIVE_DISCOVERY_PROMPT_VERSION,
        model_id="fixture-model:1",
        model_digest="digest-001",
        provider="ollama",
        decoding_config={"temperature": 0, "seed": 0},
        source_module_hashes=hash_source_modules(
            {"adaptive_contracts.py": "source text"}
        ),
        git_revision="abc123",
        git_dirty=True,
        git_untracked=True,
    ).model_dump(mode="json", exclude_none=True)


def _base_payload() -> dict:
    quote = "Người nói phủ nhận việc đã chuyển khoản."
    source = "Một đoạn nguồn có bằng chứng."
    return {
        "schema_version": ADAPTIVE_CONTRACT_VERSION,
        "run_status": "success",
        "claims": [
            {
                "claim_id": "clm-1",
                "claim_type": "unseen.financial.negated_transfer",
                "statement": "Người nói phủ nhận việc đã chuyển khoản.",
                "polarity": "negated",
                "disposition": "supported",
                "evidence_refs": ["ev-1"],
                "concept_refs": ["con-1"],
                "attributes": {
                    "previously_unseen_attribute": {
                        "normalized": 0,
                        "explicit_negation": False,
                        "verification_state": "supported",
                    }
                },
            }
        ],
        "evidence": [
            {
                "evidence_id": "ev-1",
                "segment_id": "seg-1",
                "quote_exact": quote,
                "raw_char_start": 0,
                "raw_char_end": len(quote),
                "start_seconds": 0.0,
                "end_seconds": 2.5,
                "quote_sha256": _hash(quote),
                "source_sha256": _hash(source),
            }
        ],
        "concepts": [
            {
                "concept_id": "con-1",
                "concept_type": "unseen.object.custom_identifier",
                "surface": "một surface form",
                "evidence_refs": ["ev-1"],
                "attributes": {"arbitrary_nested": {"count": 0, "active": False}},
            }
        ],
        "relationships": [
            {
                "relationship_id": "rel-1",
                "relationship_type": "unseen.relation.denies",
                "source_ref": "con-1",
                "target_ref": "clm-1",
                "evidence_refs": ["ev-1"],
            }
        ],
        "themes": [
            {
                "theme_id": "thm-1",
                "title": "Chủ đề được khám phá",
                "claim_refs": ["clm-1"],
            }
        ],
        "narrative": {
            "overview": [
                {
                    "text": "Nguồn ghi nhận một lời phủ nhận.",
                    "sentence_kind": "factual",
                    "claim_refs": ["clm-1"],
                }
            ],
            "thematic_groups": [
                {
                    "theme_ref": "thm-1",
                    "sentences": [
                        {
                            "text": "Chi tiết được giữ trong một primary theme.",
                            "claim_refs": ["clm-1"],
                        }
                    ],
                }
            ],
        },
        "provenance": {
            "source_revision_id": "src-1",
            "raw_transcript_sha256": _hash(source),
            "normalized_transcript_sha256": _hash(source.casefold()),
            "segment_count": 1,
        },
        "safety": {
            "transcript_is_untrusted_data": True,
            "evidence_required_for_released_claims": True,
            "high_risk_requires_human_verification": True,
            "unsupported_high_risk_claims_released": False,
        },
        "manifest": _manifest(),
    }


def _no_claims_payload() -> dict:
    source = "Nguồn không chứa claim factual có thể trích xuất."
    return {
        "schema_version": ADAPTIVE_CONTRACT_VERSION,
        "run_status": "no_extractable_claims",
        "claims": [],
        "provenance": {
            "source_revision_id": "src-empty",
            "raw_transcript_sha256": _hash(source),
            "normalized_transcript_sha256": _hash(source.casefold()),
            "segment_count": 1,
        },
        "safety": {
            "transcript_is_untrusted_data": True,
            "evidence_required_for_released_claims": True,
            "high_risk_requires_human_verification": True,
            "unsupported_high_risk_claims_released": False,
        },
        "manifest": _manifest(),
    }


def test_summary_and_analysis_share_one_open_canonical_contract():
    assert AdaptiveSummaryContract is AdaptiveSummaryAnalysisContract
    assert AdaptiveAnalysisContract is AdaptiveSummaryAnalysisContract

    result = AdaptiveSummaryContract.model_validate(_base_payload())

    assert result.claims[0].claim_type == "unseen.financial.negated_transfer"
    assert result.concepts[0].concept_type == "unseen.object.custom_identifier"
    assert result.claims[0].attributes["previously_unseen_attribute"]["normalized"] == 0
    assert result.claims[0].polarity == "negated"
    assert result.claims[0].disposition == "supported"


def test_recursive_sanitizer_removes_nested_sparse_fillers_but_keeps_falsy_state():
    dirty = {
        "drop_none": None,
        "drop_blank": "   ",
        "drop_empty_list": [],
        "drop_empty_dict": {},
        "nested": {
            "drop_filler_case": "KHÔNG CÓ THÔNG TIN",
            "drop_filler_unicode": "Ｃần xác minh thêm",
            "keep_zero": 0,
            "keep_false": False,
            "keep_negation": "negated",
            "keep_verification": "supported",
        },
    }

    assert sanitize_sparse_payload(dirty) == {
        "nested": {
            "keep_zero": 0,
            "keep_false": False,
            "keep_negation": "negated",
            "keep_verification": "supported",
        }
    }


@pytest.mark.parametrize(
    "invalid_value",
    [
        None,
        "",
        "   ",
        [],
        {},
        "Không có thông tin",
        "CẦN XÁC MINH THÊM",
        "Ｃần xác minh thêm",
    ],
)
def test_validation_boundary_rejects_optional_sparse_values(invalid_value):
    payload = _base_payload()
    payload["claims"][0]["attributes"] = {"dirty_optional": invalid_value}

    with pytest.raises(ValidationError, match="filler values are forbidden"):
        AdaptiveSummaryAnalysisContract.model_validate(payload)


@pytest.mark.parametrize("invalid_value", [object(), float("nan"), float("inf")])
def test_open_attributes_are_still_strict_json_values(invalid_value):
    payload = _base_payload()
    payload["claims"][0]["attributes"] = {"not_json": invalid_value}

    with pytest.raises(ValidationError):
        AdaptiveSummaryAnalysisContract.model_validate(payload)


def test_required_field_removed_by_sanitizer_fails_closed():
    payload = _base_payload()
    payload["claims"][0]["statement"] = "Không có thông tin"
    cleaned = sanitize_sparse_payload(payload)

    assert "statement" not in cleaned["claims"][0]
    with pytest.raises(ValidationError):
        AdaptiveSummaryAnalysisContract.model_validate(cleaned)


def test_strict_envelopes_reject_extra_fields():
    payload = _base_payload()
    payload["provenance"]["unexpected"] = "not allowed"

    with pytest.raises(ValidationError, match="extra_forbidden"):
        AdaptiveSummaryAnalysisContract.model_validate(payload)


def test_no_extractable_claims_is_the_only_valid_empty_claim_state():
    result = AdaptiveSummaryAnalysisContract.model_validate(_no_claims_payload())
    assert result.run_status == "no_extractable_claims"
    assert result.claims == []
    assert result.evidence is None
    assert result.themes is None
    assert result.narrative is None

    success = _no_claims_payload()
    success["run_status"] = "success"
    with pytest.raises(ValidationError):
        AdaptiveSummaryAnalysisContract.model_validate(success)


def test_sparse_dump_preserves_the_required_no_claims_sentinel():
    result = AdaptiveSummaryAnalysisContract.model_validate(_no_claims_payload())

    sparse_dump = result.model_dump_sparse()

    assert sparse_dump["claims"] == []
    assert "evidence" not in sparse_dump
    assert AdaptiveSummaryAnalysisContract.model_validate(sparse_dump) == result


@pytest.mark.parametrize("field", ["evidence", "themes", "narrative"])
def test_no_extractable_claims_rejects_evidence_themes_or_narrative(field):
    payload = _no_claims_payload()
    populated = _base_payload()[field]
    payload[field] = populated

    with pytest.raises(ValidationError, match="no_extractable_claims cannot include"):
        AdaptiveSummaryAnalysisContract.model_validate(payload)


def test_duplicate_ids_fail_closed_across_the_canonical_graph():
    payload = _base_payload()
    duplicate = dict(payload["claims"][0])
    duplicate["statement"] = "Một claim thứ hai dùng lại ID."
    payload["claims"].append(duplicate)

    with pytest.raises(ValidationError, match="duplicate ID"):
        AdaptiveSummaryAnalysisContract.model_validate(payload)


def test_dangling_relationship_node_reference_fails_closed():
    payload = _base_payload()
    payload["relationships"][0]["target_ref"] = "missing-node"

    with pytest.raises(ValidationError, match="dangling relationship node refs"):
        AdaptiveSummaryAnalysisContract.model_validate(payload)


def test_fake_claim_evidence_reference_fails_closed():
    payload = _base_payload()
    payload["claims"][0]["evidence_refs"] = ["ev-fake"]

    with pytest.raises(ValidationError, match="dangling claim evidence_refs"):
        AdaptiveSummaryAnalysisContract.model_validate(payload)


def test_invalid_disposition_is_rejected_by_the_contract():
    payload = _base_payload()
    payload["claims"][0]["disposition"] = "probably_supported"

    with pytest.raises(ValidationError):
        AdaptiveSummaryAnalysisContract.model_validate(payload)


def test_unsupported_high_risk_fact_is_rejected():
    payload = _base_payload()
    claim = payload["claims"][0]
    claim.update(
        risk_tier="high_risk",
        epistemic_status="fact",
        requires_human_verification=False,
        disposition="unverifiable",
    )

    with pytest.raises(
        ValidationError, match="high-risk claims must be represented as hypotheses"
    ):
        AdaptiveSummaryAnalysisContract.model_validate(payload)


def test_supported_high_risk_hypothesis_cannot_be_factual_narrative():
    payload = _base_payload()
    claim = payload["claims"][0]
    claim.update(
        risk_tier="high_risk",
        epistemic_status="hypothesis",
        requires_human_verification=True,
        disposition="supported",
    )

    with pytest.raises(
        ValidationError, match="cannot be released as factual narrative"
    ):
        AdaptiveSummaryAnalysisContract.model_validate(payload)

    payload["narrative"]["overview"][0]["sentence_kind"] = "uncertainty"
    payload["narrative"]["thematic_groups"][0]["sentences"][0][
        "sentence_kind"
    ] = "uncertainty"
    result = AdaptiveSummaryAnalysisContract.model_validate(payload)
    assert result.claims[0].requires_human_verification is True


def test_exact_utf8_prompt_hash_is_deterministic_and_not_normalized():
    prompt = "Trích xuất đúng bằng chứng tiếng Việt: đ, 0, False."
    assert sha256_utf8(prompt) == hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assert sha256_utf8(prompt) == sha256_utf8(prompt)
    assert sha256_utf8("é") != sha256_utf8("e\u0301")
    assert sha256_utf8(prompt) != sha256_utf8(prompt + " ")


def test_canonical_schema_hash_is_stable_across_processes_and_changes_on_tamper():
    local_hash = adaptive_contract_schema_sha256()
    command = (
        "from src.services.investigation.contracts import "
        "adaptive_contract_schema_sha256; print(adaptive_contract_schema_sha256())"
    )
    process_hash = subprocess.check_output(
        [sys.executable, "-c", command],
        text=True,
    ).strip()

    assert process_hash == local_hash
    tampered = adaptive_contract_json_schema()
    tampered["title"] = "tampered"
    assert sha256_canonical_json(tampered) != local_hash


def test_manifest_records_model_config_versions_source_hashes_and_git_state():
    prompt = "Prompt chính xác UTF-8."
    source_hashes = hash_source_modules({"b.py": b"bytes", "a.py": "nội dung"})
    manifest = build_run_manifest(
        prompt=prompt,
        prompt_version="prompt-v9",
        model_id="qwen-local:14b",
        model_digest="immutable-digest",
        provider="ollama",
        decoding_config={"temperature": 0, "num_ctx": 32768},
        source_module_hashes=source_hashes,
        git_revision="deadbeef",
        git_dirty=True,
        git_untracked=True,
    )

    assert manifest.contract_version == ADAPTIVE_CONTRACT_VERSION
    assert manifest.prompt_sha256 == sha256_utf8(prompt)
    assert manifest.json_schema_sha256 == adaptive_contract_schema_sha256()
    assert manifest.model_id == "qwen-local:14b"
    assert manifest.decoding_config["temperature"] == 0
    assert manifest.source_module_hashes == source_hashes
    assert manifest.git_dirty is True
    assert manifest.git_untracked is True
    assert list(source_hashes) == ["a.py", "b.py"]

    changed = build_run_manifest(
        prompt=prompt + " changed",
        prompt_version="prompt-v9",
        model_id="qwen-local:14b",
        model_digest="immutable-digest",
        provider="ollama",
        decoding_config={"temperature": 0, "num_ctx": 32768},
        source_module_hashes=source_hashes,
        git_revision="deadbeef",
        git_dirty=True,
        git_untracked=True,
    )
    assert changed.prompt_sha256 != manifest.prompt_sha256


def test_json_schema_is_strict_but_keeps_open_types_and_attributes():
    schema = adaptive_contract_json_schema()
    definitions = schema["$defs"]

    assert schema["additionalProperties"] is False
    assert definitions["SourceProvenance"]["additionalProperties"] is False
    assert definitions["SafetyEnvelope"]["additionalProperties"] is False
    assert definitions["GroundedClaim"]["properties"]["claim_type"] == {
        "minLength": 1,
        "title": "Claim Type",
        "type": "string",
    }
    assert "enum" not in canonical_json(
        definitions["ConceptMention"]["properties"]["concept_type"]
    )
    attributes_schema = definitions["GroundedClaim"]["properties"]["attributes"]
    assert "additionalProperties" in json.dumps(attributes_schema)
