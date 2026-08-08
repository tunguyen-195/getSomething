import copy
import hashlib
import json
import subprocess
import sys

import pytest
from pydantic import ValidationError

from src.services.investigation.contracts import (
    ADAPTIVE_CONTRACT_VERSION,
    ADAPTIVE_DISCOVERY_PROMPT_VERSION,
    INVESTIGATION_RUN_VERSION,
    AdaptiveAnalysisContract,
    AdaptiveExtractionContract,
    AdaptiveSummaryAnalysisContract,
    AdaptiveSummaryContract,
    AnalysisProjection,
    EvidenceBackedInsight,
    GroundedClaim,
    GroundedRelationship,
    Hypothesis,
    InvestigationAnalysisProjection,
    InvestigationRun,
    InvestigationRunManifest,
    InvestigationSummaryProjection,
    ProjectionEligibility,
    RiskTier,
    RunManifest,
    SummaryProjection,
    VerificationAction,
    VerificationDecision,
    adaptive_contract_json_schema,
    adaptive_contract_schema_sha256,
    build_investigation_run_manifest,
    build_run_manifest,
    canonical_json,
    hash_source_modules,
    investigation_run_json_schema,
    investigation_run_schema_sha256,
    sanitize_sparse_payload,
    sha256_canonical_json,
    sha256_utf8,
    validate_investigation_run,
)
from src.services.investigation.run_contracts import (
    _TrustedEvidenceFingerprint,
    _TrustedEligibilityAssessment,
    _TrustedRiskAssessment,
    _TrustedSelectorAttestation,
    _build_trusted_investigation_validation_context,
    _semantic_subject_sha256,
    _verification_subject_sha256,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_FIXTURE_QUOTE = "Người nói phủ nhận việc đã chuyển khoản."
_FIXTURE_SOURCE = "Một đoạn nguồn có bằng chứng."


def _trusted_context(
    payload: dict,
    *,
    risk_overrides: dict[str, RiskTier] | None = None,
    reasoning_eligibility_overrides: dict[str, ProjectionEligibility] | None = None,
):
    ledger = payload.get("ledger") or {}
    evidence_fingerprints = {
        evidence["evidence_id"]: _TrustedEvidenceFingerprint(
            segment_id=evidence["segment_id"],
            quote_sha256=evidence["quote_sha256"],
            source_sha256=evidence["source_sha256"],
            quote_prefix=evidence.get("quote_prefix"),
            quote_suffix=evidence.get("quote_suffix"),
            raw_char_start=evidence.get("raw_char_start"),
            raw_char_end=evidence.get("raw_char_end"),
            start_seconds=evidence.get("start_seconds"),
            end_seconds=evidence.get("end_seconds"),
            speaker_id=evidence.get("speaker_id"),
        )
        for evidence in ledger.get("evidence", [])
    }
    selector_attestations = {}
    claim_models = {
        claim["claim_id"]: GroundedClaim.model_validate(claim)
        for claim in ledger.get("claims", [])
    }
    decision_models = {
        decision["verification_id"]: VerificationDecision.model_validate(decision)
        for decision in ledger.get("verification_decisions", [])
    }
    verification_eligibility: dict[str, _TrustedEligibilityAssessment] = {}
    for decision_id, decision_model in decision_models.items():
        claim_model = (
            claim_models.get(decision_model.canonical_claim_ref)
            if decision_model.canonical_claim_ref
            else None
        )
        verification_eligibility[decision_id] = _TrustedEligibilityAssessment(
            eligibility=decision_model.projection_eligibility,
            artifact_ref=(
                decision_model.eligibility_artifact_ref
                or f"eligibility-withheld-{decision_id}"
            ),
            subject_sha256=_verification_subject_sha256(
                decision_model,
                claim_model,
            ),
        )
        if decision_model.evidence_resolution != "resolved":
            continue
        refs = decision_model.verified_evidence_refs or []
        selector_attestations[decision_id] = _TrustedSelectorAttestation(
            artifact_ref=decision_model.resolution_artifact_ref,
            source_revision_id=payload["provenance"]["source_revision_id"],
            evidence={ref: evidence_fingerprints[ref] for ref in refs},
        )

    relationship_attestations = {}
    relationship_models = {
        relationship["relationship_id"]: GroundedRelationship.model_validate(
            relationship
        )
        for relationship in ledger.get("relationships", [])
    }
    relationship_eligibility: dict[str, _TrustedEligibilityAssessment] = {}
    for relationship_id, relationship_model in relationship_models.items():
        relationship_eligibility[relationship_id] = _TrustedEligibilityAssessment(
            eligibility=relationship_model.projection_eligibility,
            artifact_ref=(
                relationship_model.eligibility_artifact_ref
                or f"eligibility-withheld-{relationship_id}"
            ),
            subject_sha256=_semantic_subject_sha256(relationship_model),
        )
        if relationship_model.evidence_resolution != "resolved":
            continue
        refs = relationship_model.evidence_refs
        assert relationship_model.resolution_artifact_ref is not None
        relationship_attestations[relationship_id] = _TrustedSelectorAttestation(
            artifact_ref=relationship_model.resolution_artifact_ref,
            source_revision_id=payload["provenance"]["source_revision_id"],
            evidence={ref: evidence_fingerprints[ref] for ref in refs},
        )

    risk_overrides = risk_overrides or {}
    insight_models = {
        insight["insight_id"]: EvidenceBackedInsight.model_validate(insight)
        for insight in ledger.get("insights", [])
    }
    hypothesis_models = {
        hypothesis["hypothesis_id"]: Hypothesis.model_validate(hypothesis)
        for hypothesis in ledger.get("hypotheses", [])
    }
    action_models = {
        action["action_id"]: VerificationAction.model_validate(action)
        for action in ledger.get("verification_actions", [])
    }
    risk_subjects = {
        **claim_models,
        **relationship_models,
        **insight_models,
        **hypothesis_models,
    }
    risk_assessments: dict[str, _TrustedRiskAssessment] = {}
    for subject_ref, subject_model in risk_subjects.items():
        artifact_ref = getattr(subject_model, "risk_screening_artifact_ref")
        risk_assessments[subject_ref] = _TrustedRiskAssessment(
            risk_tier=risk_overrides.get(
                subject_ref,
                getattr(subject_model, "risk_tier") or "ordinary",
            ),
            artifact_ref=artifact_ref or f"risk-screening-{subject_ref}",
            subject_sha256=_semantic_subject_sha256(subject_model),
        )

    reasoning_eligibility_overrides = reasoning_eligibility_overrides or {}
    reasoning_models = {**insight_models, **hypothesis_models, **action_models}
    reasoning_eligibility: dict[str, _TrustedEligibilityAssessment] = {}
    for subject_ref, subject_model in reasoning_models.items():
        eligibility = reasoning_eligibility_overrides.get(
            subject_ref,
            subject_model.projection_eligibility,
        )
        reasoning_eligibility[subject_ref] = _TrustedEligibilityAssessment(
            eligibility=eligibility,
            artifact_ref=subject_model.eligibility_artifact_ref,
            subject_sha256=_semantic_subject_sha256(subject_model),
        )
    return _build_trusted_investigation_validation_context(
        selector_attestations=selector_attestations,
        relationship_attestations=relationship_attestations,
        risk_assessments=risk_assessments,
        verification_eligibility=verification_eligibility,
        relationship_eligibility=relationship_eligibility,
        reasoning_eligibility=reasoning_eligibility,
        manifest_sha256=_semantic_subject_sha256(
            InvestigationRunManifest.model_validate(payload["manifest"])
        ),
    )


def _validate_run(payload: dict, *, trusted_context=None) -> InvestigationRun:
    return validate_investigation_run(
        payload,
        trusted_context=trusted_context or _trusted_context(payload),
    )


def _manifest(
    prompt: str = "Khám phá dữ kiện có bằng chứng.",
) -> dict:
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
    quote = _FIXTURE_QUOTE
    source = _FIXTURE_SOURCE
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


def _investigation_run_manifest() -> dict:
    return build_investigation_run_manifest(
        prompt="Khám phá dữ kiện có bằng chứng.",
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


def _investigation_run_payload() -> dict:
    extraction = _base_payload()
    claim = copy.deepcopy(extraction["claims"][0])
    claim["candidate_refs"] = ["cand-1"]
    claim["risk_tier"] = "ordinary"
    claim["risk_screening_artifact_ref"] = "risk-screening-clm-1"
    relationship = copy.deepcopy(extraction["relationships"][0])
    relationship.update(
        evidence_resolution="resolved",
        source_revision_id="src-1",
        resolution_authority="t2-evidence-selector-v1",
        resolution_artifact_ref="selector-artifact-rel-1",
        risk_tier="ordinary",
        risk_screening_artifact_ref="risk-screening-rel-1",
        projection_eligibility="factual",
        eligibility_artifact_ref="eligibility-rel-1",
    )
    return {
        "schema_version": INVESTIGATION_RUN_VERSION,
        "run_id": "run-1",
        "run_status": "success",
        "ledger": {
            "candidates": [
                {
                    "candidate_id": "cand-1",
                    "claim_type": claim["claim_type"],
                    "statement": claim["statement"],
                    "polarity": claim["polarity"],
                    "evidence_refs": claim["evidence_refs"],
                    "concept_refs": claim["concept_refs"],
                    "attributes": copy.deepcopy(claim["attributes"]),
                }
            ],
            "verification_decisions": [
                {
                    "verification_id": "ver-1",
                    "candidate_ref": "cand-1",
                    "disposition": "supported",
                    "evidence_resolution": "resolved",
                    "source_revision_id": "src-1",
                    "resolution_authority": "t2-evidence-selector-v1",
                    "resolution_artifact_ref": "selector-artifact-ver-1",
                    "verified_evidence_refs": ["ev-1"],
                    "canonical_claim_ref": "clm-1",
                    "projection_eligibility": "factual",
                    "eligibility_artifact_ref": "eligibility-ver-1",
                }
            ],
            "claims": [claim],
            "evidence": copy.deepcopy(extraction["evidence"]),
            "concepts": copy.deepcopy(extraction["concepts"]),
            "relationships": [relationship],
        },
        "projections": {
            "summary": {
                "released_claim_refs": ["clm-1"],
                "themes": copy.deepcopy(extraction["themes"]),
                "narrative": copy.deepcopy(extraction["narrative"]),
            },
            "analysis": {
                "released_claim_refs": ["clm-1"],
                "fact_claim_refs": ["clm-1"],
                "relationship_refs": ["rel-1"],
            },
        },
        "provenance": copy.deepcopy(extraction["provenance"]),
        "safety": copy.deepcopy(extraction["safety"]),
        "manifest": _investigation_run_manifest(),
    }


def _no_claims_investigation_run_payload() -> dict:
    extraction = _no_claims_payload()
    return {
        "schema_version": INVESTIGATION_RUN_VERSION,
        "run_id": "run-empty",
        "run_status": "no_extractable_claims",
        "provenance": copy.deepcopy(extraction["provenance"]),
        "safety": copy.deepcopy(extraction["safety"]),
        "manifest": _investigation_run_manifest(),
    }


def _add_withheld_premise(payload: dict) -> None:
    ledger = payload["ledger"]
    ledger["candidates"].append(
        {
            "candidate_id": "cand-premise",
            "claim_type": "premise.explicit_source_fact",
            "statement": "Một premise transcript-grounded được giữ trong ledger.",
            "polarity": "affirmed",
            "evidence_refs": ["ev-1"],
        }
    )
    ledger["verification_decisions"].append(
        {
            "verification_id": "ver-premise",
            "candidate_ref": "cand-premise",
            "disposition": "supported",
            "evidence_resolution": "resolved",
            "source_revision_id": "src-1",
            "resolution_authority": "t2-evidence-selector-v1",
            "resolution_artifact_ref": "selector-artifact-ver-premise",
            "verified_evidence_refs": ["ev-1"],
            "canonical_claim_ref": "clm-premise",
            "projection_eligibility": "withheld",
        }
    )
    ledger["claims"].append(
        {
            "claim_id": "clm-premise",
            "claim_type": "premise.explicit_source_fact",
            "statement": "Một premise transcript-grounded được giữ trong ledger.",
            "polarity": "affirmed",
            "disposition": "supported",
            "evidence_refs": ["ev-1"],
            "candidate_refs": ["cand-premise"],
            "risk_tier": "ordinary",
            "risk_screening_artifact_ref": "risk-screening-clm-premise",
        }
    )


def _add_released_fact_without_theme(payload: dict) -> None:
    ledger = payload["ledger"]
    ledger["candidates"].append(
        {
            "candidate_id": "cand-2",
            "claim_type": "unseen.second_fact",
            "statement": "Claim thứ hai không được gán primary theme.",
            "polarity": "affirmed",
            "evidence_refs": ["ev-1"],
        }
    )
    ledger["verification_decisions"].append(
        {
            "verification_id": "ver-2",
            "candidate_ref": "cand-2",
            "disposition": "supported",
            "evidence_resolution": "resolved",
            "source_revision_id": "src-1",
            "resolution_authority": "t2-evidence-selector-v1",
            "resolution_artifact_ref": "selector-artifact-ver-2",
            "verified_evidence_refs": ["ev-1"],
            "canonical_claim_ref": "clm-2",
            "projection_eligibility": "factual",
            "eligibility_artifact_ref": "eligibility-ver-2",
        }
    )
    ledger["claims"].append(
        {
            "claim_id": "clm-2",
            "claim_type": "unseen.second_fact",
            "statement": "Claim thứ hai không được gán primary theme.",
            "polarity": "affirmed",
            "disposition": "supported",
            "evidence_refs": ["ev-1"],
            "candidate_refs": ["cand-2"],
            "risk_tier": "ordinary",
            "risk_screening_artifact_ref": "risk-screening-clm-2",
        }
    )
    projections = payload["projections"]
    projections["summary"]["released_claim_refs"].append("clm-2")
    projections["analysis"]["released_claim_refs"].append("clm-2")
    projections["analysis"]["fact_claim_refs"].append("clm-2")


def _add_released_insight(payload: dict) -> None:
    payload["ledger"]["insights"] = [
        {
            "insight_id": "ins-1",
            "statement": "Các lượt nói cùng quy chiếu đến một dữ kiện đã xác minh.",
            "derivation_type": "shared_attribute",
            "scope": "single_source",
            "premise_claim_refs": ["clm-1"],
            "evidence_refs": ["ev-1"],
            "counterevidence_status": "none_found",
            "risk_tier": "ordinary",
            "risk_screening_artifact_ref": "risk-screening-ins-1",
            "projection_eligibility": "factual",
            "eligibility_artifact_ref": "eligibility-ins-1",
            "requires_human_verification": False,
        }
    ]
    summary = payload["projections"]["summary"]
    summary["insight_refs"] = ["ins-1"]
    summary["themes"][0]["insight_refs"] = ["ins-1"]
    summary["narrative"]["overview"][0]["insight_refs"] = ["ins-1"]
    analysis = payload["projections"]["analysis"]
    analysis["insight_refs"] = ["ins-1"]


def _add_released_hypothesis(payload: dict) -> None:
    payload["ledger"]["hypotheses"] = [
        {
            "hypothesis_id": "hyp-1",
            "statement": "Lời phủ nhận có thể nhằm che giấu một giao dịch.",
            "premise_claim_refs": ["clm-1"],
            "evidence_refs": ["ev-1"],
            "alternative_explanations": [
                "Người nói có thể thực sự không thực hiện giao dịch."
            ],
            "counterevidence_status": "not_evaluated",
            "uncertainty_reason": (
                "Nguồn chỉ ghi nhận lời phủ nhận, chưa có hồ sơ giao dịch."
            ),
            "risk_tier": "high_risk",
            "risk_screening_artifact_ref": "risk-screening-hyp-1",
            "projection_eligibility": "non_factual",
            "eligibility_artifact_ref": "eligibility-hyp-1",
            "requires_human_verification": True,
        }
    ]
    summary = payload["projections"]["summary"]
    summary["hypothesis_refs"] = ["hyp-1"]
    summary["themes"][0]["hypothesis_refs"] = ["hyp-1"]
    payload["projections"]["analysis"]["hypothesis_refs"] = ["hyp-1"]


def test_extraction_compatibility_is_separate_from_released_projections():
    assert AdaptiveExtractionContract is AdaptiveSummaryAnalysisContract
    assert AdaptiveSummaryContract is AdaptiveSummaryAnalysisContract
    assert AdaptiveAnalysisContract is AdaptiveSummaryAnalysisContract
    assert InvestigationSummaryProjection is SummaryProjection
    assert InvestigationAnalysisProjection is AnalysisProjection

    result = AdaptiveExtractionContract.model_validate(_base_payload())

    assert result.claims[0].claim_type == "unseen.financial.negated_transfer"
    assert result.concepts[0].concept_type == "unseen.object.custom_identifier"
    assert result.claims[0].attributes["previously_unseen_attribute"]["normalized"] == 0
    assert result.claims[0].polarity == "negated"
    assert result.claims[0].disposition == "supported"


@pytest.mark.parametrize(
    "command",
    [
        (
            "import src.services.investigation.reasoning_contracts as r; "
            "import src.services.investigation.run_contracts as u; "
            "import src.services.investigation.contracts as c; "
            "assert c.InvestigationRun is u.InvestigationRun; "
            "assert c.EvidenceBackedInsight is r.EvidenceBackedInsight"
        ),
        (
            "import src.services.investigation.run_contracts as u; "
            "from src.services.investigation.contracts import SummaryProjection; "
            "assert SummaryProjection is u.SummaryProjection"
        ),
    ],
)
def test_split_contract_modules_are_import_order_independent(command):
    subprocess.check_call([sys.executable, "-c", command])


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
        ValidationError, match=r"factual narrative requires fact \+ supported"
    ):
        AdaptiveSummaryAnalysisContract.model_validate(payload)

    payload["narrative"]["overview"][0]["sentence_kind"] = "uncertainty"
    payload["narrative"]["thematic_groups"][0]["sentences"][0][
        "sentence_kind"
    ] = "uncertainty"
    result = AdaptiveSummaryAnalysisContract.model_validate(payload)
    assert result.claims[0].requires_human_verification is True


def test_investigation_run_owns_one_ledger_and_two_shared_projections():
    result = _validate_run(_investigation_run_payload())

    assert result.run_status == "success"
    assert result.ledger is not None
    assert result.projections is not None
    assert result.projections.summary.released_claim_refs == ["clm-1"]
    assert result.projections.analysis.released_claim_refs == ["clm-1"]
    assert result.ledger.claims[0].epistemic_status == "fact"
    assert result.ledger.relationships[0].evidence_resolution == "resolved"


def test_success_cannot_validate_without_internal_release_context():
    payload = _investigation_run_payload()

    with pytest.raises(
        ValidationError,
        match="success requires trusted T2 selector and T4 risk validation context",
    ):
        InvestigationRun.model_validate(payload)

    with pytest.raises(ValidationError, match="success requires trusted"):
        InvestigationRun.model_validate(
            payload,
            context={"investigation_release_authority": payload},
        )


def test_raw_payload_cannot_spoof_t2_artifact_or_evidence_hashes():
    payload = _investigation_run_payload()
    trusted_context = _trusted_context(payload)
    decision = payload["ledger"]["verification_decisions"][0]
    decision["resolution_artifact_ref"] = "fabricated-selector-artifact"

    with pytest.raises(ValidationError, match="verification semantics do not match"):
        _validate_run(payload, trusted_context=trusted_context)

    payload = _investigation_run_payload()
    trusted_context = _trusted_context(payload)
    evidence = payload["ledger"]["evidence"][0]
    evidence["quote_sha256"] = "0" * 64
    evidence["source_sha256"] = "f" * 64

    with pytest.raises(ValidationError, match="quote_sha256 must match quote_exact"):
        _validate_run(payload, trusted_context=trusted_context)

    payload = _investigation_run_payload()
    trusted_context = _trusted_context(payload)
    payload["ledger"]["evidence"][0]["quote_exact"] = "Nội dung đã bị thay đổi."

    with pytest.raises(ValidationError, match="quote_sha256 must match quote_exact"):
        _validate_run(payload, trusted_context=trusted_context)


def test_trusted_context_is_bound_to_claim_and_relationship_semantics():
    payload = _investigation_run_payload()
    trusted_context = _trusted_context(payload)
    claim = payload["ledger"]["claims"][0]
    claim["claim_type"] = "accusation.organized_crime"
    claim["statement"] = "Người được nhắc điều hành một đường dây tội phạm."

    with pytest.raises(ValidationError, match="verification semantics do not match"):
        _validate_run(payload, trusted_context=trusted_context)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quote_prefix", "Ngữ cảnh trước đã bị giả mạo."),
        ("quote_suffix", "Ngữ cảnh sau đã bị giả mạo."),
    ],
)
def test_t2_attestation_binds_quote_context(field, value):
    payload = _investigation_run_payload()
    trusted_context = _trusted_context(payload)
    payload["ledger"]["evidence"][0][field] = value

    with pytest.raises(
        ValidationError,
        match="evidence selector fields do not match trusted T2 context",
    ):
        _validate_run(payload, trusted_context=trusted_context)

    payload = _investigation_run_payload()
    trusted_context = _trusted_context(payload)
    relationship = payload["ledger"]["relationships"][0]
    relationship["relationship_type"] = "hidden_criminal_network"

    with pytest.raises(ValidationError, match="relationship semantics changed"):
        _validate_run(payload, trusted_context=trusted_context)


