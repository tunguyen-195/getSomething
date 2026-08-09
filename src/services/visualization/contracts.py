"""Strict artifact contract for released InvestigationRun visualizations."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from src.services.investigation.contracts import (
    Sha256Hex,
    StrictEnvelope,
    sha256_canonical_json,
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
        if (self.start_seconds is None) != (self.end_seconds is None):
            raise ValueError("evidence timestamps must include both start and end")
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds < self.start_seconds
        ):
            raise ValueError("evidence end_seconds cannot precede start_seconds")
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
