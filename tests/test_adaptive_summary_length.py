from __future__ import annotations

import pytest

from src.services.summarization.adaptive_length import (
    adaptive_compression_ratio,
    resolve_summary_length_budget,
)
from src.services.summarization.investigation_scenarios import (
    resolve_investigation_scenario,
)


@pytest.mark.parametrize(
    ("words", "ratio"),
    [(47, 0.35), (600, 0.35), (601, 0.25), (2_001, 0.18), (6_001, 0.12)],
)
def test_adaptive_ratio_uses_source_size_bands(words: int, ratio: float) -> None:
    assert adaptive_compression_ratio(words) == ratio


def test_short_sparse_audio_is_not_forced_to_120_or_300_words() -> None:
    budget = resolve_summary_length_budget(
        mode="auto",
        source_word_count=47,
        requested_min_words=120,
        requested_max_words=400,
        coverage_estimated_words=20,
    )

    assert budget.preferred_words == 22
    assert budget.effective_max_words == 28
    assert budget.as_dict(actual_words=24)["status"] == "expanded_for_coverage"


def test_information_dense_source_gets_larger_budget_at_same_length() -> None:
    sparse = resolve_summary_length_budget(
        mode="auto",
        source_word_count=800,
        requested_min_words=120,
        requested_max_words=400,
        coverage_estimated_words=100,
    )
    dense = resolve_summary_length_budget(
        mode="auto",
        source_word_count=800,
        requested_min_words=120,
        requested_max_words=400,
        coverage_estimated_words=260,
    )

    assert dense.preferred_words > sparse.preferred_words
    assert dense.effective_max_words > sparse.effective_max_words


def test_manual_mode_preserves_explicit_cap() -> None:
    budget = resolve_summary_length_budget(
        mode="manual",
        source_word_count=800,
        requested_min_words=120,
        requested_max_words=400,
        coverage_estimated_words=260,
    )

    assert budget.preferred_words == 120
    assert budget.effective_max_words == 400
    assert budget.as_dict(actual_words=401)["status"] == "maximum_exceeded"


def test_colloquial_vay_diacritic_does_not_select_financial_scenario() -> None:
    assert resolve_investigation_scenario(
        "auto",
        "Đau thằng cha bé á. Ủa vậy hả?",
    ) == "general"
    assert resolve_investigation_scenario(
        "auto",
        "Người tham gia nói sẽ vay tiền và còn khoản nợ.",
    ) == "financial_asset"
