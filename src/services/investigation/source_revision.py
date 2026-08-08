"""Immutable transcript source revisions for evidence-grounded investigation."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .contracts import canonical_json, sha256_canonical_json, sha256_utf8

SOURCE_REVISION_VERSION: Literal[
    "investigation-source-revision-v1.0"
] = "investigation-source-revision-v1.0"
NORMALIZATION_VERSION: Literal[
    "unicode-nfkc-casefold-whitespace-collapse-v1"
] = "unicode-nfkc-casefold-whitespace-collapse-v1"
UNICODE_DATA_VERSION = unicodedata.unidata_version
OFFSET_UNIT: Literal["unicode_code_point"] = "unicode_code_point"


class SourceRevisionError(ValueError):
    """Raised when transcript source material cannot be sealed safely."""


class ImmutableArtifact(BaseModel):
    """Strict immutable base for source and selector artifacts."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        protected_namespaces=(),
        allow_inf_nan=False,
        strict=True,
        revalidate_instances="always",
    )


def _require_non_blank(value: str, label: str) -> str:
    if not value.strip():
        raise ValueError(f"{label} must be non-blank")
    return value


def _validate_sha256(value: str, label: str) -> str:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


@dataclass(frozen=True)
class NormalizedCharSpan:
    """Raw source span contributing to one normalized code point."""

    raw_start: int
    raw_end: int


