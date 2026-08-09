"""T2 immutable source revision and transcript evidence selector harness."""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from collections.abc import Callable

import pytest
from pydantic import ValidationError

import src.services.investigation.evidence_selector as selector_module
from src.services.investigation.contracts import (
    SourceProvenance,
    sha256_canonical_json,
    sha256_utf8,
)
from src.services.investigation.evidence_selector import (
    EVIDENCE_SELECTOR_ARTIFACT_VERSION,
    EVIDENCE_SELECTOR_VERSION,
    EvidenceSelectorArtifact,
    EvidenceSelectorError,
    EvidenceSelectorRequest,
    EvidenceSelectorResolver,
    VerifiedEvidenceSelectorArtifact,
    build_evidence_selector_artifact,
    selector_artifact_sha256,
    verify_evidence_selector_artifact,
)
from src.services.investigation.run_contracts import (
    build_trusted_investigation_validation_context_from_artifacts,
)
from src.services.investigation.source_revision import (
    NORMALIZATION_VERSION,
    OFFSET_UNIT,
    SOURCE_REVISION_VERSION,
    UNICODE_DATA_VERSION,
    SourceRevision,
    SourceRevisionError,
    SourceScope,
    SourceSegmentDraft,
    build_source_revision,
    normalize_transcript,
    normalize_transcript_with_mapping,
)

_AUDIO_HASH = sha256_utf8("offline-audio-fixture")


def _scope(
    *,
    case_id: str = "case-1",
    file_id: str = "file-1",
    source_id: str = "task-1",
) -> dict[str, str]:
    return {"case_id": case_id, "file_id": file_id, "source_id": source_id}


def _duplicate_revision():
    raw = "Lan nói: gặp lúc 09:00. Minh nói: gặp lúc 09:00."
    revision = build_source_revision(
        scope=_scope(),
        raw_transcript=raw,
        audio_sha256=_AUDIO_HASH,
        segments=[
            {
                "text": "Lan nói: gặp lúc 09:00.",
                "speaker_id": "speaker-1",
                "start_seconds": 0.0,
                "end_seconds": 2.5,
            },
            {
                "text": "Minh nói: gặp lúc 09:00.",
                "speaker_id": "speaker-2",
                "start_seconds": 2.5,
                "end_seconds": 5.0,
            },
        ],
    )
    return raw, revision


def _request(revision, **overrides):
    payload = {
        "evidence_id": "ev-1",
        "scope": revision.scope.model_dump(mode="json"),
        "source_revision_id": revision.source_revision_id,
        "quote_exact": "gặp lúc 09:00",
        "segment_id": revision.segments[1].segment_id,
    }
    payload.update(overrides)
    return payload


def _artifact(revision, **request_overrides):
    return build_evidence_selector_artifact(
        revision=revision,
        subject_kind="verification",
        subject_ref="ver-1",
        requests=[_request(revision, **request_overrides)],
    )


def _reseal_artifact(payload: dict) -> dict:
    for selector in payload["selectors"]:
        selector_payload = dict(selector)
        selector_payload.pop("selector_id", None)
        selector["selector_id"] = "selv1:" + sha256_canonical_json(selector_payload)
    artifact_payload = dict(payload)
    artifact_payload.pop("artifact_id", None)
    artifact_payload.pop("artifact_sha256", None)
    artifact_hash = sha256_canonical_json(artifact_payload)
    payload["artifact_sha256"] = artifact_hash
    payload["artifact_id"] = f"selartv1:{artifact_hash}"
    return payload