def test_trusted_reasoning_eligibility_is_bound_to_exact_item_content():
    payload = _investigation_run_payload()
    _add_released_insight(payload)
    trusted_context = _trusted_context(payload)
    payload["ledger"]["insights"][0][
        "statement"
    ] = "Nội dung insight đã bị thay đổi sau khi được duyệt."

    with pytest.raises(ValidationError, match="semantics changed after trusted review"):
        _validate_run(payload, trusted_context=trusted_context)


@pytest.mark.parametrize("subject_ref", ["clm-1", "rel-1"])
def test_release_requires_trusted_risk_screening_not_payload_defaults(subject_ref):
    payload = _investigation_run_payload()
    if subject_ref == "clm-1":
        subject = payload["ledger"]["claims"][0]
        subject["statement"] = "Người được nhắc đã thực hiện hành vi phạm tội."
    else:
        subject = payload["ledger"]["relationships"][0]
        subject["relationship_type"] = "accused_of_crime"
    subject.pop("risk_tier")
    trusted_context = _trusted_context(
        payload,
        risk_overrides={subject_ref: "high_risk"},
    )

    with pytest.raises(ValidationError, match="explicit risk tier"):
        _validate_run(payload, trusted_context=trusted_context)

    payload = _investigation_run_payload()
    subject = (
        payload["ledger"]["claims"][0]
        if subject_ref == "clm-1"
        else payload["ledger"]["relationships"][0]
    )
    trusted_context = _trusted_context(
        payload,
        risk_overrides={subject_ref: "high_risk"},
    )
    with pytest.raises(ValidationError, match="does not match trusted screening"):
        _validate_run(payload, trusted_context=trusted_context)