@dataclass(frozen=True)
class NormalizedTranscriptMap:
    """Deterministic NFKC/casefold/whitespace normalization with offsets."""

    raw_text: str
    normalized_text: str
    char_spans: tuple[NormalizedCharSpan, ...]
    _raw_starts: tuple[int, ...] = field(init=False, repr=False, compare=False)
    _raw_ends: tuple[int, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if len(self.normalized_text) != len(self.char_spans):
            raise SourceRevisionError("normalization mapping length mismatch")
        raw_starts = tuple(span.raw_start for span in self.char_spans)
        raw_ends = tuple(span.raw_end for span in self.char_spans)
        if any(left > right for left, right in zip(raw_starts, raw_starts[1:])):
            raise SourceRevisionError("normalization raw starts must be ordered")
        if any(left > right for left, right in zip(raw_ends, raw_ends[1:])):
            raise SourceRevisionError("normalization raw ends must be ordered")
        object.__setattr__(self, "_raw_starts", raw_starts)
        object.__setattr__(self, "_raw_ends", raw_ends)

    def normalized_range_for_raw(self, raw_start: int, raw_end: int) -> tuple[int, int]:
        if raw_start < 0 or raw_end <= raw_start or raw_end > len(self.raw_text):
            raise SourceRevisionError("invalid raw character range")
        first = bisect_right(self._raw_ends, raw_start)
        last = bisect_left(self._raw_starts, raw_end)
        normalized_slice = normalize_transcript(self.raw_text[raw_start:raw_end])
        if first >= last:
            if normalized_slice:
                raise SourceRevisionError("raw range has no normalized offset mapping")
            return (0, 0)
        spans = self.char_spans[first:last]
        if any(span.raw_start < raw_start or span.raw_end > raw_end for span in spans):
            raise SourceRevisionError("raw range splits a Unicode normalization unit")
        if self.normalized_text[first:last] != normalized_slice:
            raise SourceRevisionError("raw and normalized ranges are inconsistent")
        return first, last

    def raw_range_for_normalized(
        self,
        normalized_start: int,
        normalized_end: int,
    ) -> tuple[int, int]:
        if (
            normalized_start < 0
            or normalized_end <= normalized_start
            or normalized_end > len(self.normalized_text)
        ):
            raise SourceRevisionError("invalid normalized character range")
        spans = self.char_spans[normalized_start:normalized_end]
        return spans[0].raw_start, spans[-1].raw_end


def _is_hangul_l(char: str) -> bool:
    codepoint = ord(char)
    return 0x1100 <= codepoint <= 0x115F or 0xA960 <= codepoint <= 0xA97C


def _is_hangul_v(char: str) -> bool:
    codepoint = ord(char)
    return 0x1160 <= codepoint <= 0x11A7 or 0xD7B0 <= codepoint <= 0xD7C6


def _is_hangul_t(char: str) -> bool:
    codepoint = ord(char)
    return 0x11A8 <= codepoint <= 0x11FF or 0xD7CB <= codepoint <= 0xD7FB


def _is_precomposed_hangul_lv(char: str) -> bool:
    codepoint = ord(char)
    return 0xAC00 <= codepoint <= 0xD7A3 and (codepoint - 0xAC00) % 28 == 0


def _hangul_continues(unit: str, char: str) -> bool:
    if not unit:
        return False
    last = unit[-1]
    if _is_hangul_v(char) and _is_hangul_l(last):
        return True
    if _is_hangul_t(char) and (_is_hangul_v(last) or _is_precomposed_hangul_lv(last)):
        return True
    return False


def _normalization_continues(previous_char: str, char: str) -> bool:
    decomposed_char = unicodedata.normalize("NFKD", char)
    if not decomposed_char:
        return False
    first = decomposed_char[0]
    if unicodedata.combining(first):
        return True
    decomposed_tail = unicodedata.normalize("NFKD", previous_char)
    return _hangul_continues(decomposed_tail, first)


def _normalization_units(raw_text: str) -> Iterable[tuple[int, int]]:
    if not raw_text:
        return
    start = 0
    for index in range(1, len(raw_text)):
        char = raw_text[index]
        if _normalization_continues(raw_text[index - 1], char):
            continue
        yield start, index
        start = index
    yield start, len(raw_text)


def _nfkc_map(raw_text: str) -> tuple[str, list[NormalizedCharSpan]]:
    chars: list[str] = []
    spans: list[NormalizedCharSpan] = []
    for raw_start, raw_end in _normalization_units(raw_text):
        normalized_unit = unicodedata.normalize("NFKC", raw_text[raw_start:raw_end])
        chars.extend(normalized_unit)
        spans.extend(NormalizedCharSpan(raw_start, raw_end) for _ in normalized_unit)
    normalized = "".join(chars)
    expected = unicodedata.normalize("NFKC", raw_text)
    if normalized != expected:
        raise SourceRevisionError("unsupported Unicode normalization boundary")
    return normalized, spans


def _casefold_map(
    normalized_text: str,
    normalized_spans: Sequence[NormalizedCharSpan],
) -> tuple[str, list[NormalizedCharSpan]]:
    chars: list[str] = []
    spans: list[NormalizedCharSpan] = []
    for char, span in zip(normalized_text, normalized_spans, strict=True):
        folded = char.casefold()
        chars.extend(folded)
        spans.extend(span for _ in folded)
    casefolded = "".join(chars)
    expected = normalized_text.casefold()
    if casefolded != expected:
        raise SourceRevisionError("casefold mapping differs from Python normalization")
    return casefolded, spans


def normalize_transcript_with_mapping(raw_text: str) -> NormalizedTranscriptMap:
    """Apply NFKC, casefold and Unicode whitespace collapse with offsets."""

    if not isinstance(raw_text, str):
        raise TypeError("raw transcript must be a string")
    nfkc_text, nfkc_spans = _nfkc_map(raw_text)
    casefolded_text, casefolded_spans = _casefold_map(nfkc_text, nfkc_spans)
    output: list[str] = []
    output_spans: list[NormalizedCharSpan] = []
    pending_whitespace: list[NormalizedCharSpan] = []
    for char, span in zip(casefolded_text, casefolded_spans, strict=True):
        if char.isspace():
            pending_whitespace.append(span)
            continue
        if pending_whitespace and output:
            output.append(" ")
            output_spans.append(
                NormalizedCharSpan(
                    min(item.raw_start for item in pending_whitespace),
                    max(item.raw_end for item in pending_whitespace),
                )
            )
        pending_whitespace.clear()
        output.append(char)
        output_spans.append(span)
    normalized_text = "".join(output)
    if len(normalized_text) != len(output_spans):
        raise AssertionError("normalization mapping length mismatch")
    return NormalizedTranscriptMap(
        raw_text=raw_text,
        normalized_text=normalized_text,
        char_spans=tuple(output_spans),
    )


def normalize_transcript(raw_text: str) -> str:
    return normalize_transcript_with_mapping(raw_text).normalized_text


class SourceScope(ImmutableArtifact):
    case_id: str = Field(min_length=1)
    file_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)

    @field_validator("case_id", "file_id", "source_id")
    @classmethod
    def validate_scope_value(cls, value: str) -> str:
        return _require_non_blank(value, "source scope field")


