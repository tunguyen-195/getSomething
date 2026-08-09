"""Deterministic T5 narrative renderer and sealed release projection."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal
from weakref import WeakKeyDictionary

from pydantic import BaseModel, Field, field_validator

from .contracts import (
    AdaptiveTheme,
    EvidenceSpan,
    GroundedClaim,
    NarrativeAttestationArtifact,
    NarrativeCategory,
    NarrativeClaimClassification,
    NarrativePlacement,
    NarrativeSentence,
    NarrativeSynthesis,
    SourceProvenance,
    StrictEnvelope,
    ThematicNarrative,
    _ensure_unique,
    sha256_canonical_json,
    sha256_utf8,
)
from .reasoning_contracts import EvidenceBackedInsight


NARRATIVE_ATTESTATION_VERSION = "narrative-attestation-v2"
NARRATIVE_PRODUCER_ID = "deterministic-source-attribution-renderer-v2"
NARRATIVE_PRODUCER_DIGEST = sha256_utf8(
    "deterministic-source-attribution-renderer-v2|speaker-time-evidence|v2"
)
CANONICAL_THEME_ID = "theme-verified-facts"
CANONICAL_THEME_TITLE = "Nội dung đã xác minh từ nguồn âm thanh"

_CATEGORY_MARKERS: tuple[tuple[NarrativeCategory, tuple[str, ...]], ...] = (
    (
        "money_quantity",
        (
            "financial",
            "money",
            "amount",
            "payment",
            "transfer",
            "account",
            "tiền",
            "chuyển khoản",
            "tài khoản",
        ),
    ),
    ("contact", ("phone", "email", "contact", "điện thoại", "liên hệ")),
    (
        "identifier_object",
        (
            "identifier",
            "identity",
            "document",
            "vehicle",
            "plate",
            "cccd",
            "cmnd",
            "hộ chiếu",
            "biển số",
        ),
    ),
    ("temporal", ("time", "date", "schedule", "timeline", "thời gian", "ngày")),
    ("location", ("location", "place", "address", "địa điểm", "địa chỉ")),
    ("person_role", ("person", "actor", "role", "identity", "người", "vai trò")),
    (
        "event_action",
        (
            "event",
            "action",
            "decision",
            "commitment",
            "meeting",
            "arrival",
            "communication",
            "sự kiện",
            "hành động",
        ),
    ),
)
_EXACT_VALUE_PATTERN = re.compile(
    r"(?:\d|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
)


class NarrativeReleaseBundle(StrictEnvelope):
    released_claim_refs: list[str] = Field(min_length=1)
    narrated_claim_refs: list[str] = Field(min_length=1)
    claim_classifications: list[NarrativeClaimClassification] = Field(min_length=1)
    insight_refs: list[str] | None = None
    themes: list[AdaptiveTheme] = Field(min_length=1)
    narrative: NarrativeSynthesis
    narrative_attestations: list[NarrativeAttestationArtifact] = Field(min_length=1)

    @field_validator("released_claim_refs", "narrated_claim_refs", "insight_refs")
    @classmethod
    def unique_release_refs(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return _ensure_unique(values, "narrative release references")


def _model_payload(value: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    return dict(value)


def narrative_subject_sha256(value: BaseModel | Mapping[str, Any]) -> str:
    return sha256_canonical_json(_model_payload(value))


def classify_released_claim(claim: GroundedClaim) -> NarrativeClaimClassification:
    searchable = f"{claim.claim_type} {claim.statement}".casefold()
    category: NarrativeCategory = "general"
    for candidate, markers in _CATEGORY_MARKERS:
        if any(marker in searchable for marker in markers):
            category = candidate
            break
    if category == "general" and _EXACT_VALUE_PATTERN.search(claim.statement):
        category = "exact_value"
    # S2 has no independently attested salience authority, so every released
    # factual claim receives the strongest placement requirement.
    salience: Literal["critical", "supporting"] = "critical"
    return NarrativeClaimClassification(
        claim_ref=claim.claim_id,
        category=category,
        salience=salience,
        required_placement=(
            "overview_or_critical_detail" if salience == "critical" else "narrative"
        ),
    )


def _format_audio_time(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds_part:02d}"
    return f"{minutes:02d}:{seconds_part:02d}"


def _source_attribution_prefix(
    evidence_refs: Sequence[str],
    evidence_by_id: Mapping[str, EvidenceSpan],
) -> str:
    evidence = [evidence_by_id[ref] for ref in evidence_refs]
    speakers = list(
        dict.fromkeys(item.speaker_id for item in evidence if item.speaker_id is not None)
    )
    if len(speakers) == 1:
        prefix = f"Người nói {speakers[0]}"
    elif speakers:
        prefix = "Các người nói " + ", ".join(speakers)
    else:
        prefix = "Người nói chưa xác định"

    timed = [
        item
        for item in evidence
        if item.start_seconds is not None and item.end_seconds is not None
    ]
    if timed:
        start = min(float(item.start_seconds) for item in timed)
        end = max(float(item.end_seconds) for item in timed)
        prefix += f" tại {_format_audio_time(start)}-{_format_audio_time(end)}"
    return prefix


def expected_narrative_sentence_kind(
    *,
    claim_refs: Sequence[str],
    insight_refs: Sequence[str],
    claim_by_id: Mapping[str, GroundedClaim],
) -> Literal["source_attributed", "factual", "derived_insight"]:
    if insight_refs:
        return "derived_insight"
    scopes = {claim_by_id[ref].factual_scope for ref in claim_refs}
    if scopes == {"verified_source_assertion"}:
        return "source_attributed"
    if scopes == {"corroborated_world_finding"}:
        return "factual"
    raise ValueError("narrative sentence requires one explicit factual scope")


def expected_narrative_sentence_text(
    *,
    claim_refs: Sequence[str],
    insight_refs: Sequence[str],
    claim_by_id: Mapping[str, GroundedClaim],
    evidence_by_id: Mapping[str, EvidenceSpan],
    insight_by_id: Mapping[str, EvidenceBackedInsight],
) -> str:
    if insight_refs:
        return " ".join(insight_by_id[ref].statement for ref in insight_refs)
    rendered: list[str] = []
    for claim_ref in claim_refs:
        claim = claim_by_id[claim_ref]
        if claim.factual_scope == "verified_source_assertion":
            for evidence_ref in claim.evidence_refs:
                evidence = evidence_by_id[evidence_ref]
                prefix = _source_attribution_prefix([evidence_ref], evidence_by_id)
                rendered.append(f"{prefix} phát biểu: “{evidence.quote_exact}”")
        elif claim.factual_scope == "corroborated_world_finding":
            rendered.append(claim.statement)
        else:
            raise ValueError("released claim is missing an explicit factual scope")
    return " ".join(rendered)


def expected_narrative_evidence_refs(
    *,
    claim_refs: Sequence[str],
    insight_refs: Sequence[str],
    claim_by_id: Mapping[str, GroundedClaim],
    insight_by_id: Mapping[str, EvidenceBackedInsight],
) -> list[str]:
    ordered: list[str] = []
    for claim_ref in claim_refs:
        ordered.extend(claim_by_id[claim_ref].evidence_refs)
    for insight_ref in insight_refs:
        ordered.extend(insight_by_id[insight_ref].evidence_refs)
    return list(dict.fromkeys(ordered))


def _sentence_id(
    *,
    source_revision_id: str,
    placement_role: NarrativePlacement,
    claim_refs: Sequence[str],
    insight_refs: Sequence[str],
    ordinal: int,
) -> str:
    digest = sha256_canonical_json(
        {
            "source_revision_id": source_revision_id,
            "placement_role": placement_role,
            "claim_refs": list(claim_refs),
            "insight_refs": list(insight_refs),
            "ordinal": ordinal,
        }
    )
    return f"sentv1:{digest}"


def _build_attested_sentence(
    *,
    source_provenance: SourceProvenance,
    generation_manifest: BaseModel | Mapping[str, Any],
    placement_role: NarrativePlacement,
    claim_refs: Sequence[str],
    insight_refs: Sequence[str],
    claim_by_id: Mapping[str, GroundedClaim],
    evidence_by_id: Mapping[str, EvidenceSpan],
    insight_by_id: Mapping[str, EvidenceBackedInsight],
    ordinal: int,
) -> tuple[NarrativeSentence, NarrativeAttestationArtifact]:
    claim_ref_list = list(claim_refs)
    insight_ref_list = list(insight_refs)
    text = expected_narrative_sentence_text(
        claim_refs=claim_ref_list,
        insight_refs=insight_ref_list,
        claim_by_id=claim_by_id,
        evidence_by_id=evidence_by_id,
        insight_by_id=insight_by_id,
    )
    sentence_kind = expected_narrative_sentence_kind(
        claim_refs=claim_ref_list,
        insight_refs=insight_ref_list,
        claim_by_id=claim_by_id,
    )
    evidence_refs = expected_narrative_evidence_refs(
        claim_refs=claim_ref_list,
        insight_refs=insight_ref_list,
        claim_by_id=claim_by_id,
        insight_by_id=insight_by_id,
    )
    sentence_id = _sentence_id(
        source_revision_id=source_provenance.source_revision_id,
        placement_role=placement_role,
        claim_refs=claim_ref_list,
        insight_refs=insight_ref_list,
        ordinal=ordinal,
    )
    content_sha256 = sha256_utf8(text)
    artifact_payload: dict[str, Any] = {
        "schema_version": NARRATIVE_ATTESTATION_VERSION,
        "producer_id": NARRATIVE_PRODUCER_ID,
        "producer_digest": NARRATIVE_PRODUCER_DIGEST,
        "source_revision_id": source_provenance.source_revision_id,
        "source_provenance_sha256": narrative_subject_sha256(source_provenance),
        "generation_manifest_sha256": narrative_subject_sha256(generation_manifest),
        "sentence_id": sentence_id,
        "sentence_kind": sentence_kind,
        "placement_role": placement_role,
        "content_sha256": content_sha256,
        "claim_refs": claim_ref_list,
        "claim_sha256": {
            ref: narrative_subject_sha256(claim_by_id[ref]) for ref in claim_ref_list
        },
        "evidence_refs": evidence_refs,
        "evidence_sha256": {
            ref: narrative_subject_sha256(evidence_by_id[ref]) for ref in evidence_refs
        },
        "decision": "supported",
        "replay_verified": True,
    }
    if insight_ref_list:
        artifact_payload["insight_refs"] = insight_ref_list
        artifact_payload["insight_sha256"] = {
            ref: narrative_subject_sha256(insight_by_id[ref])
            for ref in insight_ref_list
        }
    artifact_payload["artifact_id"] = (
        f"t5attv1:{sha256_canonical_json(artifact_payload)}"
    )
    artifact = NarrativeAttestationArtifact.model_validate(artifact_payload)
    sentence_payload: dict[str, Any] = {
        "sentence_id": sentence_id,
        "text": text,
        "sentence_kind": sentence_kind,
        "placement_role": placement_role,
        "claim_refs": claim_ref_list,
        "evidence_refs": evidence_refs,
        "content_sha256": content_sha256,
        "semantic_attestation_ref": artifact.artifact_id,
    }
    if insight_ref_list:
        sentence_payload["insight_refs"] = insight_ref_list
    sentence = NarrativeSentence.model_validate(sentence_payload)
    return sentence, artifact


def _claim_source_order(
    claim: GroundedClaim,
    evidence_by_id: Mapping[str, EvidenceSpan],
) -> tuple[float, int, str]:
    spans = [evidence_by_id[ref] for ref in claim.evidence_refs]
    timed = [item.start_seconds for item in spans if item.start_seconds is not None]
    raw_offsets = [item.raw_char_start for item in spans if item.raw_char_start is not None]
    return (
        min(float(value) for value in timed) if timed else float("inf"),
        min(int(value) for value in raw_offsets) if raw_offsets else 2**63 - 1,
        claim.claim_id,
    )


def build_deterministic_narrative_release(
    *,
    released_claims: Sequence[GroundedClaim],
    evidence: Sequence[EvidenceSpan],
    source_provenance: SourceProvenance | Mapping[str, Any],
    generation_manifest: BaseModel | Mapping[str, Any],
    released_insights: Sequence[EvidenceBackedInsight] = (),
) -> NarrativeReleaseBundle:
    """Render exact released semantics without accepting caller-authored prose."""

    claims = list(released_claims)
    if not claims:
        raise ValueError("deterministic narrative release requires released claims")
    provenance = SourceProvenance.model_validate(source_provenance)
    claim_by_id = {claim.claim_id: claim for claim in claims}
    evidence_by_id = {item.evidence_id: item for item in evidence}
    insight_by_id = {insight.insight_id: insight for insight in released_insights}
    if len(claim_by_id) != len(claims):
        raise ValueError("released narrative claim IDs must be unique")
    if len(evidence_by_id) != len(list(evidence)):
        raise ValueError("released narrative evidence IDs must be unique")
    if len(insight_by_id) != len(list(released_insights)):
        raise ValueError("released narrative insight IDs must be unique")

    claims = sorted(claims, key=lambda claim: _claim_source_order(claim, evidence_by_id))
    classifications = [classify_released_claim(claim) for claim in claims]
    classification_by_ref = {item.claim_ref: item for item in classifications}
    critical = [
        claim for claim in claims if classification_by_ref[claim.claim_id].salience == "critical"
    ]
    supporting = [
        claim
        for claim in claims
        if classification_by_ref[claim.claim_id].salience == "supporting"
    ]
    ordered_claims = [*critical, *supporting]

    overview_sentences: list[NarrativeSentence] = []
    attestations: list[NarrativeAttestationArtifact] = []
    overview_count = min(4, len(ordered_claims))
    for ordinal, claim in enumerate(ordered_claims[:overview_count]):
        sentence, artifact = _build_attested_sentence(
            source_provenance=provenance,
            generation_manifest=generation_manifest,
            placement_role="overview",
            claim_refs=[claim.claim_id],
            insight_refs=[],
            claim_by_id=claim_by_id,
            evidence_by_id=evidence_by_id,
            insight_by_id=insight_by_id,
            ordinal=ordinal,
        )
        overview_sentences.append(sentence)
        attestations.append(artifact)

    detail_sentences: list[NarrativeSentence] = []
    for ordinal, claim in enumerate(
        ordered_claims[overview_count:],
        start=overview_count,
    ):
        classification = classification_by_ref[claim.claim_id]
        sentence, artifact = _build_attested_sentence(
            source_provenance=provenance,
            generation_manifest=generation_manifest,
            placement_role=(
                "critical_detail"
                if classification.salience == "critical"
                else "thematic_detail"
            ),
            claim_refs=[claim.claim_id],
            insight_refs=[],
            claim_by_id=claim_by_id,
            evidence_by_id=evidence_by_id,
            insight_by_id=insight_by_id,
            ordinal=ordinal,
        )
        detail_sentences.append(sentence)
        attestations.append(artifact)

    insight_ordinal = len(ordered_claims)
    for offset, insight in enumerate(released_insights):
        sentence, artifact = _build_attested_sentence(
            source_provenance=provenance,
            generation_manifest=generation_manifest,
            placement_role="thematic_detail",
            claim_refs=insight.premise_claim_refs,
            insight_refs=[insight.insight_id],
            claim_by_id=claim_by_id,
            evidence_by_id=evidence_by_id,
            insight_by_id=insight_by_id,
            ordinal=insight_ordinal + offset,
        )
        detail_sentences.append(sentence)
        attestations.append(artifact)

    released_claim_refs = [claim.claim_id for claim in claims]
    released_insight_refs = [insight.insight_id for insight in released_insights]
    theme_payload: dict[str, Any] = {
        "theme_id": CANONICAL_THEME_ID,
        "title": CANONICAL_THEME_TITLE,
        "claim_refs": released_claim_refs,
    }
    if released_insight_refs:
        theme_payload["insight_refs"] = released_insight_refs
    theme = AdaptiveTheme.model_validate(theme_payload)
    narrative_payload: dict[str, Any] = {"overview": overview_sentences}
    if detail_sentences:
        narrative_payload["thematic_groups"] = [
            ThematicNarrative(theme_ref=theme.theme_id, sentences=detail_sentences)
        ]
    narrative = NarrativeSynthesis.model_validate(narrative_payload)
    bundle_payload: dict[str, Any] = {
        "released_claim_refs": released_claim_refs,
        "narrated_claim_refs": released_claim_refs,
        "claim_classifications": classifications,
        "themes": [theme],
        "narrative": narrative,
        "narrative_attestations": attestations,
    }
    if released_insight_refs:
        bundle_payload["insight_refs"] = released_insight_refs
    return NarrativeReleaseBundle.model_validate(bundle_payload)


def verify_deterministic_narrative_release(
    value: NarrativeReleaseBundle | Mapping[str, Any],
    **inputs: Any,
) -> NarrativeReleaseBundle:
    observed = NarrativeReleaseBundle.model_validate(value)
    expected = build_deterministic_narrative_release(**inputs)
    if observed.model_dump(mode="json", exclude_none=True) != expected.model_dump(
        mode="json",
        exclude_none=True,
    ):
        raise ValueError("narrative release differs from deterministic T5 replay")
    return observed


def _build_projection_bridge():
    authority = object()
    minter_taken = False
    minted: WeakKeyDictionary[object, tuple[Any, ...]] = WeakKeyDictionary()

    class ReleasedNarrativeProjection:
        __slots__ = (
            "run_id",
            "source_revision_id",
            "text",
            "sentence_ids",
            "sentence_bindings",
            "content_sha256",
            "attestation_schema_version",
            "producer_id",
            "_sealed",
            "__weakref__",
        )

        def __init__(
            self,
            *,
            run_id: str,
            source_revision_id: str,
            text: str,
            sentence_ids: tuple[str, ...],
            sentence_bindings: tuple[
                tuple[str, str, tuple[str, ...], tuple[str, ...]], ...
            ],
            content_sha256: str,
            attestation_schema_version: str,
            producer_id: str,
            _authority: object,
        ) -> None:
            if _authority is not authority:
                raise TypeError("released narrative projection requires trusted minting")
            object.__setattr__(self, "run_id", run_id)
            object.__setattr__(self, "source_revision_id", source_revision_id)
            object.__setattr__(self, "text", text)
            object.__setattr__(self, "sentence_ids", sentence_ids)
            object.__setattr__(self, "sentence_bindings", sentence_bindings)
            object.__setattr__(self, "content_sha256", content_sha256)
            object.__setattr__(
                self,
                "attestation_schema_version",
                attestation_schema_version,
            )
            object.__setattr__(self, "producer_id", producer_id)
            object.__setattr__(self, "_sealed", True)

        def __setattr__(self, name: str, value: object) -> None:
            if getattr(self, "_sealed", False):
                raise AttributeError("released narrative projection is immutable")
            object.__setattr__(self, name, value)

    def take_minter():
        nonlocal minter_taken
        if minter_taken:
            raise RuntimeError("released narrative projection minter already installed")
        minter_taken = True

        def mint(run: object) -> ReleasedNarrativeProjection:
            projections = getattr(run, "projections", None)
            summary = getattr(projections, "summary", None)
            narrative = getattr(summary, "narrative", None)
            attestations = getattr(summary, "narrative_attestations", None)
            provenance = getattr(run, "provenance", None)
            if narrative is None or not attestations or provenance is None:
                raise TypeError("trusted run is missing released narrative data")
            ordered_sentences = list(narrative.overview)
            for group in narrative.thematic_groups or []:
                ordered_sentences.extend(group.sentences)
            text = "\n".join(sentence.text for sentence in ordered_sentences)
            projection = ReleasedNarrativeProjection(
                run_id=str(getattr(run, "run_id")),
                source_revision_id=provenance.source_revision_id,
                text=text,
                sentence_ids=tuple(sentence.sentence_id for sentence in ordered_sentences),
                sentence_bindings=tuple(
                    (
                        sentence.sentence_id,
                        sentence.sentence_kind,
                        tuple(sentence.claim_refs),
                        tuple(sentence.evidence_refs),
                    )
                    for sentence in ordered_sentences
                ),
                content_sha256=sha256_utf8(text),
                attestation_schema_version=attestations[0].schema_version,
                producer_id=attestations[0].producer_id,
                _authority=authority,
            )
            minted[projection] = (
                projection.run_id,
                projection.source_revision_id,
                projection.text,
                projection.sentence_ids,
                projection.sentence_bindings,
                projection.content_sha256,
                projection.attestation_schema_version,
                projection.producer_id,
            )
            return projection

        return mint

    def require(value: object) -> ReleasedNarrativeProjection:
        if not isinstance(value, ReleasedNarrativeProjection):
            raise TypeError("trusted released narrative projection is required")
        expected = minted.get(value)
        observed = (
            value.run_id,
            value.source_revision_id,
            value.text,
            value.sentence_ids,
            getattr(value, "sentence_bindings", None),
            value.content_sha256,
            value.attestation_schema_version,
            value.producer_id,
        )
        if expected is None or observed != expected:
            raise TypeError("released narrative projection was not minted by T5 authority")
        if sha256_utf8(value.text) != value.content_sha256:
            raise ValueError("released narrative projection content hash mismatch")
        return value

    return ReleasedNarrativeProjection, take_minter, require


(
    ReleasedNarrativeProjection,
    _take_released_narrative_minter,
    _require_released_narrative,
) = _build_projection_bridge()
del _build_projection_bridge


def render_released_narrative_text(value: object) -> str:
    return _require_released_narrative(value).text


def released_narrative_metadata(value: object) -> dict[str, Any]:
    projection = _require_released_narrative(value)
    return {
        "run_id": projection.run_id,
        "source_revision_id": projection.source_revision_id,
        "sentence_ids": list(projection.sentence_ids),
        "sentences": [
            {
                "sentence_id": sentence_id,
                "sentence_kind": sentence_kind,
                "claim_refs": list(claim_refs),
                "evidence_refs": list(evidence_refs),
            }
            for sentence_id, sentence_kind, claim_refs, evidence_refs in (
                projection.sentence_bindings
            )
        ],
        "content_sha256": projection.content_sha256,
        "attestation_schema_version": projection.attestation_schema_version,
        "producer_id": projection.producer_id,
    }


def build_s2_contract_snapshot() -> dict[str, Any]:
    payload = {
        "snapshot_version": "s2-narrative-contract-v2",
        "attestation_schema_version": NARRATIVE_ATTESTATION_VERSION,
        "producer_id": NARRATIVE_PRODUCER_ID,
        "producer_digest": NARRATIVE_PRODUCER_DIGEST,
        "sentence_schema": NarrativeSentence.model_json_schema(),
        "classification_schema": NarrativeClaimClassification.model_json_schema(),
        "attestation_schema": NarrativeAttestationArtifact.model_json_schema(),
        "release_bundle_schema": NarrativeReleaseBundle.model_json_schema(),
        "required_checks": [
            "sentence_semantic_support_100_percent",
            "released_claim_narrative_coverage_100_percent",
            "critical_claim_placement_100_percent",
            "source_assertion_attribution_100_percent",
            "severe_hallucination_zero",
            "hypothesis_leakage_zero",
        ],
    }
    return {**payload, "snapshot_sha256": sha256_canonical_json(payload)}


def verify_s2_contract_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = build_s2_contract_snapshot()
    observed = dict(value)
    if observed != expected:
        raise ValueError("S2 contract snapshot does not match current implementation")
    return observed


__all__ = [
    "NARRATIVE_ATTESTATION_VERSION",
    "NARRATIVE_PRODUCER_DIGEST",
    "NARRATIVE_PRODUCER_ID",
    "NarrativeReleaseBundle",
    "ReleasedNarrativeProjection",
    "build_deterministic_narrative_release",
    "build_s2_contract_snapshot",
    "classify_released_claim",
    "expected_narrative_evidence_refs",
    "expected_narrative_sentence_text",
    "narrative_subject_sha256",
    "released_narrative_metadata",
    "render_released_narrative_text",
    "verify_deterministic_narrative_release",
    "verify_s2_contract_snapshot",
]
