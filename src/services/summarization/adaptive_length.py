"""Adaptive word-budget policy for evidence-grounded summaries."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal


SummaryLengthMode = Literal["auto", "manual"]


def adaptive_compression_ratio(source_word_count: int) -> float:
    """Return the benchmark candidate ratio for the source-size band."""

    if source_word_count < 0:
        raise ValueError("source_word_count must be non-negative")
    if source_word_count <= 600:
        return 0.35
    if source_word_count <= 2_000:
        return 0.25
    if source_word_count <= 6_000:
        return 0.18
    return 0.12


@dataclass(frozen=True)
class ResolvedSummaryLengthBudget:
    """Auditable separation of readability target and coverage capacity."""

    mode: SummaryLengthMode
    source_word_count: int
    requested_min_words: int
    requested_max_words: int
    proportional_ratio: float | None
    proportional_words: int | None
    coverage_estimated_words: int
    preferred_words: int
    initial_hard_guard_words: int
    effective_max_words: int
    strategy: Literal["single_pass", "hierarchical"]

    def as_dict(self, *, actual_words: int | None = None) -> dict[str, object]:
        auto_expanded = (
            self.mode == "auto"
            and actual_words is not None
            and actual_words > self.preferred_words
        )
        if actual_words is None:
            length_status = "pending"
        elif self.mode == "auto" and auto_expanded:
            length_status = "expanded_for_coverage"
        elif self.mode == "auto":
            length_status = "within_adaptive_target"
        elif actual_words > self.effective_max_words:
            length_status = "maximum_exceeded"
        elif actual_words < self.preferred_words:
            length_status = "below_advisory_minimum"
        else:
            length_status = "within_requested_range"
        return {
            "schema_version": "summary-length-contract-v2",
            "unit": "whitespace_delimited_words",
            "mode": self.mode,
            "source_word_count": self.source_word_count,
            "requested_minimum": self.requested_min_words,
            "requested_maximum": self.requested_max_words,
            "proportional_ratio": self.proportional_ratio,
            "proportional_words": self.proportional_words,
            "coverage_estimated_words": self.coverage_estimated_words,
            "preferred_words": self.preferred_words,
            "initial_hard_guard_words": self.initial_hard_guard_words,
            "effective_maximum": self.effective_max_words,
            "strategy": self.strategy,
            "actual": actual_words,
            "compression_ratio": (
                round(actual_words / self.source_word_count, 6)
                if actual_words is not None and self.source_word_count > 0
                else None
            ),
            "auto_expanded": auto_expanded,
            "expansion_reason": "required_evidence_coverage" if auto_expanded else None,
            "minimum": self.preferred_words,
            "maximum": self.effective_max_words,
            "minimum_met": (
                actual_words >= self.preferred_words
                if actual_words is not None
                else None
            ),
            "maximum_met": (
                actual_words <= self.effective_max_words
                if actual_words is not None
                else None
            ),
            "minimum_enforced": False,
            "maximum_enforced": self.mode == "manual",
            "satisfied": (
                self.mode == "auto" or actual_words <= self.effective_max_words
                if actual_words is not None
                else None
            ),
            "status": length_status,
        }


def resolve_summary_length_budget(
    *,
    mode: SummaryLengthMode,
    source_word_count: int,
    requested_min_words: int,
    requested_max_words: int,
    coverage_estimated_words: int,
    hierarchical_threshold_words: int = 640,
) -> ResolvedSummaryLengthBudget:
    """Resolve a manual cap or an evidence-aware adaptive initial guard."""

    if source_word_count < 0 or coverage_estimated_words < 1:
        raise ValueError("adaptive summary inputs must be positive")
    if mode == "manual":
        return ResolvedSummaryLengthBudget(
            mode=mode,
            source_word_count=source_word_count,
            requested_min_words=requested_min_words,
            requested_max_words=requested_max_words,
            proportional_ratio=None,
            proportional_words=None,
            coverage_estimated_words=coverage_estimated_words,
            preferred_words=requested_min_words,
            initial_hard_guard_words=requested_max_words,
            effective_max_words=requested_max_words,
            strategy=(
                "hierarchical"
                if requested_max_words > hierarchical_threshold_words
                else "single_pass"
            ),
        )

    ratio = adaptive_compression_ratio(source_word_count)
    proportional_words = max(1, math.ceil(source_word_count * ratio))
    preferred_words = max(
        20,
        proportional_words,
        math.ceil(coverage_estimated_words * 1.10),
    )
    initial_guard = max(
        preferred_words,
        math.ceil(preferred_words * 1.25),
        math.ceil(coverage_estimated_words * 1.35),
    )
    return ResolvedSummaryLengthBudget(
        mode=mode,
        source_word_count=source_word_count,
        requested_min_words=requested_min_words,
        requested_max_words=requested_max_words,
        proportional_ratio=ratio,
        proportional_words=proportional_words,
        coverage_estimated_words=coverage_estimated_words,
        preferred_words=preferred_words,
        initial_hard_guard_words=initial_guard,
        effective_max_words=initial_guard,
        strategy=(
            "hierarchical"
            if initial_guard > hierarchical_threshold_words
            else "single_pass"
        ),
    )


__all__ = [
    "ResolvedSummaryLengthBudget",
    "SummaryLengthMode",
    "adaptive_compression_ratio",
    "resolve_summary_length_budget",
]