def test_evidence_backed_insight_is_typed_and_mapped_to_factual_synthesis():
    payload = _investigation_run_payload()
    _add_released_insight(payload)

    result = _validate_run(payload)

    insight = result.ledger.insights[0]
    assert isinstance(insight, EvidenceBackedInsight)
    assert insight.derivation_type == "shared_attribute"
    assert result.projections.summary.insight_refs == ["ins-1"]
    assert result.projections.analysis.insight_refs == ["ins-1"]


def test_released_insight_cannot_use_withheld_premise():
    payload = _investigation_run_payload()
    _add_withheld_premise(payload)
    _add_released_insight(payload)
    insight = payload["ledger"]["insights"][0]
    insight["premise_claim_refs"] = ["clm-premise"]

    with pytest.raises(
        ValidationError,
        match="dangling released insight premise refs",
    ):
        _validate_run(payload)


def test_released_insight_requires_completed_counterevidence_review():
    payload = _investigation_run_payload()
    _add_released_insight(payload)
    payload["ledger"]["insights"][0]["counterevidence_status"] = "not_evaluated"

    with pytest.raises(
        ValidationError,
        match="released insight requires completed counterevidence review",
    ):
        _validate_run(payload)


def test_hypothesis_cannot_attach_unrelated_evidence():
    payload = _investigation_run_payload()
    _add_released_hypothesis(payload)
    unrelated_quote = "Một câu không liên quan đến premise của hypothesis."
    payload["ledger"]["evidence"].append(
        {
            "evidence_id": "ev-unrelated",
            "segment_id": "seg-unrelated",
            "quote_exact": unrelated_quote,
            "quote_sha256": _hash(unrelated_quote),
            "source_sha256": _hash(_FIXTURE_SOURCE),
        }
    )
    payload["ledger"]["hypotheses"][0]["evidence_refs"] = ["ev-unrelated"]
    trusted_context = _trusted_context(
        payload,
        risk_overrides={"hyp-1": "high_risk"},
    )

    with pytest.raises(
        ValidationError,
        match="hypothesis evidence must originate from premise",
    ):
        _validate_run(payload, trusted_context=trusted_context)