class SourceSegmentDraft(ImmutableArtifact):
    text: str = Field(min_length=1)
    speaker_id: str | None = Field(default=None, min_length=1)
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    raw_char_start: int | None = Field(default=None, ge=0)
    raw_char_end: int | None = Field(default=None, ge=0)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        _require_non_blank(value, "segment text")
        if value != value.strip():
            raise ValueError("segment text cannot have leading or trailing whitespace")
        return value

    @field_validator("speaker_id")
    @classmethod
    def validate_speaker(cls, value: str | None) -> str | None:
        if value is not None:
            _require_non_blank(value, "speaker_id")
        return value

    @model_validator(mode="after")
    def validate_ranges(self) -> "SourceSegmentDraft":
        if (self.start_seconds is None) != (self.end_seconds is None):
            raise ValueError("segment timestamps must be provided together")
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds <= self.start_seconds
        ):
            raise ValueError("segment end_seconds must be greater than start_seconds")
        if (self.raw_char_start is None) != (self.raw_char_end is None):
            raise ValueError("segment raw offsets must be provided together")
        if (
            self.raw_char_start is not None
            and self.raw_char_end is not None
            and self.raw_char_end <= self.raw_char_start
        ):
            raise ValueError("segment raw_char_end must exceed raw_char_start")
        return self


class SourceSegment(ImmutableArtifact):
    segment_id: str = Field(min_length=1)
    order_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_char_start: int = Field(ge=0)
    raw_char_end: int = Field(gt=0)
    normalized_char_start: int = Field(ge=0)
    normalized_char_end: int = Field(gt=0)
    speaker_id: str | None = Field(default=None, min_length=1)
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        _require_non_blank(value, "segment text")
        if value != value.strip():
            raise ValueError("segment text cannot have leading or trailing whitespace")
        return value

    @field_validator("speaker_id")
    @classmethod
    def validate_speaker(cls, value: str | None) -> str | None:
        if value is not None:
            _require_non_blank(value, "speaker_id")
        return value


class SourceRevision(ImmutableArtifact):
    revision_version: Literal[
        "investigation-source-revision-v1.0"
    ] = SOURCE_REVISION_VERSION
    normalization_version: Literal[
        "unicode-nfkc-casefold-whitespace-collapse-v1"
    ] = NORMALIZATION_VERSION
    unicode_data_version: str = Field(
        default=UNICODE_DATA_VERSION,
        min_length=1,
    )
    offset_unit: Literal["unicode_code_point"] = OFFSET_UNIT
    scope: SourceScope
    raw_transcript: str = Field(min_length=1)
    normalized_transcript: str = Field(min_length=1)
    raw_transcript_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_transcript_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    audio_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    segments: tuple[SourceSegment, ...] = Field(min_length=1)
    segment_count: int = Field(ge=1)
    canonical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision_id: str = Field(min_length=1)
    network_required: Literal[False] = False
    grounding_basis: Literal["transcript_only"] = "transcript_only"

    @model_validator(mode="after")
    def validate_sealed_revision(self) -> "SourceRevision":
        _validate_source_revision(self)
        return self


def _revalidate_source_revision(
    revision: SourceRevision | Mapping[str, Any],
) -> SourceRevision:
    try:
        if isinstance(revision, SourceRevision):
            return SourceRevision.model_validate_json(revision.model_dump_json())
        return SourceRevision.model_validate(revision)
    except ValidationError as exc:
        raise SourceRevisionError("invalid immutable source revision") from exc


def _segment_identity_payload(
    scope: SourceScope,
    order_index: int,
    text_sha256: str,
    raw_char_start: int,
    raw_char_end: int,
    normalized_char_start: int,
    normalized_char_end: int,
    speaker_id: str | None,
    start_seconds: float | None,
    end_seconds: float | None,
) -> dict[str, Any]:
    return {
        "scope": scope.model_dump(mode="json"),
        "order_index": order_index,
        "text_sha256": text_sha256,
        "raw_char_start": raw_char_start,
        "raw_char_end": raw_char_end,
        "normalized_char_start": normalized_char_start,
        "normalized_char_end": normalized_char_end,
        "speaker_id": speaker_id,
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
    }


def _source_revision_payload(
    *,
    scope: SourceScope,
    raw_transcript_sha256: str,
    normalized_transcript_sha256: str,
    audio_sha256: str | None,
    segments: Sequence[SourceSegment],
) -> dict[str, Any]:
    return {
        "revision_version": SOURCE_REVISION_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "unicode_data_version": UNICODE_DATA_VERSION,
        "offset_unit": OFFSET_UNIT,
        "scope": scope.model_dump(mode="json"),
        "raw_transcript_sha256": raw_transcript_sha256,
        "normalized_transcript_sha256": normalized_transcript_sha256,
        "audio_sha256": audio_sha256,
        "segments": [segment.model_dump(mode="json") for segment in segments],
        "network_required": False,
        "grounding_basis": "transcript_only",
    }


