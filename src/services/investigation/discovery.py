"""Stable public facade for adaptive T3 candidate discovery.

T3 deliberately stops before verification or release. Model and detector output
is converted into replayable T2 evidence selectors, but only T4 may decide
whether a candidate becomes a canonical fact.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Any

from pydantic import JsonValue, ValidationError

from .chunk_planner import build_chunk_plan, estimate_tokens, verify_chunk_plan
from .contracts import sha256_utf8
from .discovery_common import (
    ABLATION_MANIFEST_VERSION,
    CHUNK_PLAN_VERSION,
    DETECTOR_VERSION,
    DISCOVERY_MANIFEST_VERSION,
    DISCOVERY_PROMPT_VERSION,
    DISCOVERY_RESPONSE_VERSION,
    DISCOVERY_SYSTEM_PROMPT,
    DISCOVERY_VERSION,
    DiscoveryError,
    build_discovery_user_content,
    canonical_id,
    reject_sparse_payload,
    require_non_blank,
)
from .discovery_contracts import (
    ChunkPlan,
    ChunkPlannerConfig,
    ChunkSegmentRef,
    DetectedMention,
    DiscoveryAblationArm,
    DiscoveryAblationManifest,
    DiscoveryBatch,
    DiscoveryCandidateRecord,
    DiscoveryChunk,
    DiscoveryMessage,
    DiscoveryPromptEnvelope,
    DiscoveryRunManifest,
    EntityChallengerDraft,
    EntityChallengerRecord,
    LLMAtomicCandidateDraft,
    LLMDiscoveryResponse,
    LLMEntityMentionDraft,
    RetryPolicy,
    VerifiedDiscoveryBatch,
    build_discovery_ablation_manifest,
    candidate_record_id,
    discovery_batch_sha256,
    discovery_candidate_id,
    discovery_evidence_id,
    discovery_response_schema_sha256,
    entity_record_id,
    _seal_verified_discovery_batch,
)
from .evidence_selector import (
    EvidenceSelectorArtifact,
    EvidenceSelectorRequest,
    EvidenceSelectorResolver,
)
from .exact_detectors import detect_exact_mentions, detector_registry_sha256
from .run_contracts import DiscoveryCandidate
from .source_revision import (
    SourceRevision,
    SourceSegment,
    _revalidate_source_revision,
)


def _revalidate_chunk(chunk: DiscoveryChunk) -> DiscoveryChunk:
    """Reject Pydantic model_copy artifacts that bypassed chunk validators."""

    try:
        return DiscoveryChunk.model_validate_json(chunk.model_dump_json())
    except (TypeError, ValueError, ValidationError) as exc:
        raise DiscoveryError("invalid discovery chunk artifact") from exc


def _revalidate_chunk_plan(chunk_plan: ChunkPlan) -> ChunkPlan:
    """Recompute all nested chunk and plan invariants before using a plan."""

    try:
        return ChunkPlan.model_validate_json(chunk_plan.model_dump_json())
    except (TypeError, ValueError, ValidationError) as exc:
        raise DiscoveryError("invalid chunk plan artifact") from exc


def _chunk_segments(
    revision: SourceRevision,
    chunk: DiscoveryChunk,
) -> tuple[SourceSegment, ...]:
    revision_by_id = {item.segment_id: item for item in revision.segments}
    try:
        return tuple(revision_by_id[item.segment_id] for item in chunk.segment_refs)
    except KeyError as exc:
        raise DiscoveryError("chunk references an unknown source segment") from exc


def build_discovery_prompt(
    revision: SourceRevision,
    chunk: DiscoveryChunk,
    *,
    chunk_plan: ChunkPlan,
    focus_hint: str | None = None,
) -> DiscoveryPromptEnvelope:
    """Build role-separated prompt messages; transcript remains user data."""

    revision = _revalidate_source_revision(revision)
    chunk_plan = verify_chunk_plan(chunk_plan, revision)
    chunk = _revalidate_chunk(chunk)
    matching_chunks = [
        item for item in chunk_plan.chunks if item.chunk_id == chunk.chunk_id
    ]
    if len(matching_chunks) != 1 or matching_chunks[0] != chunk:
        raise DiscoveryError("discovery chunk is not bound to the verified chunk plan")
    if chunk.source_revision_id != revision.source_revision_id or (
        chunk.source_revision_sha256 != revision.canonical_sha256
    ):
        raise DiscoveryError("chunk source revision mismatch")
    segments = _chunk_segments(revision, chunk)
    segment_payloads = [
        {
            "segment_id": item.segment_id,
            "speaker_id": item.speaker_id,
            "start_seconds": item.start_seconds,
            "end_seconds": item.end_seconds,
            "role": next(
                ref.role
                for ref in chunk.segment_refs
                if ref.segment_id == item.segment_id
            ),
            "text": item.text,
        }
        for item in segments
    ]
    if focus_hint is not None:
        if not focus_hint.strip():
            raise DiscoveryError("focus_hint must be omitted instead of empty")
        if (
            estimate_tokens(
                focus_hint,
                chars_per_token=chunk_plan.config.chars_per_token,
            )
            > chunk_plan.config.focus_hint_token_budget
        ):
            raise DiscoveryError("focus_hint exceeds its recorded token budget")
    user_content = build_discovery_user_content(
        source_revision_id=revision.source_revision_id,
        chunk_id=chunk.chunk_id,
        primary_segment_ids=chunk.primary_segment_ids,
        segments=segment_payloads,
        focus_hint=focus_hint,
    )
    prompt_tokens = (
        estimate_tokens(
            DISCOVERY_SYSTEM_PROMPT,
            chars_per_token=chunk_plan.config.chars_per_token,
        )
        + estimate_tokens(
            user_content,
            chars_per_token=chunk_plan.config.chars_per_token,
        )
        + chunk_plan.config.message_framing_tokens
    )
    if prompt_tokens > chunk_plan.config.input_budget_tokens:
        raise DiscoveryError("effective discovery prompt exceeds model input budget")
    system_message = DiscoveryMessage(
        role="system",
        content=DISCOVERY_SYSTEM_PROMPT,
        content_sha256=sha256_utf8(DISCOVERY_SYSTEM_PROMPT),
    )
    user_message = DiscoveryMessage(
        role="user",
        content=user_content,
        content_sha256=sha256_utf8(user_content),
    )
    return DiscoveryPromptEnvelope(
        chunk_id=chunk.chunk_id,
        source_revision_id=revision.source_revision_id,
        system_message=system_message,
        user_message=user_message,
        response_schema_sha256=discovery_response_schema_sha256(),
    )


def parse_llm_discovery_response(raw_response: str) -> LLMDiscoveryResponse:
    """Parse exactly one strict JSON object and reject trailing model output."""

    if not raw_response.strip():
        raise DiscoveryError("LLM discovery response is empty")
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise DiscoveryError(
            "LLM discovery response is not one valid JSON value"
        ) from exc
    if not isinstance(payload, dict):
        raise DiscoveryError("LLM discovery response must be a JSON object")
    if payload.get("response_version") != DISCOVERY_RESPONSE_VERSION:
        raise DiscoveryError("LLM discovery response version is missing or unsupported")
    for collection_name in ("candidates", "entity_mentions"):
        items = payload.get(collection_name, [])
        if not isinstance(items, list):
            raise DiscoveryError(
                f"LLM discovery {collection_name} must be a JSON array"
            )
        for index, item in enumerate(items):
            try:
                reject_sparse_payload(item, f"{collection_name}.{index}")
            except ValueError as exc:
                raise DiscoveryError(
                    "LLM discovery response contains sparse or placeholder values"
                ) from exc
    try:
        return LLMDiscoveryResponse.model_validate_json(raw_response)
    except ValidationError as exc:
        raise DiscoveryError("LLM discovery response violates the T3 schema") from exc


def _selector_for_quote(
    revision: SourceRevision,
    *,
    resolver: EvidenceSelectorResolver,
    subject_ref: str,
    evidence_id: str,
    segment_id: str,
    quote_exact: str,
    quote_prefix: str | None = None,
    quote_suffix: str | None = None,
    raw_start: int | None = None,
) -> EvidenceSelectorArtifact:
    occurrence_index = (
        resolver.occurrence_index(quote_exact, raw_start)
        if raw_start is not None
        else None
    )
    artifact = resolver.build_artifact(
        subject_kind="verification",
        subject_ref=subject_ref,
        requests=(
            EvidenceSelectorRequest(
                evidence_id=evidence_id,
                scope=revision.scope,
                source_revision_id=revision.source_revision_id,
                quote_exact=quote_exact,
                segment_id=segment_id,
                prefix=quote_prefix,
                suffix=quote_suffix,
                occurrence_index=occurrence_index,
            ),
        ),
    )
    return artifact


def materialize_detector_candidates(
    revision: SourceRevision,
    chunk_plan: ChunkPlan,
) -> tuple[DiscoveryCandidateRecord, ...]:
    revision = _revalidate_source_revision(revision)
    chunk_plan = verify_chunk_plan(chunk_plan, revision)
    resolver = EvidenceSelectorResolver(revision)
    primary_chunk_by_segment = {
        segment_id: chunk.chunk_id
        for chunk in chunk_plan.chunks
        for segment_id in chunk.primary_segment_ids
    }
    records: list[DiscoveryCandidateRecord] = []
    for mention in detect_exact_mentions(revision):
        attributes: dict[str, JsonValue] = {
            "candidate_channel": "exact_detector",
            "detector_version": DETECTOR_VERSION,
            "detector_rule_id": mention.detector_rule_id,
            "surface": mention.surface,
            "ambiguous": mention.ambiguous,
        }
        if mention.normalized is not None:
            attributes["normalized"] = mention.normalized
        if mention.cue is not None:
            attributes["cue"] = mention.cue
        statement = f"Explicit source mention: {mention.surface}"
        candidate_id = discovery_candidate_id(
            source_revision_id=revision.source_revision_id,
            channel="exact_detector",
            chunk_id=primary_chunk_by_segment[mention.segment_id],
            claim_type=mention.detector_type,
            statement=statement,
            polarity="affirmed",
            attributes=attributes,
            segment_id=mention.segment_id,
            quote_exact=mention.surface,
        )
        evidence_id = discovery_evidence_id(
            candidate_id=candidate_id,
            segment_id=mention.segment_id,
            quote_exact=mention.surface,
        )
        selector = _selector_for_quote(
            revision,
            resolver=resolver,
            subject_ref=candidate_id,
            evidence_id=evidence_id,
            segment_id=mention.segment_id,
            quote_exact=mention.surface,
            raw_start=mention.raw_char_start,
        )
        candidate = DiscoveryCandidate(
            candidate_id=candidate_id,
            claim_type=mention.detector_type,
            statement=statement,
            polarity="affirmed",
            epistemic_status="fact",
            requires_human_verification=False,
            evidence_refs=[evidence_id],
            attributes=attributes,
        )
        record_payload: dict[str, Any] = {
            "channel": "exact_detector",
            "chunk_id": primary_chunk_by_segment[mention.segment_id],
            "candidate": candidate,
            "selector_artifact": selector,
            "candidate_only": True,
            "verification_decision_present": False,
            "release_authority": False,
        }
        records.append(
            DiscoveryCandidateRecord(
                record_id=candidate_record_id(record_payload),
                **record_payload,
            )
        )
    return tuple(records)


def _ensure_chunk_segment(
    revision: SourceRevision,
    chunk: DiscoveryChunk,
    segment_id: str,
) -> SourceSegment:
    allowed = set(chunk.primary_segment_ids)
    if segment_id not in allowed:
        raise DiscoveryError(
            "model candidate references a segment outside its chunk primary scope"
        )
    for segment in revision.segments:
        if segment.segment_id == segment_id:
            return segment
    raise DiscoveryError("model candidate references an unknown segment")


def materialize_llm_candidates(
    revision: SourceRevision,
    chunk: DiscoveryChunk,
    response: LLMDiscoveryResponse,
) -> tuple[DiscoveryCandidateRecord, ...]:
    """Assign host-owned IDs and T2 selectors to strict raw model candidates."""

    revision = _revalidate_source_revision(revision)
    chunk = _revalidate_chunk(chunk)
    response = LLMDiscoveryResponse.model_validate_json(response.model_dump_json())
    resolver = EvidenceSelectorResolver(revision)
    records: list[DiscoveryCandidateRecord] = []
    for draft in response.candidates:
        _ensure_chunk_segment(revision, chunk, draft.segment_id)
        attributes = dict(draft.attributes or {})
        attributes.update(
            {
                "candidate_channel": "llm_discovery",
                "candidate_kind": draft.candidate_kind,
            }
        )
        if draft.candidate_kind == "relationship":
            attributes.update(
                {
                    "predicate": draft.predicate or "",
                    "source_surface": draft.source_surface or "",
                    "target_surface": draft.target_surface or "",
                }
            )
        candidate_id = discovery_candidate_id(
            source_revision_id=revision.source_revision_id,
            channel="llm_discovery",
            chunk_id=chunk.chunk_id,
            claim_type=draft.claim_type,
            statement=draft.statement,
            polarity=draft.polarity,
            attributes=attributes,
            segment_id=draft.segment_id,
            quote_exact=draft.quote_exact,
        )
        evidence_id = discovery_evidence_id(
            candidate_id=candidate_id,
            segment_id=draft.segment_id,
            quote_exact=draft.quote_exact,
        )
        selector = _selector_for_quote(
            revision,
            resolver=resolver,
            subject_ref=candidate_id,
            evidence_id=evidence_id,
            segment_id=draft.segment_id,
            quote_exact=draft.quote_exact,
            quote_prefix=draft.quote_prefix,
            quote_suffix=draft.quote_suffix,
        )
        candidate = DiscoveryCandidate(
            candidate_id=candidate_id,
            claim_type=draft.claim_type,
            statement=draft.statement,
            polarity=draft.polarity,
            epistemic_status="fact",
            requires_human_verification=False,
            evidence_refs=[evidence_id],
            attributes=attributes,
        )
        record_payload: dict[str, Any] = {
            "channel": "llm_discovery",
            "chunk_id": chunk.chunk_id,
            "candidate": candidate,
            "selector_artifact": selector,
            "candidate_only": True,
            "verification_decision_present": False,
            "release_authority": False,
        }
        records.append(
            DiscoveryCandidateRecord(
                record_id=candidate_record_id(record_payload),
                **record_payload,
            )
        )
    for entity_draft in response.entity_mentions:
        _ensure_chunk_segment(revision, chunk, entity_draft.segment_id)
        claim_type = f"entity_mention.{entity_draft.entity_type}"
        statement = f"Explicit entity mention: {entity_draft.surface}"
        attributes = dict(entity_draft.attributes or {})
        attributes.update(
            {
                "candidate_channel": "llm_discovery",
                "candidate_kind": "entity_mention",
                "entity_type": entity_draft.entity_type,
                "surface": entity_draft.surface,
            }
        )
        if entity_draft.role is not None:
            attributes["role"] = entity_draft.role
        candidate_id = discovery_candidate_id(
            source_revision_id=revision.source_revision_id,
            channel="llm_discovery",
            chunk_id=chunk.chunk_id,
            claim_type=claim_type,
            statement=statement,
            polarity="reported",
            attributes=attributes,
            segment_id=entity_draft.segment_id,
            quote_exact=entity_draft.quote_exact,
        )
        evidence_id = discovery_evidence_id(
            candidate_id=candidate_id,
            segment_id=entity_draft.segment_id,
            quote_exact=entity_draft.quote_exact,
        )
        selector = _selector_for_quote(
            revision,
            resolver=resolver,
            subject_ref=candidate_id,
            evidence_id=evidence_id,
            segment_id=entity_draft.segment_id,
            quote_exact=entity_draft.quote_exact,
            quote_prefix=entity_draft.quote_prefix,
            quote_suffix=entity_draft.quote_suffix,
        )
        candidate = DiscoveryCandidate(
            candidate_id=candidate_id,
            claim_type=claim_type,
            statement=statement,
            polarity="reported",
            epistemic_status="fact",
            requires_human_verification=False,
            evidence_refs=[evidence_id],
            attributes=attributes,
        )
        record_payload = {
            "channel": "llm_discovery",
            "chunk_id": chunk.chunk_id,
            "candidate": candidate,
            "selector_artifact": selector,
            "candidate_only": True,
            "verification_decision_present": False,
            "release_authority": False,
        }
        records.append(
            DiscoveryCandidateRecord(
                record_id=candidate_record_id(record_payload),
                **record_payload,
            )
        )
    return tuple(records)


def materialize_entity_challenger_mentions(
    revision: SourceRevision,
    chunk: DiscoveryChunk,
    drafts: Sequence[EntityChallengerDraft],
    *,
    challenger_id: str,
    challenger_version: str,
) -> tuple[EntityChallengerRecord, ...]:
    revision = _revalidate_source_revision(revision)
    chunk = _revalidate_chunk(chunk)
    require_non_blank(challenger_id, "challenger_id")
    require_non_blank(challenger_version, "challenger_version")
    resolver = EvidenceSelectorResolver(revision)
    records: list[EntityChallengerRecord] = []
    for index, raw_draft in enumerate(drafts):
        draft = EntityChallengerDraft.model_validate(raw_draft)
        _ensure_chunk_segment(revision, chunk, draft.segment_id)
        payload: dict[str, Any] = {
            "channel": "entity_challenger",
            "challenger_id": challenger_id,
            "challenger_version": challenger_version,
            "chunk_id": chunk.chunk_id,
            "segment_id": draft.segment_id,
            "entity_type": draft.entity_type,
            "surface": draft.surface,
            "quote_sha256": sha256_utf8(draft.quote_exact),
            "role": draft.role,
            "attributes": draft.attributes,
            "mention_only": True,
            "can_assert_relationship": False,
            "can_release_fact": False,
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        mention_id = entity_record_id(payload)
        evidence_id = canonical_id(
            "evv1", {"subject_ref": mention_id, "response_index": index}
        )
        payload["selector_artifact"] = _selector_for_quote(
            revision,
            resolver=resolver,
            subject_ref=mention_id,
            evidence_id=evidence_id,
            segment_id=draft.segment_id,
            quote_exact=draft.quote_exact,
            quote_prefix=draft.quote_prefix,
            quote_suffix=draft.quote_suffix,
        )
        records.append(EntityChallengerRecord(mention_id=mention_id, **payload))
    return tuple(records)


def build_discovery_manifest(
    *,
    chunk_plan: ChunkPlan,
    transmitted_system_prompt: str,
    model_id: str,
    model_digest: str,
    provider: str,
    quantization: str,
    tokenizer_revision: str,
    tokenizer_sha256: str,
    chat_template_revision: str,
    chat_template_sha256: str,
    runtime_id: str,
    runtime_digest: str,
    decoding_config: Mapping[str, JsonValue],
    retry_policy: RetryPolicy,
    source_module_hashes: Mapping[str, str],
    git_revision: str,
    git_dirty: bool,
    git_untracked: bool,
    challenger_id: str | None = None,
    challenger_version: str | None = None,
    challenger_digest: str | None = None,
) -> DiscoveryRunManifest:
    """Record the exact effective prompt and all replay-critical T3 metadata."""

    chunk_plan = _revalidate_chunk_plan(chunk_plan)
    if not transmitted_system_prompt.strip():
        raise DiscoveryError("transmitted system prompt must be non-blank")
    return DiscoveryRunManifest(
        base_system_prompt_sha256=sha256_utf8(DISCOVERY_SYSTEM_PROMPT),
        transmitted_system_prompt_sha256=sha256_utf8(transmitted_system_prompt),
        response_schema_sha256=discovery_response_schema_sha256(),
        model_id=model_id,
        model_digest=model_digest,
        provider=provider,
        quantization=quantization,
        effective_context_tokens=chunk_plan.config.max_context_tokens,
        tokenizer_revision=tokenizer_revision,
        tokenizer_sha256=tokenizer_sha256,
        chat_template_revision=chat_template_revision,
        chat_template_sha256=chat_template_sha256,
        runtime_id=runtime_id,
        runtime_digest=runtime_digest,
        decoding_config=dict(decoding_config),
        retry_policy=retry_policy,
        chunk_plan_id=chunk_plan.plan_id,
        chunk_plan_sha256=chunk_plan.plan_sha256,
        chunk_token_estimates={
            item.chunk_id: item.context_token_estimate for item in chunk_plan.chunks
        },
        detector_registry_sha256=detector_registry_sha256(),
        challenger_id=challenger_id,
        challenger_version=challenger_version,
        challenger_digest=challenger_digest,
        source_module_hashes=dict(source_module_hashes),
        git_revision=git_revision,
        git_dirty=git_dirty,
        git_untracked=git_untracked,
    )


def verify_discovery_batch(
    batch: DiscoveryBatch | Mapping[str, Any],
    revision: SourceRevision,
) -> VerifiedDiscoveryBatch:
    """Replay every T3 selector and reject forged or cross-source artifacts."""

    revision = _revalidate_source_revision(revision)
    try:
        raw_json = (
            batch.model_dump_json(exclude_none=True)
            if isinstance(batch, DiscoveryBatch)
            else json.dumps(batch, ensure_ascii=False, allow_nan=False)
        )
        resolved = DiscoveryBatch.model_validate_json(raw_json)
    except (TypeError, ValueError, ValidationError) as exc:
        raise DiscoveryError("invalid discovery batch artifact") from exc
    verify_chunk_plan(resolved.chunk_plan, revision)
    if resolved.scope != revision.scope:
        raise DiscoveryError("discovery batch crosses source/case/file scope")
    if resolved.source_revision_id != revision.source_revision_id or (
        resolved.source_revision_sha256 != revision.canonical_sha256
    ):
        raise DiscoveryError("discovery batch source revision mismatch")
    if resolved.manifest.base_system_prompt_sha256 != sha256_utf8(
        DISCOVERY_SYSTEM_PROMPT
    ):
        raise DiscoveryError("discovery manifest base prompt hash mismatch")
    if resolved.manifest.response_schema_sha256 != discovery_response_schema_sha256():
        raise DiscoveryError("discovery manifest response schema hash mismatch")
    if resolved.manifest.detector_registry_sha256 != detector_registry_sha256():
        raise DiscoveryError("discovery manifest detector registry hash mismatch")
    if (
        resolved.manifest.effective_context_tokens
        != resolved.chunk_plan.config.max_context_tokens
    ):
        raise DiscoveryError("discovery manifest effective context mismatch")
    expected_chunk_estimates = {
        item.chunk_id: item.context_token_estimate
        for item in resolved.chunk_plan.chunks
    }
    if resolved.manifest.chunk_token_estimates != expected_chunk_estimates:
        raise DiscoveryError("discovery manifest chunk token estimates mismatch")
    primary_segments_by_chunk = {
        item.chunk_id: set(item.primary_segment_ids)
        for item in resolved.chunk_plan.chunks
    }
    selector_resolver = EvidenceSelectorResolver(revision)
    for candidate_record in resolved.candidate_records:
        if any(
            selector.segment_id
            not in primary_segments_by_chunk[candidate_record.chunk_id]
            for selector in candidate_record.selector_artifact.selectors
        ):
            raise DiscoveryError(
                "candidate selector crosses its chunk primary output scope"
            )
        selector_resolver.verify_artifact(candidate_record.selector_artifact)
    for entity_record in resolved.entity_challenger_records:
        if any(
            selector.segment_id not in primary_segments_by_chunk[entity_record.chunk_id]
            for selector in entity_record.selector_artifact.selectors
        ):
            raise DiscoveryError(
                "entity selector crosses its chunk primary output scope"
            )
        selector_resolver.verify_artifact(entity_record.selector_artifact)
    return _seal_verified_discovery_batch(resolved)


def build_discovery_batch(
    *,
    revision: SourceRevision,
    chunk_plan: ChunkPlan,
    manifest: DiscoveryRunManifest,
    candidate_records: Sequence[DiscoveryCandidateRecord] = (),
    entity_challenger_records: Sequence[EntityChallengerRecord] = (),
) -> DiscoveryBatch:
    revision = _revalidate_source_revision(revision)
    chunk_plan = verify_chunk_plan(chunk_plan, revision)
    payload: dict[str, Any] = {
        "discovery_version": DISCOVERY_VERSION,
        "status": (
            "success"
            if candidate_records or entity_challenger_records
            else "no_candidates"
        ),
        "scope": revision.scope.model_dump(mode="json"),
        "source_revision_id": revision.source_revision_id,
        "source_revision_sha256": revision.canonical_sha256,
        "chunk_plan": chunk_plan,
        "candidate_records": tuple(candidate_records),
        "entity_challenger_records": tuple(entity_challenger_records),
        "manifest": manifest,
        "verification_decisions": None,
        "canonical_claims": None,
        "release_authority": False,
        "network_required": False,
    }
    batch_hash = discovery_batch_sha256(payload)
    return DiscoveryBatch(
        batch_id=f"discv1:{batch_hash}",
        batch_sha256=batch_hash,
        **payload,
    )


__all__ = [
    "ABLATION_MANIFEST_VERSION",
    "CHUNK_PLAN_VERSION",
    "DETECTOR_VERSION",
    "DISCOVERY_MANIFEST_VERSION",
    "DISCOVERY_PROMPT_VERSION",
    "DISCOVERY_RESPONSE_VERSION",
    "DISCOVERY_SYSTEM_PROMPT",
    "DISCOVERY_VERSION",
    "ChunkPlan",
    "ChunkPlannerConfig",
    "ChunkSegmentRef",
    "DetectedMention",
    "DiscoveryAblationArm",
    "DiscoveryAblationManifest",
    "DiscoveryBatch",
    "DiscoveryCandidateRecord",
    "DiscoveryChunk",
    "DiscoveryError",
    "DiscoveryMessage",
    "DiscoveryPromptEnvelope",
    "DiscoveryRunManifest",
    "EntityChallengerDraft",
    "EntityChallengerRecord",
    "LLMAtomicCandidateDraft",
    "LLMDiscoveryResponse",
    "LLMEntityMentionDraft",
    "RetryPolicy",
    "VerifiedDiscoveryBatch",
    "build_chunk_plan",
    "build_discovery_ablation_manifest",
    "build_discovery_batch",
    "build_discovery_manifest",
    "build_discovery_prompt",
    "detect_exact_mentions",
    "detector_registry_sha256",
    "discovery_response_schema_sha256",
    "discovery_candidate_id",
    "discovery_evidence_id",
    "estimate_tokens",
    "materialize_detector_candidates",
    "materialize_entity_challenger_mentions",
    "materialize_llm_candidates",
    "parse_llm_discovery_response",
    "verify_chunk_plan",
    "verify_discovery_batch",
]