@pytest.mark.parametrize(
    "missing_field",
    ["derivation_type", "premise_claim_refs", "evidence_refs", "risk_tier"],
)
def test_insight_contract_rejects_missing_reasoning_fields(missing_field):
    payload = _investigation_run_payload()
    _add_released_insight(payload)
    payload["ledger"]["insights"][0].pop(missing_field)

    with pytest.raises(ValidationError):
        _validate_run(payload)


def test_hypothesis_is_typed_high_risk_and_never_factual_narrative():
    payload = _investigation_run_payload()
    _add_released_hypothesis(payload)
    trusted_context = _trusted_context(
        payload,
        risk_overrides={"hyp-1": "high_risk"},
    )

    result = _validate_run(payload, trusted_context=trusted_context)

    hypothesis = result.ledger.hypotheses[0]
    assert isinstance(hypothesis, Hypothesis)
    assert hypothesis.requires_human_verification is True
    assert result.projections.analysis.hypothesis_refs == ["hyp-1"]

    payload["projections"]["summary"]["narrative"]["overview"][0]["hypothesis_refs"] = [
        "hyp-1"
    ]
    with pytest.raises(ValidationError, match="extra_forbidden"):
        _validate_run(payload, trusted_context=trusted_context)


@pytest.mark.parametrize(
    "missing_field",
    [
        "alternative_explanations",
        "counterevidence_status",
        "uncertainty_reason",
        "requires_human_verification",
    ],
)
def test_hypothesis_contract_rejects_missing_safety_fields(missing_field):
    payload = _investigation_run_payload()
    _add_released_hypothesis(payload)
    payload["ledger"]["hypotheses"][0].pop(missing_field)

    with pytest.raises(ValidationError):
        _validate_run(payload)


