"""Deterministic transcript evidence selectors bound to immutable revisions."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from .contracts import EvidenceSpan, sha256_canonical_json, sha256_utf8
from .source_revision import (
    ImmutableArtifact,
    NormalizedTranscriptMap,
    OFFSET_UNIT,
    SourceRevision,
    SourceRevisionError,
    SourceScope,
    SourceSegment,
    normalize_transcript,
    normalize_transcript_with_mapping,
    _revalidate_source_revision,
)

EVIDENCE_SELECTOR_VERSION: Literal[
    "transcript-evidence-selector-v1.0"
] = "transcript-evidence-selector-v1.0"
EVIDENCE_SELECTOR_ARTIFACT_VERSION: Literal[
    "transcript-evidence-selector-artifact-v1.0"
] = "transcript-evidence-selector-artifact-v1.0"
SELECTOR_CONTEXT_CHARS: Literal[32] = 32


class EvidenceSelectorError(ValueError):
    """Raised when an evidence selector is ambiguous or cannot be replayed."""


class EvidenceSelectorRequest(ImmutableArtifact):
    evidence_id: str = Field(min_length=1)
    scope: SourceScope
    source_revision_id: str = Field(min_length=1)
    quote_exact: str = Field(min_length=1)
    segment_id: str | None = Field(default=None, min_length=1)
    prefix: str | None = None
    suffix: str | None = None
    occurrence_index: int | None = Field(default=None, ge=0)

    @field_validator("evidence_id", "source_revision_id")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("selector request IDs must be non-blank")
        return value

    @field_validator("quote_exact")
    @classmethod
    def validate_quote(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("quote_exact must be non-blank")
        if value != value.strip():
            raise ValueError("quote_exact cannot have leading or trailing whitespace")
        return value

    @field_validator("prefix", "suffix")
    @classmethod
    def validate_optional_context(cls, value: str | None) -> str | None:
        if value is not None and not value:
            raise ValueError("explicit selector context cannot be empty")
        return value


class EvidenceSelector(ImmutableArtifact):
    selector_version: Literal[
        "transcript-evidence-selector-v1.0"
    ] = EVIDENCE_SELECTOR_VERSION
    selector_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    scope: SourceScope
    source_revision_id: str = Field(min_length=1)
    source_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_transcript_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    segment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    segment_id: str = Field(min_length=1)
    quote_exact: str = Field(min_length=1)
    quote_normalized: str = Field(min_length=1)
    quote_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_quote_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_char_start: int = Field(ge=0)
    raw_char_end: int = Field(gt=0)
    normalized_char_start: int = Field(ge=0)
    normalized_char_end: int = Field(gt=0)
    offset_unit: Literal["unicode_code_point"] = OFFSET_UNIT
    prefix: str
    suffix: str
    context_window_chars: Literal[32] = SELECTOR_CONTEXT_CHARS
    occurrence_index: int = Field(ge=0)
    speaker_id: str | None = Field(default=None, min_length=1)
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    network_required: Literal[False] = False
    grounding_basis: Literal["transcript_only"] = "transcript_only"
    audio_grounded: Literal[False] = False

    @field_validator(
        "selector_id",
        "evidence_id",
        "source_revision_id",
        "segment_id",
    )
    @classmethod
    def validate_non_blank_ids(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("selector IDs must be non-blank")
        return value

    @model_validator(mode="after")
    def validate_self_hashes(self) -> "EvidenceSelector":
        if self.raw_char_end <= self.raw_char_start:
            raise ValueError("selector raw range must be increasing")
        if self.normalized_char_end <= self.normalized_char_start:
            raise ValueError("selector normalized range must be increasing")
        if (self.start_seconds is None) != (self.end_seconds is None):
            raise ValueError("selector timestamps must be provided together")
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds <= self.start_seconds
        ):
            raise ValueError("selector timestamp range must be increasing")
        if self.quote_sha256 != sha256_utf8(self.quote_exact):
            raise ValueError("selector quote_sha256 mismatch")
        if self.normalized_quote_sha256 != sha256_utf8(self.quote_normalized):
            raise ValueError("selector normalized_quote_sha256 mismatch")
        if self.source_sha256 != self.segment_sha256:
            raise ValueError("EvidenceSpan source_sha256 must equal segment_sha256")
        if self.selector_id != _selector_id(self):
            raise ValueError("selector_id is not canonical")
        return self

    def to_evidence_span(self) -> EvidenceSpan:
        """Project the verified transcript selector into the T1 evidence shape."""

        selector = EvidenceSelector.model_validate_json(self.model_dump_json())
        payload: dict[str, Any] = {
            "evidence_id": selector.evidence_id,
            "segment_id": selector.segment_id,
            "quote_exact": selector.quote_exact,
            "raw_char_start": selector.raw_char_start,
            "raw_char_end": selector.raw_char_end,
            "quote_sha256": selector.quote_sha256,
            "source_sha256": selector.segment_sha256,
        }
        if selector.prefix:
            payload["quote_prefix"] = selector.prefix
        if selector.suffix:
            payload["quote_suffix"] = selector.suffix
        if selector.start_seconds is not None:
            payload["start_seconds"] = selector.start_seconds
            payload["end_seconds"] = selector.end_seconds
        if selector.speaker_id is not None:
            payload["speaker_id"] = selector.speaker_id
        return EvidenceSpan.model_validate(payload)


class EvidenceSelectorArtifact(ImmutableArtifact):
    artifact_version: Literal[
        "transcript-evidence-selector-artifact-v1.0"
    ] = EVIDENCE_SELECTOR_ARTIFACT_VERSION
    artifact_id: str = Field(min_length=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    subject_kind: Literal["verification", "relationship"]
    subject_ref: str = Field(min_length=1)
    scope: SourceScope
    source_revision_id: str = Field(min_length=1)
    source_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_transcript_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    audio_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    segment_count: int = Field(ge=1)
    offset_unit: Literal["unicode_code_point"] = OFFSET_UNIT
    selectors: tuple[EvidenceSelector, ...] = Field(min_length=1)
    network_required: Literal[False] = False
    grounding_basis: Literal["transcript_only"] = "transcript_only"
    audio_grounded: Literal[False] = False

    @field_validator("artifact_id", "subject_ref", "source_revision_id")
    @classmethod
    def validate_non_blank_ids(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("selector artifact IDs must be non-blank")
        return value

    @model_validator(mode="after")
    def validate_artifact_identity(self) -> "EvidenceSelectorArtifact":
        evidence_ids = [selector.evidence_id for selector in self.selectors]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("selector artifact evidence IDs must be unique")
        if tuple(sorted(evidence_ids)) != tuple(evidence_ids):
            raise ValueError("selector artifact evidence IDs must be sorted")
        for selector in self.selectors:
            if selector.scope != self.scope:
                raise ValueError("selector scope does not match artifact scope")
            if selector.source_revision_id != self.source_revision_id:
                raise ValueError("selector revision does not match artifact revision")
            if selector.source_revision_sha256 != self.source_revision_sha256:
                raise ValueError("selector revision hash does not match artifact")
            if selector.raw_transcript_sha256 != self.raw_transcript_sha256:
                raise ValueError("selector raw transcript hash does not match artifact")
            if selector.normalized_source_sha256 != self.normalized_source_sha256:
                raise ValueError(
                    "selector normalized source hash does not match artifact"
                )
            if selector.offset_unit != self.offset_unit:
                raise ValueError("selector offset unit does not match artifact")
        expected_hash = _artifact_sha256(self)
        if self.artifact_sha256 != expected_hash:
            raise ValueError("selector artifact canonical hash mismatch")
        if self.artifact_id != f"selartv1:{expected_hash}":
            raise ValueError("selector artifact_id is not canonical")
        return self


_VERIFIED_ARTIFACT_AUTHORITY = object()


class VerifiedEvidenceSelectorArtifact:
    """Opaque proof that an artifact replayed against an immutable revision."""

    _artifact_json: str
    _sealed: bool
    __slots__ = ("_artifact_json", "_sealed")

    def __init__(self, artifact: EvidenceSelectorArtifact, *, _authority: object):
        if _authority is not _VERIFIED_ARTIFACT_AUTHORITY:
            raise TypeError("verified selector artifact requires internal authority")
        resolved = _revalidate_selector_artifact(artifact)
        object.__setattr__(self, "_artifact_json", resolved.model_dump_json())
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("verified selector artifact is immutable")
        object.__setattr__(self, name, value)

    @property
    def artifact(self) -> EvidenceSelectorArtifact:
        return _revalidate_selector_artifact(
            EvidenceSelectorArtifact.model_validate_json(self._artifact_json)
        )


def _selector_payload(selector: EvidenceSelector | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(selector, EvidenceSelector):
        payload = selector.model_dump(mode="json")
    else:
        payload = dict(selector)
    payload.pop("selector_id", None)
    return payload


def _selector_id(selector: EvidenceSelector | Mapping[str, Any]) -> str:
    return f"selv1:{sha256_canonical_json(_selector_payload(selector))}"


def _artifact_payload(
    artifact: EvidenceSelectorArtifact | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(artifact, EvidenceSelectorArtifact):
        payload = artifact.model_dump(mode="json")
    else:
        payload = dict(artifact)
    payload.pop("artifact_id", None)
    payload.pop("artifact_sha256", None)
    return payload


def _artifact_sha256(
    artifact: EvidenceSelectorArtifact | Mapping[str, Any],
) -> str:
    return sha256_canonical_json(_artifact_payload(artifact))


def _revalidate_selector_artifact(
    artifact: EvidenceSelectorArtifact | Mapping[str, Any],
) -> EvidenceSelectorArtifact:
    try:
        if isinstance(artifact, EvidenceSelectorArtifact):
            return EvidenceSelectorArtifact.model_validate_json(
                artifact.model_dump_json()
            )
        return EvidenceSelectorArtifact.model_validate(artifact)
    except ValidationError as exc:
        raise EvidenceSelectorError(
            "invalid immutable evidence selector artifact"
        ) from exc


def _revalidate_selector_request(
    request: EvidenceSelectorRequest | Mapping[str, Any],
) -> EvidenceSelectorRequest:
    try:
        if isinstance(request, EvidenceSelectorRequest):
            return EvidenceSelectorRequest.model_validate_json(
                request.model_dump_json()
            )
        return EvidenceSelectorRequest.model_validate(request)
    except ValidationError as exc:
        raise EvidenceSelectorError(
            "invalid immutable evidence selector request"
        ) from exc


def _all_occurrences(text: str, quote: str) -> tuple[int, ...]:
    offsets: list[int] = []
    cursor = 0
    while True:
        offset = text.find(quote, cursor)
        if offset < 0:
            return tuple(offsets)
        offsets.append(offset)
        cursor = offset + 1


def _segment_for_range(
    revision: SourceRevision,
    raw_start: int,
    raw_end: int,
    segment_starts: tuple[int, ...] | None = None,
) -> SourceSegment:
    starts = segment_starts or tuple(
        segment.raw_char_start for segment in revision.segments
    )
    candidate_index = bisect_right(starts, raw_start) - 1
    if candidate_index < 0:
        raise EvidenceSelectorError(
            "evidence quote must resolve wholly inside exactly one segment"
        )
    segment = revision.segments[candidate_index]
    if not (segment.raw_char_start <= raw_start and raw_end <= segment.raw_char_end):
        raise EvidenceSelectorError(
            "evidence quote must resolve wholly inside exactly one segment"
        )
    return segment


def _selector_from_request(
    revision: SourceRevision,
    request: EvidenceSelectorRequest,
    normalization: NormalizedTranscriptMap,
    segment_starts: tuple[int, ...],
    occurrence_cache: dict[str, tuple[int, ...]],
) -> EvidenceSelector:
    if request.scope != revision.scope:
        raise EvidenceSelectorError("selector request crosses source/case/file scope")
    if request.source_revision_id != revision.source_revision_id:
        raise EvidenceSelectorError("selector request source revision mismatch")
    occurrences = occurrence_cache.get(request.quote_exact)
    if occurrences is None:
        occurrences = _all_occurrences(revision.raw_transcript, request.quote_exact)
        occurrence_cache[request.quote_exact] = occurrences
    candidates: list[tuple[int, int, SourceSegment]] = []
    indexed_occurrences: Iterable[tuple[int, int]]
    if request.occurrence_index is not None:
        if request.occurrence_index >= len(occurrences):
            indexed_occurrences = ()
        else:
            indexed_occurrences = (
                (
                    request.occurrence_index,
                    occurrences[request.occurrence_index],
                ),
            )
    else:
        indexed_occurrences = enumerate(occurrences)
    for occurrence_index, raw_start in indexed_occurrences:
        raw_end = raw_start + len(request.quote_exact)
        try:
            segment = _segment_for_range(
                revision,
                raw_start,
                raw_end,
                segment_starts,
            )
        except EvidenceSelectorError:
            continue
        if request.segment_id is not None and segment.segment_id != request.segment_id:
            continue
        if request.prefix is not None and not revision.raw_transcript[
            :raw_start
        ].endswith(request.prefix):
            continue
        if request.suffix is not None and not revision.raw_transcript[
            raw_end:
        ].startswith(request.suffix):
            continue
        candidates.append((occurrence_index, raw_start, segment))
    if not candidates:
        raise EvidenceSelectorError(
            "evidence quote does not resolve in source revision"
        )
    if len(candidates) != 1:
        raise EvidenceSelectorError(
            "ambiguous evidence quote requires segment, context, or occurrence index"
        )
    occurrence_index, raw_start, segment = candidates[0]
    raw_end = raw_start + len(request.quote_exact)
    try:
        normalized_start, normalized_end = normalization.normalized_range_for_raw(
            raw_start,
            raw_end,
        )
    except SourceRevisionError as exc:
        raise EvidenceSelectorError(str(exc)) from exc
    quote_normalized = normalization.normalized_text[normalized_start:normalized_end]
    if quote_normalized != normalize_transcript(request.quote_exact):
        raise EvidenceSelectorError("quote normalized offsets do not roundtrip")
    prefix = revision.raw_transcript[
        max(0, raw_start - SELECTOR_CONTEXT_CHARS) : raw_start
    ]
    suffix = revision.raw_transcript[
        raw_end : min(len(revision.raw_transcript), raw_end + SELECTOR_CONTEXT_CHARS)
    ]
    payload: dict[str, Any] = {
        "selector_version": EVIDENCE_SELECTOR_VERSION,
        "evidence_id": request.evidence_id,
        "scope": revision.scope.model_dump(mode="json"),
        "source_revision_id": revision.source_revision_id,
        "source_revision_sha256": revision.canonical_sha256,
        "raw_transcript_sha256": revision.raw_transcript_sha256,
        "source_sha256": segment.text_sha256,
        "segment_sha256": segment.text_sha256,
        "normalized_source_sha256": revision.normalized_transcript_sha256,
        "segment_id": segment.segment_id,
        "quote_exact": request.quote_exact,
        "quote_normalized": quote_normalized,
        "quote_sha256": sha256_utf8(request.quote_exact),
        "normalized_quote_sha256": sha256_utf8(quote_normalized),
        "raw_char_start": raw_start,
        "raw_char_end": raw_end,
        "normalized_char_start": normalized_start,
        "normalized_char_end": normalized_end,
        "offset_unit": OFFSET_UNIT,
        "prefix": prefix,
        "suffix": suffix,
        "context_window_chars": SELECTOR_CONTEXT_CHARS,
        "occurrence_index": occurrence_index,
        "speaker_id": segment.speaker_id,
        "start_seconds": segment.start_seconds,
        "end_seconds": segment.end_seconds,
        "network_required": False,
        "grounding_basis": "transcript_only",
        "audio_grounded": False,
    }
    return EvidenceSelector(selector_id=_selector_id(payload), **payload)


def build_evidence_selector_artifact(
    *,
    revision: SourceRevision,
    subject_kind: Literal["verification", "relationship"],
    subject_ref: str,
    requests: Sequence[EvidenceSelectorRequest | Mapping[str, Any]],
) -> EvidenceSelectorArtifact:
    """Resolve requests and create one deterministic offline selector artifact."""

    revision = _revalidate_source_revision(revision)
    if not subject_ref.strip():
        raise EvidenceSelectorError("selector artifact subject_ref must be non-blank")
    resolved_requests = [_revalidate_selector_request(request) for request in requests]
    if not resolved_requests:
        raise EvidenceSelectorError("selector artifact requires at least one request")
    evidence_ids = [request.evidence_id for request in resolved_requests]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise EvidenceSelectorError("selector request evidence IDs must be unique")
    normalization = normalize_transcript_with_mapping(revision.raw_transcript)
    segment_starts = tuple(segment.raw_char_start for segment in revision.segments)
    occurrence_cache: dict[str, tuple[int, ...]] = {}
    selectors = tuple(
        sorted(
            (
                _selector_from_request(
                    revision,
                    request,
                    normalization,
                    segment_starts,
                    occurrence_cache,
                )
                for request in resolved_requests
            ),
            key=lambda selector: selector.evidence_id,
        )
    )
    payload: dict[str, Any] = {
        "artifact_version": EVIDENCE_SELECTOR_ARTIFACT_VERSION,
        "subject_kind": subject_kind,
        "subject_ref": subject_ref,
        "scope": revision.scope.model_dump(mode="json"),
        "source_revision_id": revision.source_revision_id,
        "source_revision_sha256": revision.canonical_sha256,
        "raw_transcript_sha256": revision.raw_transcript_sha256,
        "normalized_source_sha256": revision.normalized_transcript_sha256,
        "audio_sha256": revision.audio_sha256,
        "segment_count": revision.segment_count,
        "offset_unit": revision.offset_unit,
        "selectors": [selector.model_dump(mode="json") for selector in selectors],
        "network_required": False,
        "grounding_basis": "transcript_only",
        "audio_grounded": False,
    }
    artifact_hash = _artifact_sha256(payload)
    return EvidenceSelectorArtifact(
        artifact_id=f"selartv1:{artifact_hash}",
        artifact_sha256=artifact_hash,
        **{**payload, "selectors": selectors},
    )


def verify_evidence_selector_artifact(
    artifact: EvidenceSelectorArtifact | Mapping[str, Any],
    revision: SourceRevision,
) -> VerifiedEvidenceSelectorArtifact:
    """Replay every selector against the exact immutable transcript revision."""

    try:
        revision = _revalidate_source_revision(revision)
    except SourceRevisionError as exc:
        raise EvidenceSelectorError("invalid immutable source revision") from exc
    resolved_artifact = _revalidate_selector_artifact(artifact)
    if resolved_artifact.scope != revision.scope:
        raise EvidenceSelectorError("selector artifact crosses source/case/file scope")
    if resolved_artifact.source_revision_id != revision.source_revision_id:
        raise EvidenceSelectorError("selector artifact source revision mismatch")
    if resolved_artifact.source_revision_sha256 != revision.canonical_sha256:
        raise EvidenceSelectorError("selector artifact revision hash mismatch")
    if resolved_artifact.raw_transcript_sha256 != revision.raw_transcript_sha256:
        raise EvidenceSelectorError("selector artifact raw source hash mismatch")
    if (
        resolved_artifact.normalized_source_sha256
        != revision.normalized_transcript_sha256
    ):
        raise EvidenceSelectorError("selector artifact normalized source hash mismatch")
    if resolved_artifact.audio_sha256 != revision.audio_sha256:
        raise EvidenceSelectorError("selector artifact audio hash mismatch")
    if resolved_artifact.segment_count != revision.segment_count:
        raise EvidenceSelectorError("selector artifact segment count mismatch")
    if resolved_artifact.offset_unit != revision.offset_unit:
        raise EvidenceSelectorError("selector artifact offset unit mismatch")
    normalization = normalize_transcript_with_mapping(revision.raw_transcript)
    segment_starts = tuple(segment.raw_char_start for segment in revision.segments)
    occurrence_cache: dict[str, tuple[int, ...]] = {}
    for selector in resolved_artifact.selectors:
        if selector.raw_char_end > len(revision.raw_transcript):
            raise EvidenceSelectorError("selector raw range exceeds source")
        if (
            revision.raw_transcript[selector.raw_char_start : selector.raw_char_end]
            != selector.quote_exact
        ):
            raise EvidenceSelectorError("selector quote does not match raw offsets")
        normalized_range = normalization.normalized_range_for_raw(
            selector.raw_char_start,
            selector.raw_char_end,
        )
        if normalized_range != (
            selector.normalized_char_start,
            selector.normalized_char_end,
        ):
            raise EvidenceSelectorError("selector normalized offsets mismatch")
        if (
            normalization.normalized_text[
                selector.normalized_char_start : selector.normalized_char_end
            ]
            != selector.quote_normalized
        ):
            raise EvidenceSelectorError("selector normalized quote mismatch")
        expected_prefix = revision.raw_transcript[
            max(
                0, selector.raw_char_start - SELECTOR_CONTEXT_CHARS
            ) : selector.raw_char_start
        ]
        expected_suffix = revision.raw_transcript[
            selector.raw_char_end : min(
                len(revision.raw_transcript),
                selector.raw_char_end + SELECTOR_CONTEXT_CHARS,
            )
        ]
        if selector.prefix != expected_prefix or selector.suffix != expected_suffix:
            raise EvidenceSelectorError("selector prefix/suffix mismatch")
        occurrences = occurrence_cache.get(selector.quote_exact)
        if occurrences is None:
            occurrences = _all_occurrences(
                revision.raw_transcript,
                selector.quote_exact,
            )
            occurrence_cache[selector.quote_exact] = occurrences
        if (
            selector.occurrence_index >= len(occurrences)
            or occurrences[selector.occurrence_index] != selector.raw_char_start
        ):
            raise EvidenceSelectorError("selector occurrence index mismatch")
        segment = _segment_for_range(
            revision,
            selector.raw_char_start,
            selector.raw_char_end,
            segment_starts,
        )
        if segment.segment_id != selector.segment_id:
            raise EvidenceSelectorError("selector segment mismatch")
        if (
            selector.segment_sha256 != segment.text_sha256
            or selector.source_sha256 != segment.text_sha256
        ):
            raise EvidenceSelectorError("selector segment/source hash mismatch")
        if (
            segment.speaker_id != selector.speaker_id
            or segment.start_seconds != selector.start_seconds
            or segment.end_seconds != selector.end_seconds
        ):
            raise EvidenceSelectorError("selector speaker/time mismatch")
    return VerifiedEvidenceSelectorArtifact(
        resolved_artifact,
        _authority=_VERIFIED_ARTIFACT_AUTHORITY,
    )


def selector_artifact_sha256(artifact: EvidenceSelectorArtifact) -> str:
    return _artifact_sha256(_revalidate_selector_artifact(artifact))


__all__ = [
    "EVIDENCE_SELECTOR_ARTIFACT_VERSION",
    "EVIDENCE_SELECTOR_VERSION",
    "SELECTOR_CONTEXT_CHARS",
    "EvidenceSelector",
    "EvidenceSelectorArtifact",
    "EvidenceSelectorError",
    "EvidenceSelectorRequest",
    "VerifiedEvidenceSelectorArtifact",
    "build_evidence_selector_artifact",
    "selector_artifact_sha256",
    "verify_evidence_selector_artifact",
]
