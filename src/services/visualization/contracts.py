"""Strict artifact contract for released InvestigationRun visualizations."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from src.services.investigation.contracts import (
    Sha256Hex,
    StrictEnvelope,
    _ensure_unique,
    sha256_canonical_json,
    sha256_utf8,
)

VISUALIZATION_SCHEMA_VERSION: Literal[
    "investigation-visualization-v1"
] = "investigation-visualization-v1"
VISUALIZATION_AUTHORITY: Literal[
    "released_investigation_run"
] = "released_investigation_run"


class VisualizationProjectionError(ValueError):
    """Stable fail-closed error raised before any visualization is returned."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class VisualizationEvidence(StrictEnvelope):
    evidence_id: str = Field(min_length=1)
    segment_id: str = Field(min_length=1)
    quote_exact: str = Field(min_length=1)
    quote_sha256: Sha256Hex = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: Sha256Hex = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision_id: str = Field(min_length=1)
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    speaker_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_time_bounds(self) -> "VisualizationEvidence":
        if self.quote_sha256 != sha256_utf8(self.quote_exact):
            raise ValueError("quote_sha256 must match quote_exact UTF-8 bytes")
        if (self.start_seconds is None) != (self.end_seconds is None):
            raise ValueError("evidence timestamps must include both start and end")
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds <= self.start_seconds
        ):
            raise ValueError(
                "evidence end_seconds cannot precede or equal start_seconds"
            )
        return self


class VisualizationNode(StrictEnvelope):
    id: str = Field(min_length=1)
    kind: Literal["claim", "concept"]
    label: str = Field(min_length=1)
    type: str = Field(min_length=1)
    epistemic_type: Literal["source_attributed", "fact"]
    source_revision_id: str = Field(min_length=1)
    claim_refs: list[str] = Field(min_length=1)
    evidence: list[VisualizationEvidence] = Field(min_length=1)
    role: str | None = Field(default=None, min_length=1)

    @field_validator("claim_refs")
    @classmethod
    def unique_claim_refs(cls, values: list[str]) -> list[str]:
        return _ensure_unique(values, "visualization node claim refs")

    @model_validator(mode="after")
    def unique_evidence_refs(self) -> "VisualizationNode":
        _ensure_unique(
            [item.evidence_id for item in self.evidence],
            "visualization node evidence refs",
        )
        if self.kind == "claim" and self.claim_refs != [self.id]:
            raise ValueError("claim nodes must bind exactly their own claim ID")
        return self


class VisualizationEdge(StrictEnvelope):
    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    label: str = Field(min_length=1)
    type: str = Field(min_length=1)
    epistemic_type: Literal["source_attributed", "fact"]
    source_revision_id: str = Field(min_length=1)
    claim_refs: list[str] = Field(min_length=1)
    evidence: list[VisualizationEvidence] = Field(min_length=1)

    @field_validator("claim_refs")
    @classmethod
    def unique_claim_refs(cls, values: list[str]) -> list[str]:
        return _ensure_unique(values, "visualization edge claim refs")

    @model_validator(mode="after")
    def unique_evidence_refs(self) -> "VisualizationEdge":
        _ensure_unique(
            [item.evidence_id for item in self.evidence],
            "visualization edge evidence refs",
        )
        return self