def _model_validate_artifact(payload: dict) -> EvidenceSelectorArtifact:
    return EvidenceSelectorArtifact.model_validate_json(
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def test_source_revision_is_exact_immutable_deterministic_and_timestamp_free():
    raw = "  Nguye\u0302\u0303n\tđã gặp ＡＢＣ.\nHồ sơ số ﬁ-01.  "
    segment_one = "Nguye\u0302\u0303n\tđã gặp ＡＢＣ."
    segment_two = "Hồ sơ số ﬁ-01."
    first = build_source_revision(
        scope=_scope(),
        raw_transcript=raw,
        audio_sha256=_AUDIO_HASH,
        segments=[
            {
                "text": segment_one,
                "speaker_id": "speaker-1",
                "start_seconds": 0.0,
                "end_seconds": 3.0,
            },
            {
                "text": segment_two,
                "speaker_id": "speaker-2",
                "start_seconds": 3.0,
                "end_seconds": 5.0,
            },
        ],
    )
    second = build_source_revision(
        scope=_scope(),
        raw_transcript=raw,
        audio_sha256=_AUDIO_HASH,
        segments=[
            {
                "text": segment_one,
                "speaker_id": "speaker-1",
                "start_seconds": 0.0,
                "end_seconds": 3.0,
            },
            {
                "text": segment_two,
                "speaker_id": "speaker-2",
                "start_seconds": 3.0,
                "end_seconds": 5.0,
            },
        ],
    )

    assert first == second
    assert first.raw_transcript == raw
    assert first.normalized_transcript == "nguyễn đã gặp abc. hồ sơ số fi-01."
    assert first.revision_version == SOURCE_REVISION_VERSION
    assert first.normalization_version == NORMALIZATION_VERSION
    assert first.unicode_data_version == UNICODE_DATA_VERSION
    assert first.offset_unit == OFFSET_UNIT
    assert first.source_revision_id == f"srcv1:{first.canonical_sha256}"
    assert first.segment_count == 2
    assert [segment.order_index for segment in first.segments] == [0, 1]
    assert first.network_required is False
    assert first.grounding_basis == "transcript_only"
    assert SourceRevision.model_validate_json(first.model_dump_json()) == first
    schema_text = json.dumps(SourceRevision.model_json_schema()).casefold()
    for forbidden in (
        "created_at",
        "creation_time",
        "uploaded_at",
        "upload_time",
    ):
        assert forbidden not in schema_text
    with pytest.raises(ValidationError, match="frozen"):
        first.raw_transcript = "mutated"  # type: ignore[misc]


def test_normalization_explicit_edges_and_raw_normalized_mapping_roundtrip():
    raw = "  Nguye\u0302\u0303n\tＡＢＣ\u00a0\u00a0ﬁle  "
    mapping = normalize_transcript_with_mapping(raw)

    assert mapping.normalized_text == "nguyễn abc file"
    assert normalize_transcript(mapping.normalized_text) == mapping.normalized_text
    raw_start = raw.index("ＡＢＣ")
    raw_end = raw_start + len("ＡＢＣ")
    normalized_start, normalized_end = mapping.normalized_range_for_raw(
        raw_start,
        raw_end,
    )
    assert mapping.normalized_text[normalized_start:normalized_end] == "abc"
    assert mapping.raw_range_for_normalized(normalized_start, normalized_end) == (
        raw_start,
        raw_end,
    )
    combining_mark = raw.index("\u0302")
    with pytest.raises(
        SourceRevisionError, match="splits a Unicode normalization unit"
    ):
        mapping.normalized_range_for_raw(combining_mark, combining_mark + 1)

    expansion_raw = "Straße İ"
    expansion_mapping = normalize_transcript_with_mapping(expansion_raw)
    sharp_s_start = expansion_raw.index("ß")
    normalized_start, normalized_end = expansion_mapping.normalized_range_for_raw(
        sharp_s_start,
        sharp_s_start + 1,
    )
    assert expansion_mapping.normalized_text == "strasse i̇"
    assert expansion_mapping.normalized_text[normalized_start:normalized_end] == "ss"
    assert expansion_mapping.raw_range_for_normalized(
        normalized_start,
        normalized_end,
    ) == (sharp_s_start, sharp_s_start + 1)

    halfwidth_raw = "ｶﾞ" * 4096
    halfwidth_mapping = normalize_transcript_with_mapping(halfwidth_raw)
    assert halfwidth_mapping.normalized_text == "ガ" * 4096
    assert halfwidth_mapping.char_spans[0].raw_start == 0
    assert halfwidth_mapping.char_spans[-1].raw_end == len(halfwidth_raw)


@pytest.mark.parametrize(
    "segments, message",
    [
        (
            [
                {"text": "Alpha", "raw_char_start": 0, "raw_char_end": 5},
                {"text": "pha", "raw_char_start": 2, "raw_char_end": 5},
            ],
            "cannot overlap",
        ),
        (
            [{"text": "Wrong", "raw_char_start": 0, "raw_char_end": 5}],
            "does not match raw transcript",
        ),
        (
            [
                {"text": "Alpha", "start_seconds": 2.0, "end_seconds": 3.0},
                {"text": "Beta", "start_seconds": 1.0, "end_seconds": 2.0},
            ],
            "timestamps must be ordered",
        ),
    ],
)
def test_source_revision_rejects_invalid_segment_transcript_ranges(
    segments,
    message,
):
    with pytest.raises((SourceRevisionError, ValidationError), match=message):
        build_source_revision(
            scope=_scope(),
            raw_transcript="Alpha Beta",
            segments=segments,
        )


def test_source_revision_rejects_non_whitespace_content_outside_segments():
    with pytest.raises(SourceRevisionError, match="uncovered transcript content"):
        build_source_revision(
            scope=_scope(),
            raw_transcript="alpha SECRET omega",
            segments=[
                {"text": "alpha", "raw_char_start": 0, "raw_char_end": 5},
                {"text": "omega", "raw_char_start": 13, "raw_char_end": 18},
            ],
        )


def test_source_revision_rejects_raw_segment_and_hash_mutation():
    _, revision = _duplicate_revision()

    raw_tamper = revision.model_dump(mode="json")
    raw_tamper["raw_transcript"] = raw_tamper["raw_transcript"].replace("Lan", "Nam", 1)
    with pytest.raises(ValidationError, match="normalized transcript does not match"):
        SourceRevision.model_validate_json(json.dumps(raw_tamper, ensure_ascii=False))

    hash_tamper = revision.model_dump(mode="json")
    hash_tamper["raw_transcript_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="raw transcript hash mismatch"):
        SourceRevision.model_validate_json(json.dumps(hash_tamper, ensure_ascii=False))

    segment_tamper = revision.model_dump(mode="json")
    segment_tamper["segments"][0]["text"] = "Nội dung đã sửa"
    segment_tamper["segments"][0]["text_sha256"] = sha256_utf8("Nội dung đã sửa")
    with pytest.raises(ValidationError, match="segment text/transcript mismatch"):
        SourceRevision.model_validate_json(
            json.dumps(segment_tamper, ensure_ascii=False)
        )

    copied_tamper = revision.model_copy(
        update={"raw_transcript": revision.raw_transcript.replace("Lan", "Nam", 1)}
    )
    with pytest.raises(SourceRevisionError, match="invalid immutable source revision"):
        build_evidence_selector_artifact(
            revision=copied_tamper,
            subject_kind="verification",
            subject_ref="ver-copy-tamper",
            requests=[_request(revision)],
        )


def test_source_revision_rejects_canonical_hash_and_timestamp_metadata_tamper():
    _, revision = _duplicate_revision()
    canonical_tamper = revision.model_dump(mode="json")
    canonical_tamper["canonical_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="canonical hash mismatch"):
        SourceRevision.model_validate_json(
            json.dumps(canonical_tamper, ensure_ascii=False)
        )

    timestamp_tamper = revision.model_dump(mode="json")
    timestamp_tamper["created_at"] = "2026-08-09T00:00:00Z"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SourceRevision.model_validate_json(
            json.dumps(timestamp_tamper, ensure_ascii=False)
        )

    unicode_version_tamper = revision.model_dump(mode="json")
    unicode_version_tamper["unicode_data_version"] = "future-version"
    with pytest.raises(ValidationError, match="Unicode data version mismatch"):
        SourceRevision.model_validate_json(
            json.dumps(unicode_version_tamper, ensure_ascii=False)
        )


def test_source_revision_rejects_resealed_noncanonical_segment_surface_metadata():
    _, revision = _duplicate_revision()
    speaker_tamper = revision.model_dump(mode="json")
    speaker_tamper["segments"][0]["speaker_id"] = "   "
    with pytest.raises(ValidationError, match="speaker_id must be non-blank"):
        SourceRevision.model_validate_json(
            json.dumps(speaker_tamper, ensure_ascii=False)
        )

    copied_draft = SourceSegmentDraft(text="Alpha").model_copy(
        update={"speaker_id": "   "}
    )
    with pytest.raises(SourceRevisionError, match="source segment draft"):
        build_source_revision(
            scope=_scope(),
            raw_transcript="Alpha",
            segments=[copied_draft],
        )

    copied_scope = SourceScope.model_validate(_scope()).model_copy(
        update={"case_id": "   "}
    )
    with pytest.raises(SourceRevisionError, match="source scope"):
        build_source_revision(
            scope=copied_scope,
            raw_transcript="Alpha",
        )


def test_duplicate_quote_requires_disambiguation_and_roundtrips_exact_selector():
    raw, revision = _duplicate_revision()
    ambiguous = _request(revision)
    ambiguous.pop("segment_id")

    with pytest.raises(EvidenceSelectorError, match="ambiguous evidence quote"):
        build_evidence_selector_artifact(
            revision=revision,
            subject_kind="verification",
            subject_ref="ver-1",
            requests=[ambiguous],
        )

    artifact = _artifact(revision)
    verified = verify_evidence_selector_artifact(artifact, revision)
    selector = verified.artifact.selectors[0]
    segment = revision.segments[1]
    evidence = selector.to_evidence_span()

    assert selector.selector_version == EVIDENCE_SELECTOR_VERSION
    assert artifact.artifact_version == EVIDENCE_SELECTOR_ARTIFACT_VERSION
    assert selector.occurrence_index == 1
    assert raw[selector.raw_char_start : selector.raw_char_end] == selector.quote_exact
    assert selector.segment_id == segment.segment_id
    assert selector.speaker_id == "speaker-2"
    assert selector.start_seconds == 2.5
    assert selector.end_seconds == 5.0
    assert selector.segment_sha256 == segment.text_sha256
    assert selector.source_sha256 == segment.text_sha256
    assert selector.raw_transcript_sha256 == revision.raw_transcript_sha256
    assert evidence.source_sha256 == sha256_utf8(segment.text)
    assert evidence.source_sha256 != revision.raw_transcript_sha256
    assert artifact.network_required is False
    assert artifact.audio_grounded is False
    assert artifact.grounding_basis == "transcript_only"
    assert artifact.audio_sha256 == revision.audio_sha256
    assert artifact.segment_count == revision.segment_count
    assert selector_artifact_sha256(artifact) == artifact.artifact_sha256
    assert EvidenceSelectorArtifact.model_validate_json(artifact.model_dump_json()) == (
        artifact
    )


def test_prefix_suffix_and_occurrence_resolve_repeated_quote_deterministically():
    raw = "trước A mã 77 sau A; trước B mã 77 sau B"
    revision = build_source_revision(scope=_scope(), raw_transcript=raw)
    base = {
        "evidence_id": "ev-1",
        "scope": _scope(),
        "source_revision_id": revision.source_revision_id,
        "quote_exact": "mã 77",
    }

    by_context = build_evidence_selector_artifact(
        revision=revision,
        subject_kind="verification",
        subject_ref="ver-1",
        requests=[{**base, "prefix": "trước B "}],
    )
    by_occurrence = build_evidence_selector_artifact(
        revision=revision,
        subject_kind="verification",
        subject_ref="ver-1",
        requests=[{**base, "occurrence_index": 1}],
    )

    assert (
        by_context.selectors[0].raw_char_start
        == by_occurrence.selectors[0].raw_char_start
    )
    assert by_context.selectors[0].occurrence_index == 1
    verify_evidence_selector_artifact(by_context, revision)
    verify_evidence_selector_artifact(by_occurrence, revision)


def test_overlapping_quote_occurrences_use_global_zero_based_index():
    revision = build_source_revision(scope=_scope(), raw_transcript="aaaa")
    artifact = build_evidence_selector_artifact(
        revision=revision,
        subject_kind="verification",
        subject_ref="ver-overlap",
        requests=[
            {
                "evidence_id": "ev-overlap",
                "scope": _scope(),
                "source_revision_id": revision.source_revision_id,
                "quote_exact": "aa",
                "occurrence_index": 1,
            }
        ],
    )

    assert artifact.selectors[0].raw_char_start == 1
    assert artifact.selectors[0].occurrence_index == 1
    verify_evidence_selector_artifact(artifact, revision)


def test_unicode_and_whitespace_quote_preserves_surface_and_normalized_offsets():
    raw = "Mã\tＡＢＣ\u00a0e\u0301 xuất hiện."
    revision = build_source_revision(scope=_scope(), raw_transcript=raw)
    quote = "ＡＢＣ\u00a0e\u0301"
    artifact = build_evidence_selector_artifact(
        revision=revision,
        subject_kind="verification",
        subject_ref="ver-unicode",
        requests=[
            {
                "evidence_id": "ev-unicode",
                "scope": _scope(),
                "source_revision_id": revision.source_revision_id,
                "quote_exact": quote,
            }
        ],
    )
    selector = artifact.selectors[0]

    assert selector.quote_exact == quote
    assert selector.quote_normalized == "abc é"
    assert (
        revision.normalized_transcript[
            selector.normalized_char_start : selector.normalized_char_end
        ]
        == "abc é"
    )
    verify_evidence_selector_artifact(artifact, revision)


def test_offsets_are_explicit_unicode_code_points_not_utf16_units():
    raw = "😀 mã 77"
    revision = build_source_revision(scope=_scope(), raw_transcript=raw)
    artifact = build_evidence_selector_artifact(
        revision=revision,
        subject_kind="verification",
        subject_ref="ver-offset-unit",
        requests=[
            {
                "evidence_id": "ev-offset-unit",
                "scope": _scope(),
                "source_revision_id": revision.source_revision_id,
                "quote_exact": "mã 77",
            }
        ],
    )
    selector = artifact.selectors[0]

    assert revision.offset_unit == "unicode_code_point"
    assert artifact.offset_unit == revision.offset_unit
    assert selector.offset_unit == revision.offset_unit
    assert selector.raw_char_start == 2
    assert raw[selector.raw_char_start : selector.raw_char_end] == "mã 77"
    verify_evidence_selector_artifact(artifact, revision)


def test_selector_rejects_cross_scope_revision_and_cross_segment_quote():
    _, revision = _duplicate_revision()
    wrong_scope = _request(revision, scope=_scope(case_id="case-other"))
    with pytest.raises(EvidenceSelectorError, match="crosses source/case/file"):
        build_evidence_selector_artifact(
            revision=revision,
            subject_kind="verification",
            subject_ref="ver-1",
            requests=[wrong_scope],
        )
    wrong_revision = _request(revision, source_revision_id="srcv1:" + "0" * 64)
    with pytest.raises(EvidenceSelectorError, match="source revision mismatch"):
        build_evidence_selector_artifact(
            revision=revision,
            subject_kind="verification",
            subject_ref="ver-1",
            requests=[wrong_revision],
        )
    with pytest.raises(EvidenceSelectorError, match="does not resolve"):
        build_evidence_selector_artifact(
            revision=revision,
            subject_kind="verification",
            subject_ref="ver-cross-segment",
            requests=[
                {
                    "evidence_id": "ev-cross",
                    "scope": _scope(),
                    "source_revision_id": revision.source_revision_id,
                    "quote_exact": ". Minh nói:",
                }
            ],
        )

    same_text_other_case = build_source_revision(
        scope=_scope(case_id="case-other"),
        raw_transcript=revision.raw_transcript,
        segments=[
            {
                "text": segment.text,
                "speaker_id": segment.speaker_id,
                "start_seconds": segment.start_seconds,
                "end_seconds": segment.end_seconds,
            }
            for segment in revision.segments
        ],
    )
    with pytest.raises(EvidenceSelectorError, match="crosses source/case/file"):
        verify_evidence_selector_artifact(_artifact(revision), same_text_other_case)


_Tamper = Callable[[dict], None]


def _tamper_raw_offset(payload: dict) -> None:
    selector = payload["selectors"][0]
    selector["raw_char_start"] += 1
    selector["raw_char_end"] += 1


def _tamper_normalized_offset(payload: dict) -> None:
    selector = payload["selectors"][0]
    selector["normalized_char_start"] += 1
    selector["normalized_char_end"] += 1


def _tamper_prefix(payload: dict) -> None:
    payload["selectors"][0]["prefix"] = "fabricated-prefix"


def _tamper_suffix(payload: dict) -> None:
    payload["selectors"][0]["suffix"] = "fabricated-suffix"


def _tamper_occurrence(payload: dict) -> None:
    payload["selectors"][0]["occurrence_index"] = 0


def _tamper_segment(payload: dict) -> None:
    payload["selectors"][0]["segment_id"] = "segv1:" + "0" * 64


def _tamper_segment_hash(payload: dict) -> None:
    selector = payload["selectors"][0]
    selector["segment_sha256"] = "0" * 64
    selector["source_sha256"] = "0" * 64


def _tamper_speaker(payload: dict) -> None:
    payload["selectors"][0]["speaker_id"] = "speaker-fabricated"


def _tamper_time(payload: dict) -> None:
    payload["selectors"][0]["start_seconds"] = 2.0


@pytest.mark.parametrize(
    "tamper, message",
    [
        (_tamper_raw_offset, "quote does not match raw offsets"),
        (_tamper_normalized_offset, "normalized offsets mismatch"),
        (_tamper_prefix, "prefix/suffix mismatch"),
        (_tamper_suffix, "prefix/suffix mismatch"),
        (_tamper_occurrence, "occurrence index mismatch"),
        (_tamper_segment, "segment mismatch"),
        (_tamper_segment_hash, "segment/source hash mismatch"),
        (_tamper_speaker, "speaker/time mismatch"),
        (_tamper_time, "speaker/time mismatch"),
    ],
)
def test_resealed_selector_field_tamper_fails_revision_replay(
    tamper: _Tamper,
    message: str,
):
    _, revision = _duplicate_revision()
    payload = _artifact(revision).model_dump(mode="json")
    tamper(payload)
    tampered = _model_validate_artifact(_reseal_artifact(payload))

    with pytest.raises(EvidenceSelectorError, match=message):
        verify_evidence_selector_artifact(tampered, revision)


@pytest.mark.parametrize("field", ["case_id", "file_id", "source_id"])
def test_resealed_cross_scope_artifact_fails_revision_replay(field):
    _, revision = _duplicate_revision()
    payload = _artifact(revision).model_dump(mode="json")
    payload["scope"][field] += "-other"
    payload["selectors"][0]["scope"][field] += "-other"
    tampered = _model_validate_artifact(_reseal_artifact(payload))

    with pytest.raises(EvidenceSelectorError, match="crosses source/case/file"):
        verify_evidence_selector_artifact(tampered, revision)


def test_resealed_revision_and_raw_source_hash_tamper_fail_replay():
    _, revision = _duplicate_revision()
    revision_payload = _artifact(revision).model_dump(mode="json")
    revision_payload["source_revision_id"] = "srcv1:" + "0" * 64
    revision_payload["selectors"][0]["source_revision_id"] = "srcv1:" + "0" * 64
    tampered_revision = _model_validate_artifact(_reseal_artifact(revision_payload))
    with pytest.raises(EvidenceSelectorError, match="source revision mismatch"):
        verify_evidence_selector_artifact(tampered_revision, revision)

    source_payload = _artifact(revision).model_dump(mode="json")
    source_payload["raw_transcript_sha256"] = "0" * 64
    source_payload["selectors"][0]["raw_transcript_sha256"] = "0" * 64
    tampered_source = _model_validate_artifact(_reseal_artifact(source_payload))
    with pytest.raises(EvidenceSelectorError, match="raw source hash mismatch"):
        verify_evidence_selector_artifact(tampered_source, revision)

    audio_payload = _artifact(revision).model_dump(mode="json")
    audio_payload["audio_sha256"] = "0" * 64
    tampered_audio = _model_validate_artifact(_reseal_artifact(audio_payload))
    with pytest.raises(EvidenceSelectorError, match="audio hash mismatch"):
        verify_evidence_selector_artifact(tampered_audio, revision)

    count_payload = _artifact(revision).model_dump(mode="json")
    count_payload["segment_count"] += 1
    tampered_count = _model_validate_artifact(_reseal_artifact(count_payload))
    with pytest.raises(EvidenceSelectorError, match="segment count mismatch"):
        verify_evidence_selector_artifact(tampered_count, revision)


def test_quote_and_artifact_hash_tamper_fail_before_revision_replay():
    _, revision = _duplicate_revision()
    quote_hash_payload = _artifact(revision).model_dump(mode="json")
    quote_hash_payload["selectors"][0]["quote_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="quote_sha256 mismatch"):
        _model_validate_artifact(_reseal_artifact(quote_hash_payload))

    artifact_hash_payload = _artifact(revision).model_dump(mode="json")
    artifact_hash_payload["artifact_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="canonical hash mismatch"):
        _model_validate_artifact(artifact_hash_payload)

    copied_tamper = _artifact(revision).model_copy(update={"artifact_id": "fake"})
    with pytest.raises(
        EvidenceSelectorError,
        match="invalid immutable evidence selector artifact",
    ):
        verify_evidence_selector_artifact(copied_tamper, revision)


def test_artifact_request_order_is_canonical_and_duplicate_evidence_ids_fail():
    raw, revision = _duplicate_revision()
    first = {
        "evidence_id": "ev-a",
        "scope": _scope(),
        "source_revision_id": revision.source_revision_id,
        "quote_exact": "Lan nói",
    }
    second = {
        "evidence_id": "ev-b",
        "scope": _scope(),
        "source_revision_id": revision.source_revision_id,
        "quote_exact": "Minh nói",
    }
    forward = build_evidence_selector_artifact(
        revision=revision,
        subject_kind="verification",
        subject_ref="ver-order",
        requests=[first, second],
    )
    reverse = build_evidence_selector_artifact(
        revision=revision,
        subject_kind="verification",
        subject_ref="ver-order",
        requests=[second, first],
    )

    assert forward == reverse
    assert [selector.evidence_id for selector in forward.selectors] == ["ev-a", "ev-b"]
    assert raw[forward.selectors[0].raw_char_start : forward.selectors[0].raw_char_end]
    with pytest.raises(EvidenceSelectorError, match="evidence IDs must be unique"):
        build_evidence_selector_artifact(
            revision=revision,
            subject_kind="verification",
            subject_ref="ver-duplicate",
            requests=[first, {**second, "evidence_id": "ev-a"}],
        )


def test_selector_build_reuses_source_normalization_and_occurrence_index(monkeypatch):
    raw = "mã 77 và mã 77"
    revision = build_source_revision(scope=_scope(), raw_transcript=raw)
    calls = {"normalization": 0, "occurrences": 0}
    original_normalize = selector_module.normalize_transcript_with_mapping
    original_occurrences = selector_module._all_occurrences

    def count_normalization(text):
        calls["normalization"] += 1
        return original_normalize(text)

    def count_occurrences(text, quote):
        calls["occurrences"] += 1
        return original_occurrences(text, quote)

    monkeypatch.setattr(
        selector_module,
        "normalize_transcript_with_mapping",
        count_normalization,
    )
    monkeypatch.setattr(selector_module, "_all_occurrences", count_occurrences)
    base = {
        "scope": _scope(),
        "source_revision_id": revision.source_revision_id,
        "quote_exact": "mã 77",
    }
    artifact = build_evidence_selector_artifact(
        revision=revision,
        subject_kind="verification",
        subject_ref="ver-cache",
        requests=[
            {**base, "evidence_id": "ev-1", "occurrence_index": 0},
            {**base, "evidence_id": "ev-2", "occurrence_index": 1},
        ],
    )

    assert len(artifact.selectors) == 2
    assert calls == {"normalization": 1, "occurrences": 1}
    verify_evidence_selector_artifact(artifact, revision)
    assert calls == {"normalization": 2, "occurrences": 2}


def test_prepared_resolver_reuses_revision_work_across_artifacts(monkeypatch):
    raw = "mã 77 và mã 77"
    revision = build_source_revision(scope=_scope(), raw_transcript=raw)
    calls = {"normalization": 0, "occurrences": 0}
    original_normalize = selector_module.normalize_transcript_with_mapping
    original_occurrences = selector_module._all_occurrences

    def count_normalization(text):
        calls["normalization"] += 1
        return original_normalize(text)

    def count_occurrences(text, quote):
        calls["occurrences"] += 1
        return original_occurrences(text, quote)

    monkeypatch.setattr(
        selector_module,
        "normalize_transcript_with_mapping",
        count_normalization,
    )
    monkeypatch.setattr(selector_module, "_all_occurrences", count_occurrences)
    resolver = EvidenceSelectorResolver(revision)
    artifacts = []
    for index in (0, 1):
        artifacts.append(
            resolver.build_artifact(
                subject_kind="verification",
                subject_ref=f"ver-{index}",
                requests=(
                    EvidenceSelectorRequest(
                        evidence_id=f"ev-{index}",
                        scope=revision.scope,
                        source_revision_id=revision.source_revision_id,
                        quote_exact="mã 77",
                        occurrence_index=index,
                    ),
                ),
            )
        )

    assert calls == {"normalization": 1, "occurrences": 1}
    for artifact in artifacts:
        resolver.verify_artifact(artifact)
    assert calls == {"normalization": 1, "occurrences": 1}


def test_only_replayed_artifact_builds_production_trusted_selector_context():
    _, revision = _duplicate_revision()
    artifact = _artifact(revision)
    verified = verify_evidence_selector_artifact(artifact, revision)
    context = build_trusted_investigation_validation_context_from_artifacts(
        selector_artifacts={"ver-1": verified},
        relationship_selector_artifacts={},
        risk_assessments={},
        verification_eligibility={},
        relationship_eligibility={},
        manifest_sha256="0" * 64,
    )
    attestation = context.selector_attestations["ver-1"]
    fingerprint = attestation.evidence["ev-1"]

    assert attestation.artifact_ref == artifact.artifact_id
    assert fingerprint.source_sha256 == revision.segments[1].text_sha256
    assert fingerprint.raw_transcript_sha256 == revision.raw_transcript_sha256
    assert fingerprint.source_revision_sha256 == revision.canonical_sha256
    assert (
        fingerprint.normalized_char_start == artifact.selectors[0].normalized_char_start
    )
    assert fingerprint.occurrence_index == 1
    provenance = SourceProvenance(
        source_revision_id=revision.source_revision_id,
        audio_sha256=revision.audio_sha256,
        raw_transcript_sha256=revision.raw_transcript_sha256,
        normalized_transcript_sha256=revision.normalized_transcript_sha256,
        segment_count=revision.segment_count,
    )
    context.validate_source_provenance(provenance)
    provenance_tampers = (
        ("raw_transcript_sha256", "0" * 64, "raw transcript hash"),
        ("normalized_transcript_sha256", "0" * 64, "normalized transcript hash"),
        ("audio_sha256", "0" * 64, "audio hash"),
        ("segment_count", revision.segment_count + 1, "segment count"),
    )
    for field, value, message in provenance_tampers:
        with pytest.raises(ValueError, match=message):
            context.validate_source_provenance(
                provenance.model_copy(update={field: value})
            )
    with pytest.warns(UserWarning, match="serializer warnings"):
        with pytest.raises(ValueError, match="invalid run source provenance"):
            context.validate_source_provenance(
                provenance.model_copy(update={"segment_count": "one"})
            )
    with pytest.raises(TypeError, match="verified T2 artifact"):
        build_trusted_investigation_validation_context_from_artifacts(
            selector_artifacts={"ver-1": artifact},  # type: ignore[dict-item]
            relationship_selector_artifacts={},
            risk_assessments={},
            verification_eligibility={},
            relationship_eligibility={},
            manifest_sha256="0" * 64,
        )
    with pytest.raises(TypeError, match="internal authority"):
        VerifiedEvidenceSelectorArtifact(artifact, _authority=object())
    with pytest.raises(AttributeError, match="immutable"):
        verified._artifact = artifact.model_copy(  # type: ignore[attr-defined]
            update={"artifact_id": "fake"}
        )
    with pytest.raises(AttributeError, match="immutable"):
        context.manifest_sha256 = "1" * 64


def test_relationship_artifact_uses_separate_trusted_registry_and_kind_gate():
    _, revision = _duplicate_revision()
    relationship_artifact = build_evidence_selector_artifact(
        revision=revision,
        subject_kind="relationship",
        subject_ref="rel-1",
        requests=[_request(revision)],
    )
    verified = verify_evidence_selector_artifact(relationship_artifact, revision)
    context = build_trusted_investigation_validation_context_from_artifacts(
        selector_artifacts={},
        relationship_selector_artifacts={"rel-1": verified},
        risk_assessments={},
        verification_eligibility={},
        relationship_eligibility={},
        manifest_sha256="0" * 64,
    )

    assert context.relationship_attestations["rel-1"].artifact_ref == (
        relationship_artifact.artifact_id
    )
    with pytest.raises(ValueError, match="subject kind mismatch"):
        build_trusted_investigation_validation_context_from_artifacts(
            selector_artifacts={"rel-1": verified},
            relationship_selector_artifacts={},
            risk_assessments={},
            verification_eligibility={},
            relationship_eligibility={},
            manifest_sha256="0" * 64,
        )
    with pytest.raises(ValueError, match="subject_ref does not match"):
        build_trusted_investigation_validation_context_from_artifacts(
            selector_artifacts={},
            relationship_selector_artifacts={"rel-other": verified},
            risk_assessments={},
            verification_eligibility={},
            relationship_eligibility={},
            manifest_sha256="0" * 64,
        )


def test_selector_artifact_rejects_resealed_blank_semantic_ids():
    _, revision = _duplicate_revision()
    payload = _artifact(revision).model_dump(mode="json")
    payload["subject_ref"] = "   "
    with pytest.raises(ValidationError, match="artifact IDs must be non-blank"):
        _model_validate_artifact(_reseal_artifact(payload))

    selector_payload = _artifact(revision).model_dump(mode="json")
    selector_payload["selectors"][0]["evidence_id"] = "   "
    with pytest.raises(ValidationError, match="selector IDs must be non-blank"):
        _model_validate_artifact(_reseal_artifact(selector_payload))

    request = EvidenceSelectorRequest.model_validate(_request(revision))
    copied_request = request.model_copy(update={"evidence_id": "   "})
    with pytest.raises(EvidenceSelectorError, match="selector request"):
        build_evidence_selector_artifact(
            revision=revision,
            subject_kind="verification",
            subject_ref="ver-request-copy",
            requests=[copied_request],
        )


@pytest.mark.parametrize("seed", [1, 2, 123, 0xC0FFEE])
def test_seeded_generative_normalization_mapping_selector_properties(seed):
    rng = random.Random(seed)
    tokens = [
        "An",
        "Bình",
        "Nguye\u0302\u0303n",
        "ＡＢＣ",
        "ﬁle",
        "R7-X",
        "09:00",
        "đ",
        "e\u0301",
        "ｶﾞ",
    ]
    whitespace = [" ", "  ", "\t", "\n", "\u00a0", "\u202f"]
    for sample_index in range(30):
        selected = [rng.choice(tokens) for _ in range(rng.randint(2, 8))]
        separators = [rng.choice(whitespace) for _ in range(len(selected) - 1)]
        raw_parts: list[str] = [rng.choice(whitespace)]
        for index, token in enumerate(selected):
            raw_parts.append(token)
            if index < len(separators):
                raw_parts.append(separators[index])
        raw_parts.append(rng.choice(whitespace))
        raw = "".join(raw_parts)
        mapping = normalize_transcript_with_mapping(raw)

        assert normalize_transcript(mapping.normalized_text) == mapping.normalized_text
        assert len(mapping.normalized_text) == len(mapping.char_spans)
        assert all(
            0 <= span.raw_start < span.raw_end <= len(raw)
            for span in mapping.char_spans
        )
        assert all(
            left.raw_start <= right.raw_start
            for left, right in zip(mapping.char_spans, mapping.char_spans[1:])
        )

        revision = build_source_revision(
            scope=_scope(
                case_id=f"case-{seed}",
                file_id=f"file-{sample_index}",
                source_id=f"source-{seed}-{sample_index}",
            ),
            raw_transcript=raw,
        )
        token = rng.choice(selected)
        occurrences: list[int] = []
        cursor = 0
        while True:
            offset = raw.find(token, cursor)
            if offset < 0:
                break
            occurrences.append(offset)
            cursor = offset + 1
        occurrence_index = rng.randrange(len(occurrences))
        request = {
            "evidence_id": "ev-generated",
            "scope": revision.scope.model_dump(mode="json"),
            "source_revision_id": revision.source_revision_id,
            "quote_exact": token,
            "occurrence_index": occurrence_index,
        }
        first = build_evidence_selector_artifact(
            revision=revision,
            subject_kind="verification",
            subject_ref="ver-generated",
            requests=[request],
        )
        second = build_evidence_selector_artifact(
            revision=revision,
            subject_kind="verification",
            subject_ref="ver-generated",
            requests=[request],
        )

        assert first == second
        assert verify_evidence_selector_artifact(first, revision).artifact == first
        selector = first.selectors[0]
        assert raw[selector.raw_char_start : selector.raw_char_end] == token
        assert revision.normalized_transcript[
            selector.normalized_char_start : selector.normalized_char_end
        ] == normalize_transcript(token)


def test_revision_and_selector_hashes_are_stable_across_process_hash_seeds():
    command = """
from src.services.investigation.source_revision import build_source_revision
from src.services.investigation.evidence_selector import (
    build_evidence_selector_artifact,
)
scope = {'case_id': 'case', 'file_id': 'file', 'source_id': 'source'}
revision = build_source_revision(scope=scope, raw_transcript='mã 77 và mã 77')
artifact = build_evidence_selector_artifact(
    revision=revision,
    subject_kind='verification',
    subject_ref='ver',
    requests=[{
        'evidence_id': 'ev',
        'scope': scope,
        'source_revision_id': revision.source_revision_id,
        'quote_exact': 'mã 77',
        'occurrence_index': 1,
    }],
)
print(revision.canonical_sha256, artifact.artifact_sha256)
"""
    outputs = set()
    for seed in ("1", "2", "123", "random"):
        process = subprocess.run(
            [sys.executable, "-c", command],
            check=True,
            capture_output=True,
            text=True,
            env={**dict(os.environ), "PYTHONHASHSEED": seed, "PYTHONUTF8": "1"},
        )
        outputs.add(process.stdout.strip())
    assert len(outputs) == 1
