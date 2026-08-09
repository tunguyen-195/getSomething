"""Canonical evidence-grounded investigation domain with lazy public exports."""

from __future__ import annotations

import importlib
from typing import Any

_SOURCE_EXPORTS = frozenset(
    {
        "NORMALIZATION_VERSION",
        "OFFSET_UNIT",
        "SOURCE_REVISION_VERSION",
        "UNICODE_DATA_VERSION",
        "NormalizedCharSpan",
        "NormalizedTranscriptMap",
        "SourceRevision",
        "SourceRevisionError",
        "SourceScope",
        "SourceSegment",
        "SourceSegmentDraft",
        "build_source_revision",
        "normalize_transcript",
        "normalize_transcript_with_mapping",
        "source_revision_canonical_json",
    }
)
_SELECTOR_EXPORTS = frozenset(
    {
        "EVIDENCE_SELECTOR_ARTIFACT_VERSION",
        "EVIDENCE_SELECTOR_VERSION",
        "SELECTOR_CONTEXT_CHARS",
        "EvidenceSelector",
        "EvidenceSelectorArtifact",
        "EvidenceSelectorError",
        "EvidenceSelectorRequest",
        "EvidenceSelectorResolver",
        "VerifiedEvidenceSelectorArtifact",
        "build_evidence_selector_artifact",
        "selector_artifact_sha256",
        "verify_evidence_selector_artifact",
    }
)
_RUN_EXPORTS = frozenset()


def __getattr__(name: str) -> Any:
    if name in _SOURCE_EXPORTS:
        module = importlib.import_module(".source_revision", __name__)
    elif name in _SELECTOR_EXPORTS:
        module = importlib.import_module(".evidence_selector", __name__)
    elif name in _RUN_EXPORTS:
        module = importlib.import_module(".run_contracts", __name__)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | _SOURCE_EXPORTS | _SELECTOR_EXPORTS | _RUN_EXPORTS)


__all__ = sorted(_SOURCE_EXPORTS | _SELECTOR_EXPORTS | _RUN_EXPORTS)