class VisualizationTimelineItem(StrictEnvelope):
    id: str = Field(min_length=1)
    time: str = Field(min_length=1)
    event: str = Field(min_length=1)
    claim_ref: str = Field(min_length=1)
    epistemic_type: Literal["source_attributed", "fact"]
    source_revision_id: str = Field(min_length=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    evidence: list[VisualizationEvidence] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def validate_time_bounds(self) -> "VisualizationTimelineItem":
        if self.end_seconds < self.start_seconds:
            raise ValueError("timeline end_seconds cannot precede start_seconds")
        return self


class VisualizationEvent(StrictEnvelope):
    id: str = Field(min_length=1)
    event: str = Field(min_length=1)
    type: str = Field(min_length=1)
    claim_ref: str = Field(min_length=1)
    epistemic_type: Literal["source_attributed", "fact"]
    source_revision_id: str = Field(min_length=1)
    evidence: list[VisualizationEvidence] = Field(min_length=1)


class VisualizationEntity(StrictEnvelope):
    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    value: str = Field(min_length=1)
    source_revision_id: str = Field(min_length=1)
    claim_refs: list[str] = Field(min_length=1)
    evidence: list[VisualizationEvidence] = Field(min_length=1)
    context: str | None = Field(default=None, min_length=1)

    @field_validator("claim_refs")
    @classmethod
    def unique_claim_refs(cls, values: list[str]) -> list[str]:
        return _ensure_unique(values, "visualization entity claim refs")

    @model_validator(mode="after")
    def unique_evidence_refs(self) -> "VisualizationEntity":
        _ensure_unique(
            [item.evidence_id for item in self.evidence],
            "visualization entity evidence refs",
        )
        return self


class InvestigationVisualization(StrictEnvelope):
    """Hash-bound, strict visualization artifact with no persistence semantics."""

    schema_version: Literal[
        "investigation-visualization-v1"
    ] = VISUALIZATION_SCHEMA_VERSION
    authority: Literal["released_investigation_run"] = VISUALIZATION_AUTHORITY
    run_id: str = Field(min_length=1)
    source_revision_id: str = Field(min_length=1)
    release_subject_sha256: Sha256Hex = Field(pattern=r"^[0-9a-f]{64}$")
    content_hash: Sha256Hex = Field(pattern=r"^[0-9a-f]{64}$")
    nodes: list[VisualizationNode]
    edges: list[VisualizationEdge]
    timeline: list[VisualizationTimelineItem]
    main_events: list[VisualizationEvent]
    extracted_entities: list[VisualizationEntity]

    @classmethod
    def _allowed_sparse_empty_paths(cls, value: object) -> frozenset[tuple[str, ...]]:
        return frozenset(
            {
                ("nodes",),
                ("edges",),
                ("timeline",),
                ("main_events",),
                ("extracted_entities",),
            }
        )

    @model_validator(mode="after")
    def validate_content_hash(self) -> "InvestigationVisualization":
        payload = self.model_dump(
            mode="json",
            exclude={"content_hash"},
            exclude_none=True,
        )
        if self.content_hash != sha256_canonical_json(payload):
            raise ValueError("content_hash must bind the canonical visualization")
        collections = {
            "node": self.nodes,
            "edge": self.edges,
            "timeline": self.timeline,
            "event": self.main_events,
            "entity": self.extracted_entities,
        }
        for label, items in collections.items():
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"visualization {label} IDs must be unique")

        if self.nodes != sorted(self.nodes, key=lambda item: (item.kind, item.id)):
            raise ValueError("visualization nodes must use canonical sorted order")
        if self.edges != sorted(self.edges, key=lambda item: item.id):
            raise ValueError("visualization edges must use canonical sorted order")
        if self.timeline != sorted(
            self.timeline,
            key=lambda item: (
                item.start_seconds,
                item.end_seconds,
                item.claim_ref,
                item.id,
            ),
        ):
            raise ValueError("visualization timeline must use canonical sorted order")
        if self.main_events != sorted(self.main_events, key=lambda item: item.id):
            raise ValueError("visualization events must use canonical sorted order")
        if self.extracted_entities != sorted(
            self.extracted_entities,
            key=lambda item: (item.type, item.value.casefold(), item.id),
        ):
            raise ValueError("visualization entities must use canonical sorted order")

        node_ids = {node.id for node in self.nodes}
        for edge in self.edges:
            if edge.source not in node_ids or edge.target not in node_ids:
                raise ValueError("visualization edge endpoints must resolve to nodes")

        claim_refs = {
            claim_ref for node in self.nodes for claim_ref in node.claim_refs
        }
        nested_claim_refs = {
            claim_ref
            for item in [*self.edges, *self.extracted_entities]
            for claim_ref in item.claim_refs
        }
        nested_claim_refs.update(item.claim_ref for item in self.timeline)
        nested_claim_refs.update(item.claim_ref for item in self.main_events)
        missing_claim_refs = sorted(nested_claim_refs - claim_refs)
        if missing_claim_refs:
            raise ValueError(
                "visualization contains dangling claim refs: "
                + ", ".join(missing_claim_refs)
            )

        evidence_payload_by_id: dict[str, dict[str, object]] = {}
        revision_values = {self.source_revision_id}
        revision_values.update(node.source_revision_id for node in self.nodes)
        revision_values.update(edge.source_revision_id for edge in self.edges)
        revision_values.update(item.source_revision_id for item in self.timeline)
        revision_values.update(item.source_revision_id for item in self.main_events)
        revision_values.update(
            item.source_revision_id for item in self.extracted_entities
        )
        all_evidence = [
            evidence
            for item in [
                *self.nodes,
                *self.edges,
                *self.timeline,
                *self.main_events,
                *self.extracted_entities,
            ]
            for evidence in item.evidence
        ]
        revision_values.update(item.source_revision_id for item in all_evidence)
        if revision_values != {self.source_revision_id}:
            raise ValueError(
                "all visualization items must match the top-level source revision"
            )
        for evidence in all_evidence:
            payload = evidence.model_dump(mode="json", exclude_none=True)
            existing = evidence_payload_by_id.get(evidence.evidence_id)
            if existing is not None and existing != payload:
                raise ValueError(
                    "reused visualization evidence IDs must have identical payloads"
                )
            evidence_payload_by_id[evidence.evidence_id] = payload
        return self


__all__ = [
    "InvestigationVisualization",
    "VISUALIZATION_AUTHORITY",
    "VISUALIZATION_SCHEMA_VERSION",
    "VisualizationEdge",
    "VisualizationEntity",
    "VisualizationEvidence",
    "VisualizationEvent",
    "VisualizationNode",
    "VisualizationProjectionError",
    "VisualizationTimelineItem",
]
