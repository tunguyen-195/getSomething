"""Typed transcript-only preview for investigation requests awaiting T5 release."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models.investigation_knowledge import (
    GroundedContextAnalysisPayload,
    KnowledgeGroundingError,
    participant_source_metadata_sha256,
    validate_grounded_summary_text,
)


PREVIEW_SCHEMA_VERSION = "grounded-investigative-bulletin-v1"
PUBLIC_PREVIEW_SCHEMA_VERSION = "preliminary-bulletin-v2"
PREVIEW_AUTHORITY = "grounded_synthesis_pending_human_review"
PREVIEW_RELEASE_STATUS = "pending_human_review"

BulletinSection = Literal[
    "overview",
    "actors_objects",
    "events_timeline",
    "relationships_flows",
    "critical_details",
    "assessment",
    "uncertainties",
]
_SECTION_TITLES: dict[BulletinSection, str] = {
    "overview": "Tổng quan",
    "actors_objects": "Nhân vật và đối tượng quan trọng",
    "events_timeline": "Sự kiện và diễn biến",
    "relationships_flows": "Mối quan hệ và luồng liên quan",
    "critical_details": "Chi tiết quan trọng",
    "assessment": "Nhận định cần xác minh",
    "uncertainties": "Điểm chưa rõ",
}
_ROLE_SECTION: dict[str, BulletinSection] = {
    "overview": "overview",
    "participant": "actors_objects",
    "event": "events_timeline",
    "time": "events_timeline",
    "location": "events_timeline",
    "relationship": "relationships_flows",
    "financial": "critical_details",
    "contact": "critical_details",
    "identifier": "critical_details",
    "outcome": "overview",
    "uncertainty": "uncertainties",
    "sensitive_detail": "critical_details",
}

_LEGACY_PREVIEW_HEADERS = {
    "bản xem trước evidence transcript - chưa phải tóm tắt điều tra đã phát hành.",
    "bản xem trước evidence transcript - chưa phải tóm tắt điều tra đã phát hành",
    "transcript evidence preview - not a released investigation summary.",
    "transcript evidence preview - not a released investigation summary",
    "transcript evidence preview - not a released investigation narrative.",
    "transcript evidence preview - not a released investigation narrative",
}
_LEGACY_LINE_PREFIX = re.compile(
    r"^(?:#{1,6}\s+)?(?:(?:[-*•]|\d+[.)])\s+)?(?:\*\*)?\s*"
)
_LEGACY_ATTRIBUTION_MARKER = re.compile(
    r"\[\s*(?:audio[\s_-]*offset|offset[\s_-]+(?:âm|am)[\s_-]+thanh)"
    r"\s*:[^\]]*\](?:\*\*)?\s*",
    re.IGNORECASE,
)
_LEGACY_SOURCE_PREFIX = re.compile(
    r"^(?:nguồn ghi nhận|source(?: record| quote)?)\s*:\s*",
    re.IGNORECASE,
)


class TranscriptEvidencePreviewError(ValueError):
    """Raised when a transcript preview cannot be proven against current input."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PreviewModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        protected_namespaces=(),
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class TranscriptEvidencePreviewSource(PreviewModel):
    task_id: str | None = Field(default=None, min_length=1)
    case_id: str | int | None = None
    file_name: str | None = Field(default=None, min_length=1)
    audio_id: str | int | None = None
    audio_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    transcript_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision_id: str | None = Field(default=None, min_length=1)
    context_model_id: str = Field(min_length=1)