@pytest.mark.parametrize(
    "missing_field",
    [
        "target_ref",
        "evidence_refs",
        "required_source_type",
        "question",
        "promotion_criterion",
        "rejection_criterion",
    ],
)
def test_verification_action_contract_rejects_missing_operational_fields(
    missing_field,
):
    action = {
        "action_id": "act-1",
        "target_ref": "clm-1",
        "linked_claim_refs": ["clm-1"],
        "evidence_refs": ["ev-1"],
        "required_source_type": "lawful-record",
        "question": "Dữ liệu hợp pháp xác nhận hay bác bỏ claim nào?",
        "promotion_criterion": "Nguồn độc lập khớp định danh và sự kiện.",
        "rejection_criterion": "Nguồn độc lập chứng minh claim sai.",
        "projection_eligibility": "non_factual",
        "eligibility_artifact_ref": "eligibility-act-1",
        "requires_human_verification": True,
    }
    action.pop(missing_field)

    with pytest.raises(ValidationError):
        VerificationAction.model_validate(action)


def test_success_without_released_projections_fails_closed():
    payload = _investigation_run_payload()
    payload.pop("projections")

    with pytest.raises(ValidationError, match="success requires ledger"):
        _validate_run(payload)


def test_every_released_claim_requires_exactly_one_primary_theme():
    payload = _investigation_run_payload()
    _add_released_fact_without_theme(payload)

    with pytest.raises(
        ValidationError, match="every released claim requires exactly one primary theme"
    ):
        _validate_run(payload)


def test_partially_supported_claim_cannot_enter_factual_narrative():
    payload = _investigation_run_payload()
    payload["ledger"]["claims"][0]["disposition"] = "partially_supported"
    payload["ledger"]["claims"][0]["requires_human_verification"] = True
    decision = payload["ledger"]["verification_decisions"][0]
    decision["disposition"] = "partially_supported"
    decision["projection_eligibility"] = "non_factual"
    analysis = payload["projections"]["analysis"]
    analysis.pop("fact_claim_refs")
    analysis["qualified_claim_refs"] = ["clm-1"]

    with pytest.raises(
        ValidationError, match=r"factual narrative requires fact \+ supported"
    ):
        _validate_run(payload)


def test_partially_supported_claim_is_visible_only_as_qualified_output():
    payload = _investigation_run_payload()
    claim = payload["ledger"]["claims"][0]
    claim["disposition"] = "partially_supported"
    claim["requires_human_verification"] = True
    decision = payload["ledger"]["verification_decisions"][0]
    decision["disposition"] = "partially_supported"
    decision["projection_eligibility"] = "non_factual"
    summary = payload["projections"]["summary"]
    summary["narrative"]["overview"][0]["sentence_kind"] = "uncertainty"
    summary["narrative"]["thematic_groups"][0]["sentences"][0][
        "sentence_kind"
    ] = "uncertainty"
    analysis = payload["projections"]["analysis"]
    analysis.pop("fact_claim_refs")
    analysis["qualified_claim_refs"] = ["clm-1"]

    result = _validate_run(payload)

    assert result.projections.analysis.fact_claim_refs is None
    assert result.projections.analysis.qualified_claim_refs == ["clm-1"]
    assert result.ledger.claims[0].requires_human_verification is True


