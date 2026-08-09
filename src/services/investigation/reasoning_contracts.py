"""Typed bounded-reasoning outputs for investigative intelligence."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from .contracts import (
    CounterevidenceStatus,
    DerivationType,
    RiskTier,
    StrictEnvelope,
    _ensure_unique,
)


class EvidenceBackedInsight(StrictEnvelope):
    """Replayable synthesis derived only from released supported fact premises."""

    insight_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    derivation_type: DerivationType
    scope: Literal["single_source"] = "single_source"
    premise_claim_refs: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    counterevidence_status: CounterevidenceStatus
    counterevidence_claim_refs: list[str] | None = None
    risk_tier: RiskTier
    risk_screening_artifact_ref: str = Field(min_length=1)
    projection_eligibility: Literal["factual", "withheld"]
    eligibility_artifact_ref: str = Field(min_length=1)
    requires_human_verification: Literal[False] = False
    attributes: dict[str, JsonValue] | None = None

    @field_validator(
        "premise_claim_refs",
        "evidence_refs",
        "counterevidence_claim_refs",
    )
    @classmethod
    def unique_insight_refs(
        cls,
        values: list[str] | None,
    ) -> list[str] | None:
        if values is None:
            return None
        return _ensure_unique(values, "insight references")

    @model_validator(mode="after")
    def validate_counterevidence_and_risk(self) -> "EvidenceBackedInsight":
        has_counterevidence = bool(self.counterevidence_claim_refs)
        if self.counterevidence_status == "present" and not has_counterevidence:
            raise ValueError("present counterevidence requires claim refs")
        if self.counterevidence_status == "none_found" and has_counterevidence:
            raise ValueError("none_found counterevidence cannot include claim refs")
        if set(self.premise_claim_refs) & set(self.counterevidence_claim_refs or []):
            raise ValueError(
                "insight premise and counterevidence refs must be disjoint"
            )
        if self.risk_tier == "high_risk":
            raise ValueError("high-risk reasoning must remain a hypothesis")
        return self


class Hypothesis(StrictEnvelope):
    """Abductive possibility kept separate from factual narrative."""

    hypothesis_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    premise_claim_refs: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    alternative_explanations: list[str] = Field(min_length=1)
    counterevidence_status: CounterevidenceStatus
    counterevidence_claim_refs: list[str] | None = None
    uncertainty_reason: str = Field(min_length=1)
    risk_tier: RiskTier
    risk_screening_artifact_ref: str = Field(min_length=1)
    projection_eligibility: Literal["non_factual", "withheld"]
    eligibility_artifact_ref: str = Field(min_length=1)
    requires_human_verification: Literal[True]
    attributes: dict[str, JsonValue] | None = None

    @field_validator(
        "premise_claim_refs",
        "evidence_refs",
        "alternative_explanations",
        "counterevidence_claim_refs",
    )
    @classmethod
    def unique_hypothesis_values(
        cls,
        values: list[str] | None,
    ) -> list[str] | None:
        if values is None:
            return None
        return _ensure_unique(values, "hypothesis values")

    @model_validator(mode="after")
    def validate_counterevidence(self) -> "Hypothesis":
        has_counterevidence = bool(self.counterevidence_claim_refs)
        if self.counterevidence_status == "present" and not has_counterevidence:
            raise ValueError("present counterevidence requires claim refs")
        if self.counterevidence_status == "none_found" and has_counterevidence:
            raise ValueError("none_found counterevidence cannot include claim refs")
        if set(self.premise_claim_refs) & set(self.counterevidence_claim_refs or []):
            raise ValueError(
                "hypothesis premise and counterevidence refs must be disjoint"
            )
        return self


class VerificationAction(StrictEnvelope):
    """Concrete investigative follow-up with falsifiable promotion criteria."""

    action_id: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    linked_claim_refs: list[str] | None = None
    linked_hypothesis_refs: list[str] | None = None
    linked_concept_refs: list[str] | None = None
    evidence_refs: list[str] = Field(min_length=1)
    required_source_type: str = Field(min_length=1)
    question: str = Field(min_length=1)
    promotion_criterion: str = Field(min_length=1)
    rejection_criterion: str = Field(min_length=1)
    projection_eligibility: Literal["non_factual", "withheld"]
    eligibility_artifact_ref: str = Field(min_length=1)
    requires_human_verification: Literal[True]
    attributes: dict[str, JsonValue] | None = None

    @field_validator(
        "linked_claim_refs",
        "linked_hypothesis_refs",
        "linked_concept_refs",
        "evidence_refs",
    )
    @classmethod
    def unique_action_refs(
        cls,
        values: list[str] | None,
    ) -> list[str] | None:
        if values is None:
            return None
        return _ensure_unique(values, "verification action references")

    @model_validator(mode="after")
    def require_linked_subject(self) -> "VerificationAction":
        if (
            not self.linked_claim_refs
            and not self.linked_hypothesis_refs
            and not self.linked_concept_refs
        ):
            raise ValueError(
                "verification actions require a linked claim, hypothesis, or concept"
            )
        linked_refs = (
            set(self.linked_claim_refs or [])
            | set(self.linked_hypothesis_refs or [])
            | set(self.linked_concept_refs or [])
        )
        if self.target_ref not in linked_refs:
            raise ValueError("verification action target_ref must be explicitly linked")
        return self


__all__ = ["EvidenceBackedInsight", "Hypothesis", "VerificationAction"]