class TranscriptEvidencePreviewEvidence(PreviewModel):
    evidence_id: str = Field(min_length=1)
    source_type: Literal["transcript_segment", "transcript_text"]
    segment_index: int | None = Field(default=None, ge=0)
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    speaker_id: str | None = Field(default=None, min_length=1)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, gt=0)
    quote: str = Field(min_length=1)
    quote_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_exact_source_binding(self) -> "TranscriptEvidencePreviewEvidence":
        if self.quote_sha256 != _sha256(self.quote):
            raise ValueError("preview evidence quote hash mismatch")
        if (self.start_seconds is None) != (self.end_seconds is None):
            raise ValueError("preview audio offsets must be paired")
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds < self.start_seconds
        ):
            raise ValueError("preview audio offsets are reversed")
        if self.source_type == "transcript_segment":
            if self.segment_index is None:
                raise ValueError("segment preview evidence requires segment_index")
            if self.char_start is not None or self.char_end is not None:
                raise ValueError("segment preview evidence cannot use transcript offsets")
        else:
            if self.char_start is None or self.char_end is None:
                raise ValueError("text preview evidence requires transcript offsets")
            if self.segment_index is not None:
                raise ValueError("text preview evidence cannot use segment_index")
        return self


class TranscriptEvidencePreviewLine(PreviewModel):
    line_id: str = Field(min_length=1)
    section: BulletinSection
    text: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    source_item_refs: list[str] = Field(min_length=1)


class TranscriptEvidencePreviewCoverage(PreviewModel):
    status: Literal["complete", "partial"]
    total_source_units: int = Field(ge=1)
    selected_source_units: int = Field(ge=1)
    omitted_source_units: int = Field(ge=0)
    selected_evidence_count: int = Field(ge=1)
    total_critical_items: int = Field(ge=0)
    covered_critical_items: int = Field(ge=0)
    omitted_critical_items: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> "TranscriptEvidencePreviewCoverage":
        if self.selected_source_units > self.total_source_units:
            raise ValueError("selected preview units exceed total source units")
        if self.omitted_source_units != (
            self.total_source_units - self.selected_source_units
        ):
            raise ValueError("preview omitted source-unit count mismatch")
        expected_status = "complete" if self.omitted_source_units == 0 else "partial"
        if self.covered_critical_items > self.total_critical_items:
            raise ValueError("covered critical items exceed total critical items")
        if self.omitted_critical_items != (
            self.total_critical_items - self.covered_critical_items
        ):
            raise ValueError("omitted critical-item count mismatch")
        if self.omitted_critical_items:
            expected_status = "partial"
        if self.status != expected_status:
            raise ValueError("preview coverage status mismatch")
        return self


class TranscriptEvidencePreview(PreviewModel):
    schema_version: Literal[PREVIEW_SCHEMA_VERSION] = PREVIEW_SCHEMA_VERSION
    artifact_type: Literal["transcript_evidence_preview"] = (
        "transcript_evidence_preview"
    )
    authority: Literal[PREVIEW_AUTHORITY] = PREVIEW_AUTHORITY
    release_status: Literal[PREVIEW_RELEASE_STATUS] = PREVIEW_RELEASE_STATUS
    world_facts_released: Literal[False] = False
    source: TranscriptEvidencePreviewSource
    evidence: list[TranscriptEvidencePreviewEvidence] = Field(min_length=1)
    lines: list[TranscriptEvidencePreviewLine] = Field(min_length=1)
    coverage: TranscriptEvidencePreviewCoverage
    text: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_projection(self) -> "TranscriptEvidencePreview":
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        if len(evidence_by_id) != len(self.evidence):
            raise ValueError("preview evidence IDs must be unique")
        line_ids = [line.line_id for line in self.lines]
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("preview line IDs must be unique")
        for line in self.lines:
            if len(line.evidence_refs) != len(set(line.evidence_refs)):
                raise ValueError("preview line evidence references must be unique")
            if len(line.source_item_refs) != len(set(line.source_item_refs)):
                raise ValueError("preview source-item references must be unique")
            if any(ref not in evidence_by_id for ref in line.evidence_refs):
                raise ValueError("preview line has dangling evidence reference")
            _validate_bulletin_line(
                line.text,
                [evidence_by_id[ref].quote for ref in line.evidence_refs],
            )
        expected_text = _render_bulletin_text(self.lines)
        if self.text != expected_text:
            raise ValueError("preview text does not match deterministic lines")
        if self.content_sha256 != _sha256(self.text):
            raise ValueError("preview content hash mismatch")
        if self.coverage.selected_evidence_count != len(self.evidence):
            raise ValueError("preview evidence coverage count mismatch")
        return self


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _unwrap_legacy_quote(value: str) -> str:
    trimmed = value.strip()
    for left, right in (("\"", "\""), ("“", "”"), ("'", "'")):
        if trimmed.startswith(left) and trimmed.endswith(right) and len(trimmed) >= 2:
            return trimmed[len(left) : -len(right)].strip()
    return trimmed