def test_generic_non_factual_claim_cannot_replace_typed_hypothesis():
    payload = _investigation_run_payload()
    _add_withheld_premise(payload)
    candidate = payload["ledger"]["candidates"][0]
    candidate.update(
        epistemic_status="hypothesis",
        requires_human_verification=True,
        premise_candidate_refs=["cand-premise"],
    )
    claim = payload["ledger"]["claims"][0]
    claim.update(
        epistemic_status="hypothesis",
        requires_human_verification=True,
        premise_claim_refs=["clm-premise"],
    )
    payload["ledger"]["verification_decisions"][0][
        "projection_eligibility"
    ] = "non_factual"
    with pytest.raises(
        ValidationError,
        match="non-factual intelligence requires its dedicated typed contract",
    ):
        _validate_run(payload)


def test_verification_action_uses_a_distinct_typed_projection():
    payload = _investigation_run_payload()
    payload["ledger"]["verification_actions"] = [
        {
            "action_id": "act-1",
            "target_ref": "clm-1",
            "linked_claim_refs": ["clm-1"],
            "evidence_refs": ["ev-1"],
            "required_source_type": "lawful-account-holder-record",
            "question": "Ai là chủ tài khoản được nhắc trong nguồn?",
            "promotion_criterion": "Hồ sơ hợp pháp khớp định danh và tài khoản.",
            "rejection_criterion": (
                "Hồ sơ hợp pháp chứng minh tài khoản thuộc người khác."
            ),
            "projection_eligibility": "non_factual",
            "eligibility_artifact_ref": "eligibility-act-1",
            "requires_human_verification": True,
        }
    ]
    summary = payload["projections"]["summary"]
    summary["verification_action_refs"] = ["act-1"]
    summary["themes"][0]["verification_action_refs"] = ["act-1"]
    analysis = payload["projections"]["analysis"]
    analysis["verification_action_refs"] = ["act-1"]

    result = _validate_run(payload)

    action = result.ledger.verification_actions[0]
    assert isinstance(action, VerificationAction)
    assert action.target_ref == "clm-1"
    assert result.projections.analysis.verification_action_refs == ["act-1"]


def test_verification_action_can_target_a_linked_concept():
    payload = _investigation_run_payload()
    payload["ledger"]["verification_actions"] = [
        {
            "action_id": "act-concept",
            "target_ref": "con-1",
            "linked_concept_refs": ["con-1"],
            "evidence_refs": ["ev-1"],
            "required_source_type": "lawful-identity-record",
            "question": "Định danh nào tương ứng với đối tượng được nhắc đến?",
            "promotion_criterion": "Nguồn hợp pháp xác nhận định danh.",
            "rejection_criterion": "Nguồn hợp pháp bác bỏ định danh.",
            "projection_eligibility": "non_factual",
            "eligibility_artifact_ref": "eligibility-act-concept",
            "requires_human_verification": True,
        }
    ]
    summary = payload["projections"]["summary"]
    summary["verification_action_refs"] = ["act-concept"]
    summary["themes"][0]["verification_action_refs"] = ["act-concept"]
    payload["projections"]["analysis"]["verification_action_refs"] = ["act-concept"]

    result = _validate_run(payload)

    action = result.ledger.verification_actions[0]
    assert action.target_ref == "con-1"
    assert action.linked_concept_refs == ["con-1"]


def test_withheld_verification_action_rejects_dangling_evidence():
    payload = _investigation_run_payload()
    payload["run_status"] = "needs_review"
    payload.pop("projections")
    payload["gate_failures"] = [
        {
            "code": "ACTION_REQUIRES_REVIEW",
            "stage": "reasoning",
            "message": "Verification action remains diagnostic.",
        }
    ]
    payload["ledger"]["verification_actions"] = [
        {
            "action_id": "act-dangling",
            "target_ref": "clm-1",
            "linked_claim_refs": ["clm-1"],
            "evidence_refs": ["ev-missing"],
            "required_source_type": "lawful-record",
            "question": "Nguồn độc lập xác nhận hay bác bỏ claim?",
            "promotion_criterion": "Nguồn độc lập xác nhận claim.",
            "rejection_criterion": "Nguồn độc lập bác bỏ claim.",
            "projection_eligibility": "withheld",
            "eligibility_artifact_ref": "eligibility-act-dangling",
            "requires_human_verification": True,
        }
    ]

    with pytest.raises(
        ValidationError,
        match="dangling verification action evidence refs: ev-missing",
    ):
        _validate_run(payload)


def test_verification_action_cannot_attach_unrelated_evidence():
    payload = _investigation_run_payload()
    payload["ledger"]["verification_actions"] = [
        {
            "action_id": "act-1",
            "target_ref": "clm-1",
            "linked_claim_refs": ["clm-1"],
            "evidence_refs": ["ev-unrelated"],
            "required_source_type": "lawful-record",
            "question": "Nguồn độc lập xác nhận hay bác bỏ claim?",
            "promotion_criterion": "Nguồn độc lập xác nhận claim.",
            "rejection_criterion": "Nguồn độc lập bác bỏ claim.",
            "projection_eligibility": "non_factual",
            "eligibility_artifact_ref": "eligibility-act-1",
            "requires_human_verification": True,
        }
    ]
    unrelated_quote = "Nội dung không thuộc target của verification action."
    payload["ledger"]["evidence"].append(
        {
            "evidence_id": "ev-unrelated",
            "segment_id": "seg-unrelated",
            "quote_exact": unrelated_quote,
            "quote_sha256": _hash(unrelated_quote),
            "source_sha256": _hash(_FIXTURE_SOURCE),
        }
    )
    summary = payload["projections"]["summary"]
    summary["verification_action_refs"] = ["act-1"]
    summary["themes"][0]["verification_action_refs"] = ["act-1"]
    payload["projections"]["analysis"]["verification_action_refs"] = ["act-1"]

    with pytest.raises(
        ValidationError,
        match="verification action evidence must originate from linked items",
    ):
        _validate_run(payload)


@pytest.mark.parametrize("resolution", ["unresolved", "revision_mismatch"])
def test_unresolved_or_revision_mismatch_evidence_cannot_be_released(resolution):
    payload = _investigation_run_payload()
    decision = payload["ledger"]["verification_decisions"][0]
    decision["evidence_resolution"] = resolution
    decision["projection_eligibility"] = "withheld"
    decision.pop("verified_evidence_refs")

    with pytest.raises(
        ValidationError,
        match="canonical claim evidence requires a resolved verification",
    ):
        _validate_run(payload)