def _coerce_segment_drafts(
    segments: Sequence[SourceSegmentDraft | Mapping[str, Any]] | None,
    raw_transcript: str,
) -> tuple[SourceSegmentDraft, ...]:
    if not segments:
        return (SourceSegmentDraft(text=raw_transcript.strip()),)
    try:
        return tuple(
            SourceSegmentDraft.model_validate_json(segment.model_dump_json())
            if isinstance(segment, SourceSegmentDraft)
            else SourceSegmentDraft.model_validate(segment)
            for segment in segments
        )
    except ValidationError as exc:
        raise SourceRevisionError("invalid immutable source segment draft") from exc


def build_source_revision(
    *,
    scope: SourceScope | Mapping[str, Any],
    raw_transcript: str,
    segments: Sequence[SourceSegmentDraft | Mapping[str, Any]] | None = None,
    audio_sha256: str | None = None,
) -> SourceRevision:
    """Seal exact transcript content and stable segments into one revision."""

    try:
        resolved_scope = (
            SourceScope.model_validate_json(scope.model_dump_json())
            if isinstance(scope, SourceScope)
            else SourceScope.model_validate(scope)
        )
    except ValidationError as exc:
        raise SourceRevisionError("invalid immutable source scope") from exc
    _require_non_blank(raw_transcript, "raw transcript")
    if audio_sha256 is not None:
        _validate_sha256(audio_sha256, "audio_sha256")
    normalization = normalize_transcript_with_mapping(raw_transcript)
    if not normalization.normalized_text:
        raise SourceRevisionError("normalized transcript must be non-blank")
    drafts = _coerce_segment_drafts(segments, raw_transcript)
    sealed_segments: list[SourceSegment] = []
    raw_cursor = 0
    last_start_seconds: float | None = None
    for order_index, draft in enumerate(drafts):
        if draft.raw_char_start is None:
            raw_start = raw_transcript.find(draft.text, raw_cursor)
            if raw_start < 0:
                raise SourceRevisionError(
                    f"segment {order_index} text is not present after the prior segment"
                )
            raw_end = raw_start + len(draft.text)
        else:
            raw_start = draft.raw_char_start
            raw_end = draft.raw_char_end or 0
        if raw_start < raw_cursor:
            raise SourceRevisionError(
                "segment raw ranges cannot overlap or go backward"
            )
        if raw_transcript[raw_cursor:raw_start].strip():
            raise SourceRevisionError(
                "uncovered transcript content between segments must be whitespace"
            )
        if (
            raw_end > len(raw_transcript)
            or raw_transcript[raw_start:raw_end] != draft.text
        ):
            raise SourceRevisionError(
                "segment text does not match raw transcript range"
            )
        if (
            last_start_seconds is not None
            and draft.start_seconds is not None
            and draft.start_seconds < last_start_seconds
        ):
            raise SourceRevisionError("segment timestamps must be ordered")
        normalized_start, normalized_end = normalization.normalized_range_for_raw(
            raw_start,
            raw_end,
        )
        if normalized_start == normalized_end:
            raise SourceRevisionError("segment cannot normalize to empty text")
        text_sha256 = sha256_utf8(draft.text)
        segment_payload = _segment_identity_payload(
            resolved_scope,
            order_index,
            text_sha256,
            raw_start,
            raw_end,
            normalized_start,
            normalized_end,
            draft.speaker_id,
            draft.start_seconds,
            draft.end_seconds,
        )
        segment_id = f"segv1:{sha256_canonical_json(segment_payload)}"
        sealed_segments.append(
            SourceSegment(
                segment_id=segment_id,
                order_index=order_index,
                text=draft.text,
                text_sha256=text_sha256,
                raw_char_start=raw_start,
                raw_char_end=raw_end,
                normalized_char_start=normalized_start,
                normalized_char_end=normalized_end,
                speaker_id=draft.speaker_id,
                start_seconds=draft.start_seconds,
                end_seconds=draft.end_seconds,
            )
        )
        raw_cursor = raw_end
        if draft.start_seconds is not None:
            last_start_seconds = draft.start_seconds
    if raw_transcript[raw_cursor:].strip():
        raise SourceRevisionError(
            "uncovered transcript content after segments must be whitespace"
        )
    raw_hash = sha256_utf8(raw_transcript)
    normalized_hash = sha256_utf8(normalization.normalized_text)
    revision_hash = sha256_canonical_json(
        _source_revision_payload(
            scope=resolved_scope,
            raw_transcript_sha256=raw_hash,
            normalized_transcript_sha256=normalized_hash,
            audio_sha256=audio_sha256,
            segments=sealed_segments,
        )
    )
    return SourceRevision(
        scope=resolved_scope,
        raw_transcript=raw_transcript,
        normalized_transcript=normalization.normalized_text,
        raw_transcript_sha256=raw_hash,
        normalized_transcript_sha256=normalized_hash,
        audio_sha256=audio_sha256,
        segments=tuple(sealed_segments),
        segment_count=len(sealed_segments),
        canonical_sha256=revision_hash,
        source_revision_id=f"srcv1:{revision_hash}",
    )