def sanitize_legacy_preview_text(value: object) -> str:
    """Remove reader-facing metadata emitted by transcript preview v1."""

    if not isinstance(value, str):
        return ""

    cleaned_lines: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            cleaned_lines.append("")
            continue
        if line.casefold() in _LEGACY_PREVIEW_HEADERS:
            continue

        prefix = _LEGACY_LINE_PREFIX.match(line)
        content = line[prefix.end() :] if prefix else line
        markers = list(_LEGACY_ATTRIBUTION_MARKER.finditer(content))
        if markers and markers[0].start() == 0:
            for index, marker in enumerate(markers):
                end = markers[index + 1].start() if index + 1 < len(markers) else len(content)
                chunk = content[marker.end() : end].strip()
                chunk = _LEGACY_SOURCE_PREFIX.sub("", chunk, count=1)
                chunk = _unwrap_legacy_quote(chunk.rstrip(" ;|"))
                if chunk:
                    cleaned_lines.append(chunk)
            continue

        cleaned_lines.append(line)

    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned_lines)).strip()


_BULLETIN_PREFIXES = (
    "Qua nội dung file audio, ghi nhận: ",
    "Nhân vật/đối tượng được nhắc đến: ",
    "Tổ chức được nhắc đến: ",
    "Địa điểm được nhắc đến: ",
    "Giá trị nhạy cảm được nhắc đến: ",
    "Sự kiện được mô tả: ",
    "Mối liên hệ được mô tả: ",
    "Chi tiết đáng chú ý: ",
    "Dấu hiệu cần xác minh: ",
)


def _sentence_text(value: object) -> str:
    text = _normalized_text(value).strip(" ;")
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _content_without_bulletin_prefix(value: str) -> str:
    for prefix in _BULLETIN_PREFIXES:
        if value.startswith(prefix):
            return value[len(prefix) :]
    return value


def _validate_bulletin_line(text: str, evidence_quotes: list[str]) -> None:
    try:
        validate_grounded_summary_text(
            _content_without_bulletin_prefix(text).rstrip("."),
            evidence_quotes,
            owner="bulletin sentence",
        )
    except KnowledgeGroundingError as exc:
        raise ValueError(str(exc)) from exc


def _render_bulletin_text(lines: Sequence[TranscriptEvidencePreviewLine]) -> str:
    factual_sections = (
        "overview",
        "actors_objects",
        "events_timeline",
        "relationships_flows",
        "critical_details",
    )
    factual_lines = [
        line.text for line in lines if line.section in factual_sections
    ]
    paragraphs: list[str] = []
    if factual_lines:
        factual_text = " ".join(factual_lines)
        if not factual_text.casefold().startswith("qua nội dung"):
            factual_text = f"Qua nội dung file audio, ghi nhận: {factual_text}"
        paragraphs.append(factual_text)
    for section in ("assessment", "uncertainties"):
        section_lines = [line.text for line in lines if line.section == section]
        if section_lines:
            paragraphs.append(" ".join(section_lines))
    return "\n\n".join(paragraphs)