def test_shape_valid_wrong_hash_is_not_claimed_resolved_before_t2():
    payload = _investigation_run_payload()
    evidence = payload["ledger"]["evidence"][0]
    evidence["quote_sha256"] = "0" * 64
    evidence["source_sha256"] = "f" * 64
    decision = payload["ledger"]["verification_decisions"][0]
    decision["evidence_resolution"] = "unresolved"
    decision["projection_eligibility"] = "withheld"
    decision.pop("verified_evidence_refs")

    with pytest.raises(
        ValidationError,
        match="quote_sha256 must match quote_exact",
    ):
        _validate_run(payload)


def test_verifier_source_revision_mismatch_fails_release():
    payload = _investigation_run_payload()
    payload["ledger"]["verification_decisions"][0]["source_revision_id"] = "src-stale"

    with pytest.raises(ValidationError, match="verification source revision mismatch"):
        _validate_run(payload)


def test_needs_review_preserves_diagnostic_ledger_without_projections():
    payload = _investigation_run_payload()
    payload["run_status"] = "needs_review"
    payload.pop("projections")
    payload["gate_failures"] = [
        {
            "code": "EVIDENCE_SELECTOR_UNRESOLVED",
            "stage": "verification",
            "message": "Selector requires T2 resolution.",
            "refs": ["cand-1", "ev-1"],
        }
    ]

    result = _validate_run(payload)

    assert result.run_status == "needs_review"
    assert result.ledger is not None
    assert result.projections is None
    assert result.gate_failures[0].code == "EVIDENCE_SELECTOR_UNRESOLVED"


def test_needs_review_can_preserve_candidates_when_no_claim_is_canonicalized():
    payload = _investigation_run_payload()
    payload["run_status"] = "needs_review"
    payload.pop("projections")
    ledger = payload["ledger"]
    ledger["claims"] = []
    ledger.pop("relationships")
    decision = ledger["verification_decisions"][0]
    decision["disposition"] = "contradicted"
    decision["projection_eligibility"] = "withheld"
    decision.pop("canonical_claim_ref")
    payload["gate_failures"] = [
        {
            "code": "NO_CANONICAL_CLAIM",
            "stage": "verification",
            "message": "All candidates were contradicted or withheld.",
            "refs": ["cand-1"],
        }
    ]

    result = _validate_run(payload)

    assert result.run_status == "needs_review"
    assert result.ledger.claims == []


def test_needs_review_cannot_publish_projections():
    payload = _investigation_run_payload()
    payload["run_status"] = "needs_review"
    payload["gate_failures"] = [
        {
            "code": "QUALITY_GATE_FAILED",
            "stage": "release",
            "message": "Release gate failed.",
        }
    ]

    with pytest.raises(
        ValidationError, match="needs_review cannot include released projections"
    ):
        _validate_run(payload)


def test_failed_run_requires_machine_readable_blocking_failure():
    payload = _no_claims_investigation_run_payload()
    payload["run_status"] = "failed"

    with pytest.raises(
        ValidationError, match="failed runs require a blocking gate failure"
    ):
        _validate_run(payload)

    payload["gate_failures"] = [
        {
            "code": "MODEL_GENERATION_FAILED",
            "stage": "discovery",
            "message": "The offline model did not return a valid candidate payload.",
        }
    ]
    assert _validate_run(payload).run_status == "failed"


def test_no_extractable_claims_omits_ledger_and_projections():
    payload = _no_claims_investigation_run_payload()
    result = _validate_run(payload)

    assert result.run_status == "no_extractable_claims"
    assert result.ledger is None
    assert result.projections is None

    payload["ledger"] = _investigation_run_payload()["ledger"]
    with pytest.raises(
        ValidationError, match="no_extractable_claims cannot include ledger"
    ):
        _validate_run(payload)


def test_released_relationship_requires_resolved_revision_and_epistemic_state():
    payload = _investigation_run_payload()
    relationship = payload["ledger"]["relationships"][0]
    relationship["evidence_resolution"] = "unresolved"
    relationship.pop("source_revision_id")

    with pytest.raises(
        ValidationError, match="unresolved relationships must remain withheld"
    ):
        _validate_run(payload)

    payload = _investigation_run_payload()
    relationship = payload["ledger"]["relationships"][0]
    relationship.update(
        epistemic_status="hypothesis",
        requires_human_verification=True,
        premise_claim_refs=["clm-1"],
        projection_eligibility="non_factual",
    )
    result = _validate_run(payload)
    assert result.ledger.relationships[0].epistemic_status == "hypothesis"


def test_non_factual_relationship_cannot_depend_on_withheld_premise():
    payload = _investigation_run_payload()
    _add_withheld_premise(payload)
    relationship = payload["ledger"]["relationships"][0]
    relationship.update(
        epistemic_status="hypothesis",
        requires_human_verification=True,
        premise_claim_refs=["clm-premise"],
        projection_eligibility="non_factual",
    )

    with pytest.raises(
        ValidationError, match="dangling released relationship premise refs"
    ):
        _validate_run(payload)


def test_summary_and_analysis_must_use_the_same_released_claim_set():
    payload = _investigation_run_payload()
    payload["projections"]["analysis"]["released_claim_refs"] = ["clm-other"]
    payload["projections"]["analysis"]["fact_claim_refs"] = ["clm-other"]

    with pytest.raises(
        ValidationError, match="Summary and Analysis must project the same"
    ):
        _validate_run(payload)


def test_every_non_withheld_verified_claim_must_be_projected():
    payload = _investigation_run_payload()
    _add_released_fact_without_theme(payload)
    summary = payload["projections"]["summary"]
    analysis = payload["projections"]["analysis"]
    summary["released_claim_refs"].remove("clm-2")
    analysis["released_claim_refs"].remove("clm-2")
    analysis["fact_claim_refs"].remove("clm-2")

    with pytest.raises(
        ValidationError,
        match="released projections must include every non-withheld verified claim",
    ):
        _validate_run(payload)


def test_orphan_canonical_claim_without_candidate_refs_is_rejected():
    payload = _investigation_run_payload()
    payload["ledger"]["claims"][0].pop("candidate_refs")

    with pytest.raises(
        ValidationError, match="canonical claims must retain their source candidate"
    ):
        _validate_run(payload)