def _validate_source_revision(revision: SourceRevision) -> None:
    if revision.unicode_data_version != UNICODE_DATA_VERSION:
        raise ValueError("source revision Unicode data version mismatch")
    normalization = normalize_transcript_with_mapping(revision.raw_transcript)
    if revision.normalized_transcript != normalization.normalized_text:
        raise ValueError("normalized transcript does not match normalization policy")
    if revision.raw_transcript_sha256 != sha256_utf8(revision.raw_transcript):
        raise ValueError("raw transcript hash mismatch")
    if revision.normalized_transcript_sha256 != sha256_utf8(
        revision.normalized_transcript
    ):
        raise ValueError("normalized transcript hash mismatch")
    if revision.audio_sha256 is not None:
        _validate_sha256(revision.audio_sha256, "audio_sha256")
    if revision.segment_count != len(revision.segments):
        raise ValueError("segment_count mismatch")
    raw_cursor = 0
    last_start_seconds: float | None = None
    for order_index, segment in enumerate(revision.segments):
        if segment.order_index != order_index:
            raise ValueError("segment order_index must be contiguous")
        if segment.raw_char_end <= segment.raw_char_start:
            raise ValueError("segment raw range must be non-empty")
        if segment.normalized_char_end <= segment.normalized_char_start:
            raise ValueError("segment normalized range must be non-empty")
        if (segment.start_seconds is None) != (segment.end_seconds is None):
            raise ValueError("segment timestamps must be provided together")
        if (
            segment.start_seconds is not None
            and segment.end_seconds is not None
            and segment.end_seconds <= segment.start_seconds
        ):
            raise ValueError("segment timestamp range must be increasing")
        if segment.raw_char_start < raw_cursor:
            raise ValueError("segment raw ranges cannot overlap or go backward")
        if revision.raw_transcript[raw_cursor : segment.raw_char_start].strip():
            raise ValueError(
                "uncovered transcript content between segments must be whitespace"
            )
        if (
            segment.raw_char_end > len(revision.raw_transcript)
            or revision.raw_transcript[segment.raw_char_start : segment.raw_char_end]
            != segment.text
        ):
            raise ValueError("segment text/transcript mismatch")
        if segment.text_sha256 != sha256_utf8(segment.text):
            raise ValueError("segment text hash mismatch")
        normalized_range = normalization.normalized_range_for_raw(
            segment.raw_char_start,
            segment.raw_char_end,
        )
        if normalized_range != (
            segment.normalized_char_start,
            segment.normalized_char_end,
        ):
            raise ValueError("segment normalized offsets mismatch")
        if (
            last_start_seconds is not None
            and segment.start_seconds is not None
            and segment.start_seconds < last_start_seconds
        ):
            raise ValueError("segment timestamps must be ordered")
        expected_segment_id = "segv1:" + sha256_canonical_json(
            _segment_identity_payload(
                revision.scope,
                order_index,
                segment.text_sha256,
                segment.raw_char_start,
                segment.raw_char_end,
                segment.normalized_char_start,
                segment.normalized_char_end,
                segment.speaker_id,
                segment.start_seconds,
                segment.end_seconds,
            )
        )
        if segment.segment_id != expected_segment_id:
            raise ValueError("segment_id is not canonical")
        raw_cursor = segment.raw_char_end
        if segment.start_seconds is not None:
            last_start_seconds = segment.start_seconds
    if revision.raw_transcript[raw_cursor:].strip():
        raise ValueError(
            "uncovered transcript content after segments must be whitespace"
        )
    expected_revision_hash = sha256_canonical_json(
        _source_revision_payload(
            scope=revision.scope,
            raw_transcript_sha256=revision.raw_transcript_sha256,
            normalized_transcript_sha256=revision.normalized_transcript_sha256,
            audio_sha256=revision.audio_sha256,
            segments=revision.segments,
        )
    )
    if revision.canonical_sha256 != expected_revision_hash:
        raise ValueError("source revision canonical hash mismatch")
    if revision.source_revision_id != f"srcv1:{expected_revision_hash}":
        raise ValueError("source_revision_id is not canonical")


def source_revision_canonical_json(revision: SourceRevision) -> str:
    """Return a deterministic serialization for offline persistence/replay."""

    return canonical_json(_revalidate_source_revision(revision))


__all__ = [
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
]