def _source_unit_count(transcript: str, segments: Sequence[Mapping[str, Any]]) -> int:
    if segments:
        return max(
            1,
            sum(bool(_normalized_text(segment.get("text"))) for segment in segments),
        )
    units = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+|[\r\n]+", transcript)
        if part.strip()
    ]
    return max(1, len(units))


def _validate_current_source(
    payload: GroundedContextAnalysisPayload,
    transcript: str,
    segments: Sequence[Mapping[str, Any]],
    source_metadata: Mapping[str, Any],
) -> None:
    provenance = payload.investigation_knowledge.provenance
    transcript_hash = _sha256(_normalized_text(transcript))
    if provenance.transcript_sha256 != transcript_hash:
        raise TranscriptEvidencePreviewError(
            "INVESTIGATION_PREVIEW_STALE_TRANSCRIPT",
            "Grounded context does not match the current transcript.",
        )
    if provenance.transcript_segment_count != len(segments):
        raise TranscriptEvidencePreviewError(
            "INVESTIGATION_PREVIEW_STALE_SEGMENTS",
            "Grounded context does not match the current transcript segments.",
        )

    expected_segment_bindings = {
        item.segment_index: (
            item.source_sha256,
            item.start_seconds,
            item.end_seconds,
            item.speaker_id,
        )
        for item in provenance.segment_source_hashes
    }
    observed_segment_bindings = {
        index: (
            _sha256(_normalized_text(segment.get("text"))),
            segment.get("start"),
            segment.get("end"),
            _normalized_text(segment.get("speaker") or segment.get("speaker_id"))
            or None,
        )
        for index, segment in enumerate(segments)
    }
    if observed_segment_bindings != expected_segment_bindings:
        raise TranscriptEvidencePreviewError(
            "INVESTIGATION_PREVIEW_STALE_SEGMENTS",
            "Grounded context segment bindings do not match the current transcript.",
        )

    expected_participant_metadata_hash = (
        payload.investigation_knowledge.participant_registry.source_metadata_sha256
    )
    if participant_source_metadata_sha256(dict(source_metadata)) != expected_participant_metadata_hash:
        raise TranscriptEvidencePreviewError(
            "INVESTIGATION_PREVIEW_STALE_DIARIZATION",
            "Grounded context does not match the current diarization provenance.",
        )

    bindings = (
        ("task_id", provenance.source_task_id),
        ("audio_id", provenance.source_audio_id),
        ("audio_sha256", provenance.audio_sha256),
    )
    for field, expected in bindings:
        observed = source_metadata.get(field)
        if expected is not None and observed is not None and str(expected) != str(observed):
            raise TranscriptEvidencePreviewError(
                "INVESTIGATION_PREVIEW_SOURCE_MISMATCH",
                f"Grounded context {field} does not match the requested source.",
            )


def validate_current_grounded_context(
    *,
    context_analysis: Mapping[str, Any],
    transcript: str,
    segments: Sequence[Mapping[str, Any]] | None,
    source_metadata: Mapping[str, Any] | None,
) -> GroundedContextAnalysisPayload:
    """Validate a grounded context against the exact current transcript revision."""

    try:
        payload = GroundedContextAnalysisPayload.model_validate(context_analysis)
    except Exception as exc:
        raise TranscriptEvidencePreviewError(
            "INVESTIGATION_PREVIEW_CONTEXT_INVALID",
            "Grounded context failed the transcript-evidence contract.",
        ) from exc
    _validate_current_source(
        payload,
        transcript,
        list(segments or []),
        dict(source_metadata or {}),
    )
    return payload


def _source_order(
    evidence_refs: Sequence[str],
    evidence_by_id: Mapping[str, TranscriptEvidencePreviewEvidence],
) -> tuple[int, int, str]:
    evidence = [evidence_by_id[ref] for ref in evidence_refs]
    segment_indexes = [item.segment_index for item in evidence if item.segment_index is not None]
    char_offsets = [item.char_start for item in evidence if item.char_start is not None]
    return (
        min(segment_indexes) if segment_indexes else 2**31 - 1,
        min(char_offsets) if char_offsets else 2**31 - 1,
        evidence_refs[0],
    )


