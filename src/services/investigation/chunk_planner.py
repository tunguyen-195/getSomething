"""Deterministic chunk planning for immutable transcript revisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import math
from typing import Any

from pydantic import ValidationError

from .discovery_common import (
    CHUNK_PLAN_VERSION,
    DISCOVERY_CHUNK_ID_PLACEHOLDER,
    DISCOVERY_SYSTEM_PROMPT,
    DiscoveryError,
    build_discovery_user_content,
)
from .discovery_contracts import (
    ChunkPlan,
    ChunkPlannerConfig,
    ChunkSegmentRef,
    DiscoveryChunk,
    chunk_id,
    chunk_plan_sha256,
)
from .source_revision import SourceRevision, SourceSegment, _revalidate_source_revision


def verify_chunk_plan(
    plan: ChunkPlan | Mapping[str, Any],
    revision: SourceRevision,
) -> ChunkPlan:
    """Revalidate a chunk plan against the exact immutable source revision."""

    revision = _revalidate_source_revision(revision)
    try:
        raw_json = (
            plan.model_dump_json()
            if isinstance(plan, ChunkPlan)
            else json.dumps(plan, ensure_ascii=False, allow_nan=False)
        )
        resolved = ChunkPlan.model_validate_json(raw_json)
    except (TypeError, ValueError, ValidationError) as exc:
        raise DiscoveryError("invalid chunk plan artifact") from exc
    if resolved.scope != revision.scope:
        raise DiscoveryError("chunk plan crosses source/case/file scope")
    if resolved.source_revision_id != revision.source_revision_id or (
        resolved.source_revision_sha256 != revision.canonical_sha256
    ):
        raise DiscoveryError("chunk plan source revision mismatch")
    if resolved.raw_transcript_sha256 != revision.raw_transcript_sha256:
        raise DiscoveryError("chunk plan raw transcript hash mismatch")
    source_ids = tuple(item.segment_id for item in revision.segments)
    primary_ids = tuple(
        segment_id
        for chunk in resolved.chunks
        for segment_id in chunk.primary_segment_ids
    )
    if primary_ids != source_ids:
        raise DiscoveryError("chunk plan primary coverage is not source-complete")
    source_by_id = {item.segment_id: item for item in revision.segments}
    source_index_by_id = {
        item.segment_id: index for index, item in enumerate(revision.segments)
    }
    for chunk in resolved.chunks:
        try:
            context_segments = [
                source_by_id[item.segment_id] for item in chunk.segment_refs
            ]
            primary_segments = [
                source_by_id[segment_id] for segment_id in chunk.primary_segment_ids
            ]
        except KeyError as exc:
            raise DiscoveryError("chunk plan references an unknown segment") from exc
        context_indexes = [
            source_index_by_id[item.segment_id] for item in chunk.segment_refs
        ]
        primary_indexes = [
            source_index_by_id[segment_id] for segment_id in chunk.primary_segment_ids
        ]
        if [item.order_index for item in chunk.segment_refs] != context_indexes:
            raise DiscoveryError("chunk segment order indexes do not match the source")
        if context_indexes != list(range(context_indexes[0], context_indexes[-1] + 1)):
            raise DiscoveryError("chunk context segments must be contiguous")
        if primary_indexes != list(range(primary_indexes[0], primary_indexes[-1] + 1)):
            raise DiscoveryError("chunk primary segments must be contiguous")
        if primary_indexes[0] - context_indexes[0] > resolved.config.overlap_turns or (
            context_indexes[-1] - primary_indexes[-1] > resolved.config.overlap_turns
        ):
            raise DiscoveryError("chunk overlap exceeds the configured turn window")
        if chunk.context_raw_char_start != context_segments[0].raw_char_start or (
            chunk.context_raw_char_end != context_segments[-1].raw_char_end
        ):
            raise DiscoveryError("chunk context range does not match source segments")
        if chunk.primary_raw_char_start != primary_segments[0].raw_char_start or (
            chunk.primary_raw_char_end != primary_segments[-1].raw_char_end
        ):
            raise DiscoveryError("chunk primary range does not match source segments")
        if chunk.oversized_single_segment:
            if (
                resolved.config.oversized_segment_policy != "singleton"
                or len(chunk.primary_segment_ids) != 1
                or chunk.primary_token_estimate <= resolved.config.input_budget_tokens
            ):
                raise DiscoveryError("invalid oversized singleton chunk")
        elif chunk.context_token_estimate > resolved.config.input_budget_tokens:
            raise DiscoveryError("chunk exceeds the recorded model input budget")
        expected_primary_tokens = _prompt_token_estimate(
            revision,
            primary_indexes=primary_indexes,
            context_indexes=primary_indexes,
            config=resolved.config,
        )
        expected_context_tokens = _prompt_token_estimate(
            revision,
            primary_indexes=primary_indexes,
            context_indexes=context_indexes,
            config=resolved.config,
        )
        if chunk.primary_token_estimate != expected_primary_tokens or (
            chunk.context_token_estimate != expected_context_tokens
        ):
            raise DiscoveryError("chunk prompt token estimates do not replay")
    return resolved


def estimate_tokens(text: str, *, chars_per_token: float = 2.8) -> int:
    """Return a deterministic conservative token estimate without a tokenizer."""

    if chars_per_token <= 0:
        raise ValueError("chars_per_token must be positive")
    return max(1, math.ceil(len(text.encode("utf-8")) / chars_per_token))


def _balanced_processing_order(count: int) -> tuple[int, ...]:
    if count <= 0:
        return ()
    anchors = [0]
    if count > 2:
        anchors.append(count // 2)
    if count > 1:
        anchors.append(count - 1)
    selected: list[int] = []
    for index in anchors:
        if index not in selected:
            selected.append(index)
    while len(selected) < count:
        remaining = [index for index in range(count) if index not in selected]
        next_index = max(
            remaining,
            key=lambda index: (min(abs(index - item) for item in selected), -index),
        )
        selected.append(next_index)
    return tuple(selected)


def _position_bucket(first: int, last: int, segment_count: int) -> str:
    if first == 0 and last == segment_count - 1:
        return "full"
    midpoint = (first + last + 1) / 2 / segment_count
    if midpoint < 1 / 3:
        return "head"
    if midpoint >= 2 / 3:
        return "tail"
    return "middle"


def _segment_tokens(segment: SourceSegment, config: ChunkPlannerConfig) -> int:
    return estimate_tokens(segment.text, chars_per_token=config.chars_per_token)


def _segment_prompt_payload(segment: SourceSegment, role: str) -> dict[str, Any]:
    return {
        "segment_id": segment.segment_id,
        "speaker_id": segment.speaker_id,
        "start_seconds": segment.start_seconds,
        "end_seconds": segment.end_seconds,
        "role": role,
        "text": segment.text,
    }


def _prompt_token_estimate(
    revision: SourceRevision,
    *,
    primary_indexes: Sequence[int],
    context_indexes: Sequence[int],
    config: ChunkPlannerConfig,
) -> int:
    primary_set = set(primary_indexes)
    user_content = build_discovery_user_content(
        source_revision_id=revision.source_revision_id,
        chunk_id=DISCOVERY_CHUNK_ID_PLACEHOLDER,
        primary_segment_ids=[
            revision.segments[index].segment_id for index in primary_indexes
        ],
        segments=[
            _segment_prompt_payload(
                revision.segments[index],
                "primary" if index in primary_set else "overlap_context",
            )
            for index in context_indexes
        ],
    )
    return (
        estimate_tokens(
            DISCOVERY_SYSTEM_PROMPT,
            chars_per_token=config.chars_per_token,
        )
        + estimate_tokens(user_content, chars_per_token=config.chars_per_token)
        + config.focus_hint_token_budget
        + config.message_framing_tokens
    )


def build_chunk_plan(
    revision: SourceRevision,
    config: ChunkPlannerConfig,
) -> ChunkPlan:
    """Plan source-ordered primary chunks and a balanced processing schedule."""

    revision = _revalidate_source_revision(revision)
    config = ChunkPlannerConfig.model_validate_json(config.model_dump_json())
    primary_groups: list[list[int]] = []
    current: list[int] = []
    current_tokens = 0
    input_budget = config.input_budget_tokens
    for index, segment in enumerate(revision.segments):
        token_count = _segment_tokens(segment, config)
        single_prompt_tokens = _prompt_token_estimate(
            revision,
            primary_indexes=[index],
            context_indexes=[index],
            config=config,
        )
        if (
            single_prompt_tokens > input_budget
            and config.oversized_segment_policy == "reject"
        ):
            raise DiscoveryError(
                f"segment {segment.segment_id} exceeds the model input budget"
            )
        candidate_indexes = [*current, index]
        candidate_prompt_tokens = _prompt_token_estimate(
            revision,
            primary_indexes=candidate_indexes,
            context_indexes=candidate_indexes,
            config=config,
        )
        if current and (
            current_tokens + token_count > config.target_chunk_tokens
            or candidate_prompt_tokens > input_budget
        ):
            primary_groups.append(current)
            current = []
            current_tokens = 0
        current.append(index)
        current_tokens += token_count
        if token_count > config.target_chunk_tokens:
            primary_groups.append(current)
            current = []
            current_tokens = 0
    if current:
        primary_groups.append(current)

    processing_order = _balanced_processing_order(len(primary_groups))
    rank_by_source = {
        source_index: rank for rank, source_index in enumerate(processing_order)
    }
    chunk_payloads: list[dict[str, Any]] = []
    for source_order, primary_indexes in enumerate(primary_groups):
        primary_set = set(primary_indexes)
        context_indexes = list(primary_indexes)
        context_tokens = _prompt_token_estimate(
            revision,
            primary_indexes=primary_indexes,
            context_indexes=context_indexes,
            config=config,
        )
        left_open = True
        right_open = True
        for distance in range(1, config.overlap_turns + 1):
            previous = primary_indexes[0] - distance
            following = primary_indexes[-1] + distance
            for candidate_index, side in (
                (previous, "left"),
                (following, "right"),
            ):
                if side == "left" and (not left_open or candidate_index < 0):
                    continue
                if side == "right" and (
                    not right_open or candidate_index >= revision.segment_count
                ):
                    continue
                candidate_context = sorted([*context_indexes, candidate_index])
                candidate_tokens = _prompt_token_estimate(
                    revision,
                    primary_indexes=primary_indexes,
                    context_indexes=candidate_context,
                    config=config,
                )
                if candidate_tokens <= input_budget:
                    context_indexes = candidate_context
                    context_tokens = candidate_tokens
                elif side == "left":
                    left_open = False
                else:
                    right_open = False
        context_indexes = sorted(set(context_indexes))
        primary_segments = [revision.segments[index] for index in primary_indexes]
        context_segments = [revision.segments[index] for index in context_indexes]
        segment_refs = tuple(
            ChunkSegmentRef(
                segment_id=revision.segments[index].segment_id,
                order_index=index,
                role="primary" if index in primary_set else "overlap_context",
            )
            for index in context_indexes
        )
        primary_tokens = _prompt_token_estimate(
            revision,
            primary_indexes=primary_indexes,
            context_indexes=primary_indexes,
            config=config,
        )
        oversized = primary_tokens > input_budget
        if context_tokens > input_budget and not oversized:
            raise DiscoveryError("chunk planner exceeded the model input budget")
        payload: dict[str, Any] = {
            "source_revision_id": revision.source_revision_id,
            "source_revision_sha256": revision.canonical_sha256,
            "source_order": source_order,
            "processing_rank": rank_by_source[source_order],
            "position_bucket": _position_bucket(
                primary_indexes[0], primary_indexes[-1], revision.segment_count
            ),
            "segment_refs": segment_refs,
            "primary_segment_ids": tuple(item.segment_id for item in primary_segments),
            "overlap_segment_ids": tuple(
                revision.segments[index].segment_id
                for index in context_indexes
                if index not in primary_set
            ),
            "primary_raw_char_start": primary_segments[0].raw_char_start,
            "primary_raw_char_end": primary_segments[-1].raw_char_end,
            "context_raw_char_start": context_segments[0].raw_char_start,
            "context_raw_char_end": context_segments[-1].raw_char_end,
            "primary_token_estimate": primary_tokens,
            "context_token_estimate": context_tokens,
            "oversized_single_segment": oversized,
        }
        chunk_payloads.append({"chunk_id": chunk_id(payload), **payload})
    chunks = tuple(DiscoveryChunk.model_validate(item) for item in chunk_payloads)
    plan_payload: dict[str, Any] = {
        "plan_version": CHUNK_PLAN_VERSION,
        "scope": revision.scope.model_dump(mode="json"),
        "source_revision_id": revision.source_revision_id,
        "source_revision_sha256": revision.canonical_sha256,
        "raw_transcript_sha256": revision.raw_transcript_sha256,
        "config": config.model_dump(mode="json"),
        "chunks": [item.model_dump(mode="json") for item in chunks],
        "segment_count": revision.segment_count,
        "chunk_count": len(chunks),
        "network_required": False,
    }
    plan_hash = chunk_plan_sha256(plan_payload)
    return ChunkPlan(
        plan_id=f"chnplanv1:{plan_hash}",
        plan_sha256=plan_hash,
        **{**plan_payload, "config": config, "chunks": chunks},
    )


__all__ = ["build_chunk_plan", "estimate_tokens", "verify_chunk_plan"]
