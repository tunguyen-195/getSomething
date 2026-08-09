"""Pure deterministic projector from a released InvestigationRun."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal, NoReturn, cast

from src.services.investigation.contracts import (
    EvidenceSpan,
    GroundedClaim,
    NarrativeSentence,
    sha256_canonical_json,
    sha256_utf8,
)
from src.services.investigation.run_contracts import (
    InvestigationRun,
    _verify_released_run_seal,
)

from .contracts import (
    InvestigationVisualization,
    VISUALIZATION_AUTHORITY,
    VISUALIZATION_SCHEMA_VERSION,
    VisualizationEdge,
    VisualizationEntity,
    VisualizationEvidence,
    VisualizationEvent,
    VisualizationNode,
    VisualizationProjectionError,
    VisualizationTimelineItem,
)


def _reject(code: str, message: str) -> NoReturn:
    raise VisualizationProjectionError(code, message)


def _format_seconds(value: float) -> str:
    milliseconds = round(value * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def _epistemic_type(
    claim_ref: str,
    analysis: object,
) -> Literal["source_attributed", "fact"]:
    source_refs = set(getattr(analysis, "source_attributed_claim_refs", None) or [])
    fact_refs = set(getattr(analysis, "fact_claim_refs", None) or [])
    qualified_refs = set(getattr(analysis, "qualified_claim_refs", None) or [])
    memberships = sum(
        claim_ref in refs for refs in (source_refs, fact_refs, qualified_refs)
    )
    if memberships != 1:
        _reject(
            "VISUALIZATION_RELEASE_GRAPH_INVALID",
            "each released claim must belong to exactly one analysis fact bucket",
        )
    if claim_ref in qualified_refs:
        _reject(
            "VISUALIZATION_UNVERIFIED_CLAIM",
            "qualified or partially supported claims cannot enter visualization",
        )
    return "source_attributed" if claim_ref in source_refs else "fact"


def _ordered_evidence(
    evidence_refs: Iterable[str],
    *,
    evidence_by_id: dict[str, EvidenceSpan],
    source_revision_id: str,
) -> list[VisualizationEvidence]:
    refs = sorted(set(evidence_refs))
    missing = [ref for ref in refs if ref not in evidence_by_id]
    if missing:
        _reject(
            "VISUALIZATION_RELEASE_GRAPH_INVALID",
            f"released visualization has dangling evidence refs: {', '.join(missing)}",
        )
    projected: list[VisualizationEvidence] = []
    for evidence in (evidence_by_id[ref] for ref in refs):
        payload: dict[str, object] = {
            "evidence_id": evidence.evidence_id,
            "segment_id": evidence.segment_id,
            "quote_exact": evidence.quote_exact,
            "quote_sha256": evidence.quote_sha256,
            "source_sha256": evidence.source_sha256,
            "source_revision_id": source_revision_id,
        }
        if evidence.start_seconds is not None:
            payload["start_seconds"] = evidence.start_seconds
            payload["end_seconds"] = evidence.end_seconds
        if evidence.speaker_id is not None:
            payload["speaker_id"] = evidence.speaker_id
        projected.append(VisualizationEvidence.model_validate(payload))
    return projected


def _validate_released_claims(
    run: InvestigationRun,
) -> tuple[list[str], dict[str, GroundedClaim], dict[str, EvidenceSpan]]:
    ledger = run.ledger
    projections = run.projections
    if ledger is None or projections is None:
        _reject(
            "VISUALIZATION_RUN_NOT_RELEASED",
            "a successful released run requires a ledger and projections",
        )

    summary_refs = set(projections.summary.released_claim_refs)
    analysis_refs = set(projections.analysis.released_claim_refs)
    if not summary_refs or summary_refs != analysis_refs:
        _reject(
            "VISUALIZATION_RELEASE_GRAPH_INVALID",
            "Summary and Analysis must expose the same non-empty released claim set",
        )

    claim_by_id = {claim.claim_id: claim for claim in ledger.claims}
    evidence_by_id = {evidence.evidence_id: evidence for evidence in ledger.evidence}
    if len(claim_by_id) != len(ledger.claims) or len(evidence_by_id) != len(
        ledger.evidence
    ):
        _reject(
            "VISUALIZATION_RELEASE_GRAPH_INVALID",
            "claim and evidence IDs must be unique",
        )

    eligible_decisions = [
        decision
        for decision in ledger.verification_decisions
        if decision.canonical_claim_ref is not None
        and decision.projection_eligibility != "withheld"
    ]
    eligible_claim_refs = {
        decision.canonical_claim_ref for decision in eligible_decisions
    }
    if eligible_claim_refs != summary_refs:
        _reject(
            "VISUALIZATION_WITHHELD_CLAIM",
            "visualization refs must equal the verifier-released claim set",
        )

    for claim_ref in sorted(summary_refs):
        claim = claim_by_id.get(claim_ref)
        if claim is None:
            _reject(
                "VISUALIZATION_RELEASE_GRAPH_INVALID",
                f"released claim {claim_ref!r} does not exist in the ledger",
            )
        if (
            claim.epistemic_status != "fact"
            or claim.disposition != "supported"
            or claim.risk_tier == "high_risk"
        ):
            _reject(
                "VISUALIZATION_UNVERIFIED_CLAIM",
                f"claim {claim_ref!r} is not an ordinary supported fact",
            )
        decisions = [
            decision
            for decision in eligible_decisions
            if decision.canonical_claim_ref == claim_ref
        ]
        if not decisions or any(
            decision.evidence_resolution != "resolved"
            or decision.source_revision_id != run.provenance.source_revision_id
            or decision.disposition != "supported"
            for decision in decisions
        ):
            _reject(
                "VISUALIZATION_UNVERIFIED_CLAIM",
                f"claim {claim_ref!r} lacks current-revision resolved verification",
            )
        verified_refs = {
            ref
            for decision in decisions
            for ref in decision.verified_evidence_refs or []
        }
        if not set(claim.evidence_refs).issubset(verified_refs):
            _reject(
                "VISUALIZATION_UNVERIFIED_CLAIM",
                f"claim {claim_ref!r} contains evidence not attested by verification",
            )
        _ordered_evidence(
            claim.evidence_refs,
            evidence_by_id=evidence_by_id,
            source_revision_id=run.provenance.source_revision_id,
        )

    return sorted(summary_refs), claim_by_id, evidence_by_id


def _claim_refs_for_concept(
    concept_ref: str,
    *,
    released_claims: Sequence[GroundedClaim],
) -> list[str]:
    return sorted(
        claim.claim_id
        for claim in released_claims
        if concept_ref in (claim.concept_refs or [])
    )


def _released_display_texts(
    run: InvestigationRun,
    released_refs: Sequence[str],
) -> dict[str, str]:
    assert run.projections is not None
    summary = run.projections.summary
    attestation_by_id = {
        artifact.artifact_id: artifact for artifact in summary.narrative_attestations
    }
    if len(attestation_by_id) != len(summary.narrative_attestations):
        _reject(
            "VISUALIZATION_NARRATIVE_ATTESTATION_INVALID",
            "released narrative attestation IDs must be unique",
        )

    sentences: list[NarrativeSentence] = list(summary.narrative.overview)
    for group in summary.narrative.thematic_groups or []:
        sentences.extend(group.sentences)

    released_set = set(released_refs)
    sentences_by_claim: dict[str, list[NarrativeSentence]] = {
        claim_ref: [] for claim_ref in released_refs
    }
    for sentence in sentences:
        artifact = attestation_by_id.get(sentence.semantic_attestation_ref)
        if artifact is None:
            _reject(
                "VISUALIZATION_NARRATIVE_ATTESTATION_INVALID",
                f"sentence {sentence.sentence_id!r} lacks its public attestation",
            )
        if (
            artifact.sentence_id != sentence.sentence_id
            or artifact.source_revision_id != run.provenance.source_revision_id
            or artifact.content_sha256 != sentence.content_sha256
            or artifact.claim_refs != sentence.claim_refs
            or artifact.evidence_refs != sentence.evidence_refs
            or artifact.decision != "supported"
            or artifact.replay_verified is not True
            or sha256_utf8(sentence.text) != sentence.content_sha256
        ):
            _reject(
                "VISUALIZATION_NARRATIVE_ATTESTATION_INVALID",
                f"sentence {sentence.sentence_id!r} does not match "
                "its public attestation",
            )
        if not set(sentence.claim_refs).issubset(released_set):
            _reject(
                "VISUALIZATION_WITHHELD_CLAIM",
                f"sentence {sentence.sentence_id!r} exposes a non-released claim",
            )
        for claim_ref in sentence.claim_refs:
            sentences_by_claim[claim_ref].append(sentence)

    display_texts: dict[str, str] = {}
    for claim_ref, claim_sentences in sentences_by_claim.items():
        if len(claim_sentences) != 1:
            _reject(
                "VISUALIZATION_NARRATIVE_MAPPING_AMBIGUOUS",
                f"released claim {claim_ref!r} requires exactly one "
                "attested display sentence",
            )
        display_texts[claim_ref] = claim_sentences[0].text
    return display_texts


def project_released_investigation_run(value: object) -> InvestigationVisualization:
    """Project a typed successful run without I/O, inference, or persistence."""

    try:
        _verify_released_run_seal(value)
    except ValueError as exc:
        _reject(
            "VISUALIZATION_RELEASED_RUN_REQUIRED",
            f"visualization requires an authority-sealed InvestigationRun: {exc}",
        )
    run = cast(InvestigationRun, value)
    if run.run_status != "success":
        _reject(
            "VISUALIZATION_RUN_NOT_RELEASED",
            f"run status {run.run_status!r} cannot publish visualization",
        )
    if run.gate_failures:
        _reject(
            "VISUALIZATION_RUN_NOT_RELEASED",
            "a released visualization cannot contain gate failures",
        )

    source_revision_id = run.provenance.source_revision_id
    released_refs, claim_by_id, evidence_by_id = _validate_released_claims(run)
    assert run.ledger is not None
    assert run.projections is not None
    analysis = run.projections.analysis
    released_claims = [claim_by_id[ref] for ref in released_refs]
    display_text_by_claim = _released_display_texts(run, released_refs)

    claim_epistemics = {
        claim_ref: _epistemic_type(claim_ref, analysis) for claim_ref in released_refs
    }
    nodes = [
        VisualizationNode(
            id=claim.claim_id,
            kind="claim",
            label=display_text_by_claim[claim.claim_id],
            type=claim.claim_type,
            epistemic_type=claim_epistemics[claim.claim_id],
            source_revision_id=source_revision_id,
            claim_refs=[claim.claim_id],
            evidence=_ordered_evidence(
                claim.evidence_refs,
                evidence_by_id=evidence_by_id,
                source_revision_id=source_revision_id,
            ),
        )
        for claim in released_claims
    ]

    relationship_by_id = {
        relationship.relationship_id: relationship
        for relationship in run.ledger.relationships or []
    }
    relationship_refs = sorted(analysis.relationship_refs or [])
    missing_relationships = [
        ref for ref in relationship_refs if ref not in relationship_by_id
    ]
    if missing_relationships:
        _reject(
            "VISUALIZATION_RELEASE_GRAPH_INVALID",
            "released visualization has dangling relationship refs: "
            + ", ".join(missing_relationships),
        )

    selected_relationships = [relationship_by_id[ref] for ref in relationship_refs]
    concept_by_id = {
        concept.concept_id: concept for concept in run.ledger.concepts or []
    }
    selected_concept_refs = {
        ref for claim in released_claims for ref in claim.concept_refs or []
    }
    selected_concept_refs.update(
        ref
        for relationship in selected_relationships
        for ref in (relationship.source_ref, relationship.target_ref)
        if ref in concept_by_id
    )

    relationship_evidence_by_concept: dict[str, set[str]] = {}
    for relationship in selected_relationships:
        if (
            relationship.evidence_resolution != "resolved"
            or relationship.source_revision_id != source_revision_id
            or relationship.projection_eligibility == "withheld"
            or relationship.epistemic_status != "fact"
            or relationship.disposition != "supported"
            or relationship.risk_tier == "high_risk"
        ):
            _reject(
                "VISUALIZATION_UNVERIFIED_RELATIONSHIP",
                f"relationship {relationship.relationship_id!r} is not "
                "release-safe for a factual graph",
            )
        for endpoint in (relationship.source_ref, relationship.target_ref):
            if endpoint in claim_by_id and endpoint not in released_refs:
                _reject(
                    "VISUALIZATION_WITHHELD_CLAIM",
                    f"relationship {relationship.relationship_id!r} exposes "
                    f"withheld claim {endpoint!r}",
                )
            if endpoint in concept_by_id:
                relationship_evidence_by_concept.setdefault(endpoint, set()).update(
                    relationship.evidence_refs
                )

    entities: list[VisualizationEntity] = []
    for concept_ref in sorted(selected_concept_refs):
        concept = concept_by_id.get(concept_ref)
        if concept is None:
            _reject(
                "VISUALIZATION_RELEASE_GRAPH_INVALID",
                f"released visualization references missing concept {concept_ref!r}",
            )
        claim_refs = _claim_refs_for_concept(
            concept_ref,
            released_claims=released_claims,
        )
        relationship_refs_for_concept = relationship_evidence_by_concept.get(
            concept_ref, set()
        )
        allowed_evidence_refs = set(relationship_refs_for_concept)
        for claim_ref in claim_refs:
            allowed_evidence_refs.update(claim_by_id[claim_ref].evidence_refs)
        evidence_refs = sorted(set(concept.evidence_refs) & allowed_evidence_refs)
        if not evidence_refs:
            evidence_refs = sorted(allowed_evidence_refs)
        if not claim_refs:
            concept_premise_refs = {
                ref
                for relationship in selected_relationships
                if concept_ref in (relationship.source_ref, relationship.target_ref)
                for ref in relationship.premise_claim_refs or []
            }
            claim_refs = sorted(concept_premise_refs)
        if not claim_refs or not evidence_refs:
            _reject(
                "VISUALIZATION_RELEASE_GRAPH_INVALID",
                f"concept {concept_ref!r} lacks released claim and evidence authority",
            )
        evidence = _ordered_evidence(
            evidence_refs,
            evidence_by_id=evidence_by_id,
            source_revision_id=source_revision_id,
        )
        node_payload: dict[str, object] = {
            "id": concept.concept_id,
            "kind": "concept",
            "label": concept.surface,
            "type": concept.concept_type,
            "epistemic_type": "source_attributed",
            "source_revision_id": source_revision_id,
            "claim_refs": claim_refs,
            "evidence": evidence,
        }
        entity_payload: dict[str, object] = {
            "id": concept.concept_id,
            "type": concept.concept_type,
            "value": concept.surface,
            "source_revision_id": source_revision_id,
            "claim_refs": claim_refs,
            "evidence": evidence,
        }
        if concept.role is not None:
            node_payload["role"] = concept.role
            entity_payload["context"] = concept.role
        nodes.append(VisualizationNode.model_validate(node_payload))
        entities.append(VisualizationEntity.model_validate(entity_payload))

    node_ids = {node.id for node in nodes}
    edges: list[VisualizationEdge] = []
    for relationship in selected_relationships:
        if (
            relationship.source_ref not in node_ids
            or relationship.target_ref not in node_ids
        ):
            _reject(
                "VISUALIZATION_RELEASE_GRAPH_INVALID",
                f"relationship {relationship.relationship_id!r} has "
                "an unprojected endpoint",
            )
        edge_claim_refs: list[str] = sorted(set(relationship.premise_claim_refs or []))
        if not edge_claim_refs:
            edge_claim_refs = sorted(
                ref
                for ref in (relationship.source_ref, relationship.target_ref)
                if ref in released_refs
            )
        if not edge_claim_refs:
            _reject(
                "VISUALIZATION_RELEASE_GRAPH_INVALID",
                f"relationship {relationship.relationship_id!r} lacks "
                "released claim authority",
            )
        if not set(edge_claim_refs).issubset(released_refs):
            _reject(
                "VISUALIZATION_WITHHELD_CLAIM",
                f"relationship {relationship.relationship_id!r} depends "
                "on a withheld claim",
            )
        edge_epistemics = {claim_epistemics[ref] for ref in edge_claim_refs}
        epistemic_type: Literal["source_attributed", "fact"] = (
            "fact" if edge_epistemics == {"fact"} else "source_attributed"
        )
        edges.append(
            VisualizationEdge(
                id=relationship.relationship_id,
                source=relationship.source_ref,
                target=relationship.target_ref,
                label=relationship.relationship_type,
                type=relationship.relationship_type,
                epistemic_type=epistemic_type,
                source_revision_id=source_revision_id,
                claim_refs=edge_claim_refs,
                evidence=_ordered_evidence(
                    relationship.evidence_refs,
                    evidence_by_id=evidence_by_id,
                    source_revision_id=source_revision_id,
                ),
            )
        )

    timeline: list[VisualizationTimelineItem] = []
    main_events: list[VisualizationEvent] = []
    for claim in released_claims:
        evidence = _ordered_evidence(
            claim.evidence_refs,
            evidence_by_id=evidence_by_id,
            source_revision_id=source_revision_id,
        )
        main_events.append(
            VisualizationEvent(
                id=claim.claim_id,
                event=display_text_by_claim[claim.claim_id],
                type=claim.claim_type,
                claim_ref=claim.claim_id,
                epistemic_type=claim_epistemics[claim.claim_id],
                source_revision_id=source_revision_id,
                evidence=evidence,
            )
        )
        for span in evidence:
            if span.start_seconds is None or span.end_seconds is None:
                continue
            timeline.append(
                VisualizationTimelineItem(
                    id=f"{claim.claim_id}:{span.evidence_id}",
                    time=(
                        f"{_format_seconds(span.start_seconds)}-"
                        f"{_format_seconds(span.end_seconds)}"
                    ),
                    event=display_text_by_claim[claim.claim_id],
                    claim_ref=claim.claim_id,
                    epistemic_type=claim_epistemics[claim.claim_id],
                    source_revision_id=source_revision_id,
                    start_seconds=span.start_seconds,
                    end_seconds=span.end_seconds,
                    evidence=[span],
                )
            )

    nodes.sort(key=lambda item: (item.kind, item.id))
    edges.sort(key=lambda item: item.id)
    timeline.sort(
        key=lambda item: (
            item.start_seconds,
            item.end_seconds,
            item.claim_ref,
            item.id,
        )
    )
    main_events.sort(key=lambda item: item.id)
    entities.sort(key=lambda item: (item.type, item.value.casefold(), item.id))

    payload = {
        "schema_version": VISUALIZATION_SCHEMA_VERSION,
        "authority": VISUALIZATION_AUTHORITY,
        "run_id": run.run_id,
        "source_revision_id": source_revision_id,
        "release_subject_sha256": sha256_canonical_json(
            run.model_dump(mode="json", exclude_none=True)
        ),
        "nodes": [item.model_dump(mode="json", exclude_none=True) for item in nodes],
        "edges": [item.model_dump(mode="json", exclude_none=True) for item in edges],
        "timeline": [
            item.model_dump(mode="json", exclude_none=True) for item in timeline
        ],
        "main_events": [
            item.model_dump(mode="json", exclude_none=True) for item in main_events
        ],
        "extracted_entities": [
            item.model_dump(mode="json", exclude_none=True) for item in entities
        ],
    }
    return InvestigationVisualization.model_validate(
        {**payload, "content_hash": sha256_canonical_json(payload)}
    )


__all__ = ["project_released_investigation_run"]