def _candidate(
    *,
    section: BulletinSection,
    text: str,
    evidence_refs: Sequence[str],
    source_item_refs: Sequence[str],
    priority: int,
    evidence_by_id: Mapping[str, TranscriptEvidencePreviewEvidence],
) -> dict[str, Any] | None:
    normalized_text = _sentence_text(text)
    refs = list(dict.fromkeys(evidence_refs))
    if not normalized_text or not refs:
        return None
    try:
        _validate_bulletin_line(
            normalized_text,
            [evidence_by_id[ref].quote for ref in refs],
        )
    except (KeyError, ValueError):
        return None
    return {
        "section": section,
        "text": normalized_text,
        "evidence_refs": refs,
        "source_item_refs": list(dict.fromkeys(source_item_refs)),
        "priority": priority,
        "source_order": _source_order(refs, evidence_by_id),
    }


def _deduplicate_candidates(candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in candidates:
        key = _content_without_bulletin_prefix(item["text"]).casefold().rstrip(".")
        existing = merged.get(key)
        if existing is None:
            merged[key] = dict(item)
            continue
        existing["evidence_refs"] = list(
            dict.fromkeys([*existing["evidence_refs"], *item["evidence_refs"]])
        )
        existing["source_item_refs"] = list(
            dict.fromkeys([*existing["source_item_refs"], *item["source_item_refs"]])
        )
        existing["priority"] = max(existing["priority"], item["priority"])
        existing["source_order"] = min(existing["source_order"], item["source_order"])
    return list(merged.values())


def _bind_item_to_summary_candidate(
    summary_candidates: Sequence[dict[str, Any]],
    *,
    source_item_ref: str,
    evidence_refs: Sequence[str],
    surfaces: Sequence[str],
) -> bool:
    normalized_surfaces = [
        _normalized_text(surface).casefold() for surface in surfaces if _normalized_text(surface)
    ]
    if not normalized_surfaces:
        return False
    evidence_set = set(evidence_refs)
    for candidate in summary_candidates:
        if not evidence_set.intersection(candidate["evidence_refs"]):
            continue
        searchable = candidate["text"].casefold()
        if all(surface in searchable for surface in normalized_surfaces):
            candidate["source_item_refs"] = list(
                dict.fromkeys([*candidate["source_item_refs"], source_item_ref])
            )
            return True
    return False


def _line_from_candidate(item: Mapping[str, Any]) -> TranscriptEvidencePreviewLine:
    identity = {
        "section": item["section"],
        "text": item["text"],
        "evidence_refs": item["evidence_refs"],
        "source_item_refs": item["source_item_refs"],
    }
    return TranscriptEvidencePreviewLine(
        line_id=f"bulletin-line:{_sha256(str(identity))[:16]}",
        section=item["section"],
        text=item["text"],
        evidence_refs=item["evidence_refs"],
        source_item_refs=item["source_item_refs"],
    )


def build_transcript_evidence_preview(
    *,
    context_analysis: Mapping[str, Any],
    transcript: str,
    segments: Sequence[Mapping[str, Any]] | None,
    source_metadata: Mapping[str, Any] | None,
    max_words: int,
) -> TranscriptEvidencePreview:
    """Plan a source-bound bulletin with whole-transcript and critical-item gates."""

    if not transcript or not transcript.strip():
        raise TranscriptEvidencePreviewError(
            "INVESTIGATION_PREVIEW_NO_EVIDENCE",
            "No transcript evidence is available for an investigation preview.",
        )
    segment_rows = list(segments or [])
    metadata = dict(source_metadata or {})
    payload = validate_current_grounded_context(
        context_analysis=context_analysis,
        transcript=transcript,
        segments=segment_rows,
        source_metadata=metadata,
    )

    knowledge = payload.investigation_knowledge
    evidence_by_id = {
        item.evidence_id: TranscriptEvidencePreviewEvidence.model_validate(
            item.model_dump(mode="json", exclude_none=True)
        )
        for item in knowledge.evidence_spans
    }
    candidates: list[dict[str, Any]] = []
    summary_candidates: list[dict[str, Any]] = []
    role_priority = {
        "financial": 125,
        "contact": 125,
        "identifier": 125,
        "sensitive_detail": 120,
        "event": 110,
        "time": 108,
        "location": 108,
        "relationship": 105,
        "participant": 100,
        "outcome": 98,
        "overview": 95,
        "uncertainty": 90,
    }
    for sentence in knowledge.summary_sentences:
        item = _candidate(
            section=_ROLE_SECTION[sentence.sentence_role],
            text=sentence.text,
            evidence_refs=sentence.evidence_ids,
            source_item_refs=[f"summary:{sentence.draft_id}"],
            priority=role_priority.get(sentence.sentence_role, 80),
            evidence_by_id=evidence_by_id,
        )
        if item is not None:
            summary_candidates.append(item)

    summary_candidates.sort(key=lambda item: item["source_order"])
    positional_summary_refs: set[str] = set()
    if summary_candidates:
        for index in {0, len(summary_candidates) // 2, len(summary_candidates) - 1}:
            summary_candidates[index]["section"] = "overview"
            summary_candidates[index]["priority"] = max(
                summary_candidates[index]["priority"],
                118,
            )
            positional_summary_refs.update(summary_candidates[index]["source_item_refs"])
    candidates.extend(summary_candidates)

    critical_refs: set[str] = set()
    entity_prefix = {
        "person": "Nhân vật/đối tượng được nhắc đến: ",
        "organization": "Tổ chức được nhắc đến: ",
        "location": "Địa điểm được nhắc đến: ",
    }
    for entity in knowledge.entities:
        critical_refs.add(entity.entity_id)
        if _bind_item_to_summary_candidate(
            summary_candidates,
            source_item_ref=entity.entity_id,
            evidence_refs=entity.evidence_ids,
            surfaces=[entity.value],
        ):
            continue
        prefix = entity_prefix.get(
            entity.entity_type,
            "Giá trị nhạy cảm được nhắc đến: ",
        )
        item = _candidate(
            section=(
                "actors_objects"
                if entity.entity_type in {"person", "organization"}
                else "critical_details"
            ),
            text=f"{prefix}{entity.value}",
            evidence_refs=entity.evidence_ids,
            source_item_refs=[entity.entity_id],
            priority=(125 if entity.entity_type not in {"person", "organization"} else 112),
            evidence_by_id=evidence_by_id,
        )
        if item is not None:
            candidates.append(item)

    for event in knowledge.events:
        critical_refs.add(event.event_id)
        if _bind_item_to_summary_candidate(
            summary_candidates,
            source_item_ref=event.event_id,
            evidence_refs=event.evidence_ids,
            surfaces=[event.description],
        ):
            continue
        item = _candidate(
            section="events_timeline",
            text=f"Sự kiện được mô tả: {event.description}",
            evidence_refs=event.evidence_ids,
            source_item_refs=[event.event_id],
            priority=120,
            evidence_by_id=evidence_by_id,
        )
        if item is not None:
            candidates.append(item)

    for relationship in knowledge.relationships:
        critical_refs.add(relationship.relationship_id)
        if _bind_item_to_summary_candidate(
            summary_candidates,
            source_item_ref=relationship.relationship_id,
            evidence_refs=relationship.evidence_ids,
            surfaces=[relationship.source, relationship.label, relationship.target],
        ):
            continue
        item = _candidate(
            section="relationships_flows",
            text=(
                "Mối liên hệ được mô tả: "
                f"{relationship.source} {relationship.label} {relationship.target}"
            ),
            evidence_refs=relationship.evidence_ids,
            source_item_refs=[relationship.relationship_id],
            priority=118,
            evidence_by_id=evidence_by_id,
        )
        if item is not None:
            candidates.append(item)

    critical_fact_markers = {
        "action",
        "contradiction",
        "decision",
        "financial",
        "identifier",
        "money",
        "quantity",
        "vehicle",
        "document",
    }
    for fact in knowledge.facts:
        searchable = f"{fact.category} {fact.statement}".casefold()
        is_critical = any(marker in searchable for marker in critical_fact_markers) or any(
            char.isdigit() for char in fact.statement
        )
        if not is_critical:
            continue
        critical_refs.add(fact.fact_id)
        if _bind_item_to_summary_candidate(
            summary_candidates,
            source_item_ref=fact.fact_id,
            evidence_refs=fact.evidence_ids,
            surfaces=[fact.statement],
        ):
            continue
        item = _candidate(
            section=("uncertainties" if fact.status == "conflicting" else "critical_details"),
            text=f"Chi tiết đáng chú ý: {fact.statement}",
            evidence_refs=fact.evidence_ids,
            source_item_refs=[fact.fact_id],
            priority=122,
            evidence_by_id=evidence_by_id,
        )
        if item is not None:
            candidates.append(item)

    for hypothesis in knowledge.hypotheses:
        critical_refs.add(hypothesis.hypothesis_id)
        item = _candidate(
            section="assessment",
            text=f"Dấu hiệu cần xác minh: {hypothesis.statement}",
            evidence_refs=hypothesis.evidence_ids,
            source_item_refs=[hypothesis.hypothesis_id],
            priority=116,
            evidence_by_id=evidence_by_id,
        )
        if item is not None:
            candidates.append(item)

    candidates = _deduplicate_candidates(candidates)
    candidates.sort(
        key=lambda item: (
            0
            if positional_summary_refs.intersection(item["source_item_refs"])
            else 1,
            -item["priority"],
            item["source_order"],
        )
    )
    selected_candidates: list[dict[str, Any]] = []
    selected_lines: list[TranscriptEvidencePreviewLine] = []
    for item in candidates:
        line = _line_from_candidate(item)
        proposed = [*selected_lines, line]
        if len(_render_bulletin_text(proposed).split()) <= max_words:
            selected_candidates.append(item)
            selected_lines.append(line)

    if not selected_lines:
        raise TranscriptEvidencePreviewError(
            "INVESTIGATION_PREVIEW_MAX_LENGTH_TOO_SMALL",
            "The requested maximum is too small for one grounded bulletin sentence.",
        )

    section_order = {section: index for index, section in enumerate(_SECTION_TITLES)}
    selected_lines.sort(
        key=lambda line: (
            section_order[line.section],
            _source_order(line.evidence_refs, evidence_by_id),
            line.line_id,
        )
    )

    selected_evidence_ids = list(
        dict.fromkeys(ref for line in selected_lines for ref in line.evidence_refs)
    )
    selected_evidence = [evidence_by_id[ref] for ref in selected_evidence_ids]

    total_units = _source_unit_count(transcript, segment_rows)
    selected_unit_keys = {
        (
            "segment",
            evidence.segment_index,
        )
        if evidence.segment_index is not None
        else ("text", evidence.char_start, evidence.char_end)
        for evidence in selected_evidence
    }
    selected_units = min(total_units, len(selected_unit_keys))
    omitted_units = total_units - selected_units
    covered_critical_refs = {
        ref
        for line in selected_lines
        for ref in line.source_item_refs
        if ref in critical_refs
    }
    omitted_critical_refs = critical_refs - covered_critical_refs
    preview_text = _render_bulletin_text(selected_lines)
    provenance = knowledge.provenance
    return TranscriptEvidencePreview(
        source=TranscriptEvidencePreviewSource(
            task_id=metadata.get("task_id") or provenance.source_task_id,
            case_id=metadata.get("case_id"),
            file_name=metadata.get("file_name") or metadata.get("filename"),
            audio_id=metadata.get("audio_id") or provenance.source_audio_id,
            audio_sha256=metadata.get("audio_sha256") or provenance.audio_sha256,
            transcript_sha256=provenance.transcript_sha256,
            source_revision_id=metadata.get("source_revision_id"),
            context_model_id=provenance.model_id,
        ),
        evidence=selected_evidence,
        lines=selected_lines,
        coverage=TranscriptEvidencePreviewCoverage(
            status=(
                "complete"
                if omitted_units == 0 and not omitted_critical_refs
                else "partial"
            ),
            total_source_units=total_units,
            selected_source_units=selected_units,
            omitted_source_units=omitted_units,
            selected_evidence_count=len(selected_evidence),
            total_critical_items=len(critical_refs),
            covered_critical_items=len(covered_critical_refs),
            omitted_critical_items=len(omitted_critical_refs),
        ),
        text=preview_text,
        content_sha256=_sha256(preview_text),
    )


def public_preview_payload(
    preview: TranscriptEvidencePreview,
    *,
    projection_mode: Literal["grounded_synthesis", "quote_only_fallback"] = (
        "grounded_synthesis"
    ),
) -> dict[str, Any]:
    """Project an internal grounded artifact into the reader-facing API shape."""

    return {
        "schema_version": PUBLIC_PREVIEW_SCHEMA_VERSION,
        "artifact_type": "preliminary_bulletin",
        "world_facts_released": preview.world_facts_released,
        "projection_mode": projection_mode,
        "completeness": preview.coverage.status,
        "text": preview.text,
    }


def public_synthesis_payload(
    text: str,
    *,
    completeness: Literal["complete", "partial"] = "complete",
) -> dict[str, Any]:
    """Build the compatibility projection for an accepted narrative writer result."""

    cleaned = sanitize_legacy_preview_text(text)
    if not cleaned:
        raise ValueError("grounded synthesis text is empty")
    return {
        "schema_version": PUBLIC_PREVIEW_SCHEMA_VERSION,
        "artifact_type": "preliminary_bulletin",
        "world_facts_released": False,
        "projection_mode": "grounded_synthesis",
        "completeness": completeness,
        "text": cleaned,
    }


def coerce_public_preview_payload(value: object) -> dict[str, Any] | None:
    """Redact stale/internal preview records at reader-facing API boundaries."""

    if isinstance(value, TranscriptEvidencePreview):
        return public_preview_payload(value)
    if not isinstance(value, Mapping):
        return None
    text = sanitize_legacy_preview_text(value.get("text"))
    if not text:
        return None
    if (
        value.get("schema_version") == PUBLIC_PREVIEW_SCHEMA_VERSION
        and value.get("artifact_type") == "preliminary_bulletin"
        and value.get("projection_mode") == "grounded_synthesis"
        and value.get("completeness") in {"complete", "partial"}
    ):
        return public_synthesis_payload(
            text,
            completeness=value["completeness"],
        )
    return {
        "schema_version": PUBLIC_PREVIEW_SCHEMA_VERSION,
        "artifact_type": "preliminary_bulletin",
        "world_facts_released": False,
        "projection_mode": "legacy_sanitized",
        "completeness": "unknown",
        "text": text,
    }


__all__ = [
    "PREVIEW_AUTHORITY",
    "PREVIEW_RELEASE_STATUS",
    "PREVIEW_SCHEMA_VERSION",
    "PUBLIC_PREVIEW_SCHEMA_VERSION",
    "TranscriptEvidencePreview",
    "TranscriptEvidencePreviewError",
    "build_transcript_evidence_preview",
    "coerce_public_preview_payload",
    "public_preview_payload",
    "public_synthesis_payload",
    "sanitize_legacy_preview_text",
    "validate_current_grounded_context",
]