def test_orphan_canonical_claim_without_linked_decision_is_rejected():
    payload = _investigation_run_payload()
    decision = payload["ledger"]["verification_decisions"][0]
    decision.pop("canonical_claim_ref")
    decision["projection_eligibility"] = "withheld"

    with pytest.raises(
        ValidationError,
        match="every canonical claim requires a linked verification decision",
    ):
        _validate_run(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "disposition",
            "contradicted",
            "verification disposition must match the canonical claim",
        ),
        (
            "projection_eligibility",
            "non_factual",
            "verification eligibility conflicts with claim epistemics",
        ),
    ],
)
def test_linked_verification_must_be_consistent_with_canonical_claim(
    field,
    value,
    message,
):
    payload = _investigation_run_payload()
    payload["ledger"]["verification_decisions"][0][field] = value
    if field == "disposition":
        payload["ledger"]["verification_decisions"][0][
            "projection_eligibility"
        ] = "non_factual"

    with pytest.raises(ValidationError, match=message):
        _validate_run(payload)


def test_canonical_claim_requires_resolved_verifier_evidence():
    payload = _investigation_run_payload()
    decision = payload["ledger"]["verification_decisions"][0]
    decision["evidence_resolution"] = "unresolved"
    decision["projection_eligibility"] = "withheld"
    decision.pop("verified_evidence_refs")

    with pytest.raises(
        ValidationError,
        match="canonical claim evidence requires a resolved verification",
    ):
        _validate_run(payload)


def test_resolved_state_requires_explicit_t2_selector_attestation():
    payload = _investigation_run_payload()
    decision = payload["ledger"]["verification_decisions"][0]
    decision.pop("resolution_authority")

    with pytest.raises(
        ValidationError, match="resolved evidence requires a T2 selector attestation"
    ):
        _validate_run(payload)


def test_all_non_withheld_decisions_must_match_claim_eligibility():
    payload = _investigation_run_payload()
    ledger = payload["ledger"]
    ledger["candidates"].append(
        {
            "candidate_id": "cand-merge",
            "claim_type": "unseen.financial.negated_transfer",
            "statement": "Candidate merge thứ hai.",
            "polarity": "negated",
            "evidence_refs": ["ev-1"],
        }
    )
    ledger["claims"][0]["candidate_refs"].append("cand-merge")
    ledger["verification_decisions"].append(
        {
            "verification_id": "ver-merge",
            "candidate_ref": "cand-merge",
            "disposition": "supported",
            "evidence_resolution": "resolved",
            "source_revision_id": "src-1",
            "resolution_authority": "t2-evidence-selector-v1",
            "resolution_artifact_ref": "selector-artifact-ver-merge",
            "verified_evidence_refs": ["ev-1"],
            "canonical_claim_ref": "clm-1",
            "projection_eligibility": "non_factual",
            "eligibility_artifact_ref": "eligibility-ver-merge",
        }
    )

    with pytest.raises(
        ValidationError,
        match="verification eligibility conflicts with claim epistemics",
    ):
        _validate_run(payload)


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


def test_investigation_run_schema_hash_is_stable_across_processes():
    local_hash = investigation_run_schema_sha256()
    command = (
        "from src.services.investigation.contracts import "
        "investigation_run_schema_sha256; print(investigation_run_schema_sha256())"
    )
    process_hash = subprocess.check_output(
        [sys.executable, "-c", command],
        text=True,
    ).strip()

    assert process_hash == local_hash
    tampered = investigation_run_json_schema()
    tampered["title"] = "tampered-investigation-run"
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


def test_legacy_manifest_contract_discriminator_remains_fail_closed():
    manifest = _manifest()
    manifest["contract_version"] = INVESTIGATION_RUN_VERSION

    with pytest.raises(ValidationError):
        RunManifest.model_validate(manifest)

    run_manifest = _investigation_run_manifest()
    assert run_manifest["contract_version"] == INVESTIGATION_RUN_VERSION
    assert run_manifest["json_schema_sha256"] == investigation_run_schema_sha256()


@pytest.mark.parametrize("required_field", ["source_module_hashes", "git_revision"])
def test_investigation_manifest_requires_replayable_source_state(required_field):
    manifest = _investigation_run_manifest()
    manifest.pop(required_field)

    with pytest.raises(ValidationError):
        InvestigationRunManifest.model_validate(manifest)

    extraction_manifest = _manifest()
    extraction_manifest.pop(required_field)
    assert RunManifest.model_validate(extraction_manifest).contract_version == (
        ADAPTIVE_CONTRACT_VERSION
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("git_revision", "fabricated-revision"),
        ("prompt_sha256", "0" * 64),
    ],
)
def test_run_manifest_cannot_change_after_trusted_preflight(field, value):
    payload = _investigation_run_payload()
    trusted_context = _trusted_context(payload)
    payload["manifest"][field] = value

    with pytest.raises(
        ValidationError, match="manifest changed after trusted preflight"
    ):
        _validate_run(payload, trusted_context=trusted_context)


def test_source_module_hashes_cannot_be_fabricated_after_trusted_preflight():
    payload = _investigation_run_payload()
    trusted_context = _trusted_context(payload)
    payload["manifest"]["source_module_hashes"]["adaptive_contracts.py"] = "0" * 64

    with pytest.raises(
        ValidationError, match="manifest changed after trusted preflight"
    ):
        _validate_run(payload, trusted_context=trusted_context)


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


def test_investigation_run_schema_separates_ledger_and_projections():
    schema = investigation_run_json_schema()
    definitions = schema["$defs"]

    assert schema["additionalProperties"] is False
    assert definitions["CanonicalClaimLedger"]["additionalProperties"] is False
    assert definitions["SummaryProjection"]["additionalProperties"] is False
    assert definitions["AnalysisProjection"]["additionalProperties"] is False
    assert definitions["GateFailure"]["additionalProperties"] is False
    epistemic_schema = definitions["GroundedClaim"]["properties"]["epistemic_status"]
    assert set(epistemic_schema["enum"]) == {
        "fact",
        "inference",
        "hypothesis",
        "verification_action",
    }
