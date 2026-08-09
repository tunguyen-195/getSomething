"""Strict, immutable artifact contracts for T3 discovery."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import (
    Field,
    JsonValue,
    ValidationError,
    field_validator,
    model_validator,
)

from .contracts import canonical_json, sha256_utf8
from .discovery_common import (
    ABLATION_MANIFEST_VERSION,
    CHUNK_PLAN_VERSION,
    DETECTOR_VERSION,
    DISCOVERY_MANIFEST_VERSION,
    DISCOVERY_PROMPT_VERSION,
    DISCOVERY_RESPONSE_VERSION,
    DISCOVERY_REQUIRED_SOURCE_MODULES,
    DISCOVERY_VERSION,
    canonical_hash,
    canonical_id,
    reject_forbidden_keys,
    reject_sparse_payload,
    require_non_blank,
    validate_sha256,
)
from .evidence_selector import EvidenceSelectorArtifact
from .run_contracts import DiscoveryCandidate
from .source_revision import (
    ImmutableArtifact,
    SourceScope,
)

_MODEL_OWNED_AUTHORITY_KEYS = frozenset(
    {
        "candidate_id",
        "evidence_id",
        "evidence_refs",
        "epistemic_status",
        "hypothesis",
        "hypothesis_id",
        "projection_eligibility",
        "raw_char_end",
        "raw_char_start",
        "release_authority",
        "requires_human_verification",
        "risk",
        "risk_tier",
        "source_revision_id",
        "verification_action",
        "verification_decision",
        "verification_status",
    }
)
_ENTITY_RELATION_KEYS = frozenset(
    {
        "can_assert_relationship",
        "owner",
        "owner_id",
        "predicate",
        "relation",
        "relationship",
        "source_entity",
        "target_entity",
    }
)


class ChunkPlannerConfig(ImmutableArtifact):
    max_context_tokens: int = Field(ge=256)
    reserved_output_tokens: int = Field(ge=64)
    target_chunk_tokens: int = Field(ge=64)
    overlap_turns: int = Field(default=1, ge=0, le=8)
    chars_per_token: float = Field(default=2.8, gt=0.5, le=8.0)
    focus_hint_token_budget: int = Field(default=128, ge=0, le=2048)
    message_framing_tokens: int = Field(default=32, ge=0, le=256)
    oversized_segment_policy: Literal["reject", "singleton"] = "reject"

    @model_validator(mode="after")
    def validate_budget(self) -> "ChunkPlannerConfig":
        input_budget = self.max_context_tokens - self.reserved_output_tokens
        if input_budget < 64:
            raise ValueError("chunk planner input budget is too small")
        if self.target_chunk_tokens > input_budget:
            raise ValueError("target_chunk_tokens exceeds model input budget")
        if self.focus_hint_token_budget + self.message_framing_tokens >= input_budget:
            raise ValueError("prompt reserves exhaust the model input budget")
        return self

    @property
    def input_budget_tokens(self) -> int:
        return self.max_context_tokens - self.reserved_output_tokens


class ChunkSegmentRef(ImmutableArtifact):
    segment_id: str = Field(min_length=1)
    order_index: int = Field(ge=0)
    role: Literal["primary", "overlap_context"]


class DiscoveryChunk(ImmutableArtifact):
    chunk_id: str = Field(min_length=1)
    source_revision_id: str = Field(min_length=1)
    source_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_order: int = Field(ge=0)
    processing_rank: int = Field(ge=0)
    position_bucket: Literal["head", "middle", "tail", "full"]
    segment_refs: tuple[ChunkSegmentRef, ...] = Field(min_length=1)
    primary_segment_ids: tuple[str, ...] = Field(min_length=1)
    overlap_segment_ids: tuple[str, ...] = ()
    primary_raw_char_start: int = Field(ge=0)
    primary_raw_char_end: int = Field(gt=0)
    context_raw_char_start: int = Field(ge=0)
    context_raw_char_end: int = Field(gt=0)
    primary_token_estimate: int = Field(ge=1)
    context_token_estimate: int = Field(ge=1)
    oversized_single_segment: bool = False

    @model_validator(mode="after")
    def validate_chunk(self) -> "DiscoveryChunk":
        if self.primary_raw_char_end <= self.primary_raw_char_start:
            raise ValueError("primary chunk range must increase")
        if self.context_raw_char_end <= self.context_raw_char_start:
            raise ValueError("context chunk range must increase")
        if self.context_raw_char_start > self.primary_raw_char_start or (
            self.context_raw_char_end < self.primary_raw_char_end
        ):
            raise ValueError("context range must contain primary range")
        primary_refs = tuple(
            item.segment_id for item in self.segment_refs if item.role == "primary"
        )
        overlap_refs = tuple(
            item.segment_id
            for item in self.segment_refs
            if item.role == "overlap_context"
        )
        if primary_refs != self.primary_segment_ids:
            raise ValueError("primary segment refs are inconsistent")
        if overlap_refs != self.overlap_segment_ids:
            raise ValueError("overlap segment refs are inconsistent")
        if set(primary_refs) & set(overlap_refs):
            raise ValueError("a chunk segment cannot be primary and overlap")
        if self.context_token_estimate < self.primary_token_estimate:
            raise ValueError("context token estimate cannot be smaller than primary")
        if self.chunk_id != chunk_id(self):
            raise ValueError("chunk_id is not canonical")
        return self


class ChunkPlan(ImmutableArtifact):
    plan_version: Literal["investigation-chunk-plan-v1.0"] = CHUNK_PLAN_VERSION
    plan_id: str = Field(min_length=1)
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: SourceScope
    source_revision_id: str = Field(min_length=1)
    source_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_transcript_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config: ChunkPlannerConfig
    chunks: tuple[DiscoveryChunk, ...] = Field(min_length=1)
    segment_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    network_required: Literal[False] = False

    @model_validator(mode="after")
    def validate_plan(self) -> "ChunkPlan":
        if self.chunk_count != len(self.chunks):
            raise ValueError("chunk_count does not match chunks")
        if tuple(item.source_order for item in self.chunks) != tuple(
            range(len(self.chunks))
        ):
            raise ValueError("chunks must remain in source order")
        ranks = sorted(item.processing_rank for item in self.chunks)
        if ranks != list(range(len(self.chunks))):
            raise ValueError("processing ranks must form a complete permutation")
        primary_ids = [
            segment_id
            for chunk in self.chunks
            for segment_id in chunk.primary_segment_ids
        ]
        if len(primary_ids) != self.segment_count:
            raise ValueError("each source segment must be primary exactly once")
        if len(primary_ids) != len(set(primary_ids)):
            raise ValueError("source segments cannot be primary in multiple chunks")
        expected_hash = chunk_plan_sha256(self)
        if self.plan_sha256 != expected_hash:
            raise ValueError("chunk plan canonical hash mismatch")
        if self.plan_id != f"chnplanv1:{expected_hash}":
            raise ValueError("chunk plan ID is not canonical")
        return self


def _chunk_payload(chunk: DiscoveryChunk | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(chunk, DiscoveryChunk):
        payload = chunk.model_dump(mode="json")
    else:
        payload = dict(chunk)
    payload.pop("chunk_id", None)
    return payload


def chunk_id(chunk: DiscoveryChunk | Mapping[str, Any]) -> str:
    return canonical_id("chnv1", _chunk_payload(chunk))


def _chunk_plan_payload(plan: ChunkPlan | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(plan, ChunkPlan):
        payload = plan.model_dump(mode="json")
    else:
        payload = dict(plan)
    payload.pop("plan_id", None)
    payload.pop("plan_sha256", None)
    return payload


def chunk_plan_sha256(plan: ChunkPlan | Mapping[str, Any]) -> str:
    return canonical_hash(_chunk_plan_payload(plan))


class DiscoveryMessage(ImmutableArtifact):
    role: Literal["system", "user"]
    content: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_content_hash(self) -> "DiscoveryMessage":
        if self.content_sha256 != sha256_utf8(self.content):
            raise ValueError("discovery message hash mismatch")
        return self


class DiscoveryPromptEnvelope(ImmutableArtifact):
    prompt_version: Literal["adaptive-open-discovery-v1.0"] = DISCOVERY_PROMPT_VERSION
    chunk_id: str = Field(min_length=1)
    source_revision_id: str = Field(min_length=1)
    system_message: DiscoveryMessage
    user_message: DiscoveryMessage
    response_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transcript_is_untrusted_data: Literal[True] = True
    network_required: Literal[False] = False

    @model_validator(mode="after")
    def validate_roles(self) -> "DiscoveryPromptEnvelope":
        if self.system_message.role != "system" or self.user_message.role != "user":
            raise ValueError("discovery instruction and data roles are fixed")
        return self


class LLMAtomicCandidateDraft(ImmutableArtifact):
    candidate_kind: Literal["claim", "relationship"]
    claim_type: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    polarity: Literal[
        "affirmed", "negated", "uncertain", "reported", "quoted_instruction"
    ]
    segment_id: str = Field(min_length=1)
    quote_exact: str = Field(min_length=1)
    quote_prefix: str | None = Field(default=None, min_length=1)
    quote_suffix: str | None = Field(default=None, min_length=1)
    predicate: str | None = Field(default=None, min_length=1)
    source_surface: str | None = Field(default=None, min_length=1)
    target_surface: str | None = Field(default=None, min_length=1)
    attributes: dict[str, JsonValue] | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_sparse_values(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            reject_sparse_payload(
                {key: item for key, item in value.items() if item is not None}
            )
            reject_forbidden_keys(
                value.get("attributes"),
                _MODEL_OWNED_AUTHORITY_KEYS,
            )
        return value

    @model_validator(mode="after")
    def validate_candidate_kind(self) -> "LLMAtomicCandidateDraft":
        relationship_fields = (self.predicate, self.source_surface, self.target_surface)
        if self.candidate_kind == "relationship":
            if (
                self.predicate is None
                or self.source_surface is None
                or self.target_surface is None
            ):
                raise ValueError(
                    "relationship candidates require predicate and surfaces"
                )
            if self.source_surface not in self.quote_exact or (
                self.target_surface not in self.quote_exact
            ):
                raise ValueError(
                    "relationship surfaces must occur exactly in quote_exact"
                )
        elif any(item is not None for item in relationship_fields):
            raise ValueError("claim candidates cannot carry relationship fields")
        return self


class LLMEntityMentionDraft(ImmutableArtifact):
    entity_type: str = Field(min_length=1)
    surface: str = Field(min_length=1)
    segment_id: str = Field(min_length=1)
    quote_exact: str = Field(min_length=1)
    quote_prefix: str | None = Field(default=None, min_length=1)
    quote_suffix: str | None = Field(default=None, min_length=1)
    role: str | None = Field(default=None, min_length=1)
    attributes: dict[str, JsonValue] | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_sparse_values(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            reject_sparse_payload(
                {key: item for key, item in value.items() if item is not None}
            )
            reject_forbidden_keys(
                value.get("attributes"),
                _MODEL_OWNED_AUTHORITY_KEYS | _ENTITY_RELATION_KEYS,
            )
        return value

    @model_validator(mode="after")
    def bind_surface_to_quote(self) -> "LLMEntityMentionDraft":
        if self.surface not in self.quote_exact:
            raise ValueError("entity surface must occur exactly in quote_exact")
        return self


class LLMDiscoveryResponse(ImmutableArtifact):
    response_version: Literal[
        "adaptive-discovery-response-v1.0"
    ] = DISCOVERY_RESPONSE_VERSION
    candidates: tuple[LLMAtomicCandidateDraft, ...] = ()
    entity_mentions: tuple[LLMEntityMentionDraft, ...] = ()

    @model_validator(mode="after")
    def validate_unique_items(self) -> "LLMDiscoveryResponse":
        candidate_keys = [canonical_json(item) for item in self.candidates]
        entity_keys = [canonical_json(item) for item in self.entity_mentions]
        if len(candidate_keys) != len(set(candidate_keys)):
            raise ValueError("duplicate LLM discovery candidates")
        if len(entity_keys) != len(set(entity_keys)):
            raise ValueError("duplicate LLM entity mentions")
        return self


def discovery_response_schema_sha256() -> str:
    return canonical_hash(LLMDiscoveryResponse.model_json_schema())


class DetectedMention(ImmutableArtifact):
    mention_id: str = Field(min_length=1)
    detector_version: Literal["investigation-exact-detectors-v1.0"] = DETECTOR_VERSION
    detector_type: str = Field(min_length=1)
    detector_rule_id: str = Field(min_length=1)
    segment_id: str = Field(min_length=1)
    surface: str = Field(min_length=1)
    normalized: str | None = Field(default=None, min_length=1)
    raw_char_start: int = Field(ge=0)
    raw_char_end: int = Field(gt=0)
    segment_char_start: int = Field(ge=0)
    segment_char_end: int = Field(gt=0)
    cue: str | None = Field(default=None, min_length=1)
    ambiguous: bool = False
    candidate_only: Literal[True] = True
    infers_owner_or_relation: Literal[False] = False

    @model_validator(mode="after")
    def validate_mention(self) -> "DetectedMention":
        if self.raw_char_end <= self.raw_char_start:
            raise ValueError("detected raw range must increase")
        if self.segment_char_end <= self.segment_char_start:
            raise ValueError("detected segment range must increase")
        if self.mention_id != detected_mention_id(self):
            raise ValueError("detected mention ID is not canonical")
        return self


def _mention_payload(mention: DetectedMention | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(mention, DetectedMention):
        payload = mention.model_dump(mode="json", exclude_none=True)
    else:
        payload = dict(mention)
    payload.pop("mention_id", None)
    return payload


def detected_mention_id(mention: DetectedMention | Mapping[str, Any]) -> str:
    return canonical_id("detv1", _mention_payload(mention))


class DiscoveryCandidateRecord(ImmutableArtifact):
    record_id: str = Field(min_length=1)
    channel: Literal["llm_discovery", "exact_detector"]
    chunk_id: str = Field(min_length=1)
    candidate: DiscoveryCandidate
    selector_artifact: EvidenceSelectorArtifact
    candidate_only: Literal[True] = True
    verification_decision_present: Literal[False] = False
    release_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_record(self) -> "DiscoveryCandidateRecord":
        try:
            DiscoveryCandidate.model_validate_json(
                self.candidate.model_dump_json(exclude_none=True)
            )
            EvidenceSelectorArtifact.model_validate_json(
                self.selector_artifact.model_dump_json()
            )
        except ValidationError as exc:
            raise ValueError(
                "candidate record contains a forged nested artifact"
            ) from exc
        if self.selector_artifact.subject_kind != "verification":
            raise ValueError("candidate selectors must use verification subject kind")
        if self.selector_artifact.subject_ref != self.candidate.candidate_id:
            raise ValueError("candidate selector subject mismatch")
        if len(self.selector_artifact.selectors) != 1:
            raise ValueError(
                "discovery candidate requires exactly one evidence selector"
            )
        selector = self.selector_artifact.selectors[0]
        selector_ids = [item.evidence_id for item in self.selector_artifact.selectors]
        if selector_ids != self.candidate.evidence_refs:
            raise ValueError("candidate evidence refs do not match selector artifact")
        if self.candidate.epistemic_status != "fact":
            raise ValueError("T3 cannot materialize hypotheses or other reasoning")
        if self.candidate.risk_tier is not None:
            raise ValueError("T3 candidates cannot carry risk decisions")
        if self.candidate.requires_human_verification:
            raise ValueError("T3 cannot assign human-review policy")
        expected_candidate_id = discovery_candidate_id(
            source_revision_id=self.selector_artifact.source_revision_id,
            channel=self.channel,
            chunk_id=self.chunk_id,
            claim_type=self.candidate.claim_type,
            statement=self.candidate.statement,
            polarity=self.candidate.polarity,
            attributes=self.candidate.attributes,
            segment_id=selector.segment_id,
            quote_exact=selector.quote_exact,
        )
        if self.candidate.candidate_id != expected_candidate_id:
            raise ValueError(
                "candidate ID is not canonical for its evidence-bound content"
            )
        expected_evidence_id = discovery_evidence_id(
            candidate_id=self.candidate.candidate_id,
            segment_id=selector.segment_id,
            quote_exact=selector.quote_exact,
        )
        if selector.evidence_id != expected_evidence_id:
            raise ValueError("candidate evidence ID is not canonical")
        if self.record_id != candidate_record_id(self):
            raise ValueError("candidate record ID is not canonical")
        return self


def _candidate_record_payload(
    record: DiscoveryCandidateRecord | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(record, DiscoveryCandidateRecord):
        payload = record.model_dump(mode="json", exclude_none=True)
    else:
        payload = dict(record)
    payload.pop("record_id", None)
    return payload


def candidate_record_id(
    record: DiscoveryCandidateRecord | Mapping[str, Any],
) -> str:
    return canonical_id("drecv1", _candidate_record_payload(record))


def discovery_candidate_id(
    *,
    source_revision_id: str,
    channel: str,
    chunk_id: str,
    claim_type: str,
    statement: str,
    polarity: str,
    attributes: Mapping[str, JsonValue] | None,
    segment_id: str,
    quote_exact: str,
) -> str:
    return canonical_id(
        "candv1",
        {
            "source_revision_id": source_revision_id,
            "channel": channel,
            "chunk_id": chunk_id,
            "claim_type": claim_type,
            "statement": statement,
            "polarity": polarity,
            "attributes": dict(attributes or {}),
            "segment_id": segment_id,
            "quote_exact": quote_exact,
        },
    )


def discovery_evidence_id(
    *,
    candidate_id: str,
    segment_id: str,
    quote_exact: str,
) -> str:
    return canonical_id(
        "evv1",
        {
            "candidate_id": candidate_id,
            "segment_id": segment_id,
            "quote_exact": quote_exact,
        },
    )


class EntityChallengerDraft(ImmutableArtifact):
    entity_type: str = Field(min_length=1)
    surface: str = Field(min_length=1)
    segment_id: str = Field(min_length=1)
    quote_exact: str = Field(min_length=1)
    quote_prefix: str | None = Field(default=None, min_length=1)
    quote_suffix: str | None = Field(default=None, min_length=1)
    role: str | None = Field(default=None, min_length=1)
    attributes: dict[str, JsonValue] | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_sparse_values(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            reject_sparse_payload(
                {key: item for key, item in value.items() if item is not None}
            )
            reject_forbidden_keys(
                value.get("attributes"),
                _MODEL_OWNED_AUTHORITY_KEYS | _ENTITY_RELATION_KEYS,
            )
        return value

    @model_validator(mode="after")
    def bind_surface_to_quote(self) -> "EntityChallengerDraft":
        if self.surface not in self.quote_exact:
            raise ValueError("entity surface must occur exactly in quote_exact")
        return self


class EntityChallengerRecord(ImmutableArtifact):
    mention_id: str = Field(min_length=1)
    channel: Literal["entity_challenger"] = "entity_challenger"
    challenger_id: str = Field(min_length=1)
    challenger_version: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    segment_id: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    surface: str = Field(min_length=1)
    quote_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: str | None = Field(default=None, min_length=1)
    attributes: dict[str, JsonValue] | None = None
    selector_artifact: EvidenceSelectorArtifact
    mention_only: Literal[True] = True
    can_assert_relationship: Literal[False] = False
    can_release_fact: Literal[False] = False

    @model_validator(mode="after")
    def validate_entity_record(self) -> "EntityChallengerRecord":
        try:
            EvidenceSelectorArtifact.model_validate_json(
                self.selector_artifact.model_dump_json()
            )
        except ValidationError as exc:
            raise ValueError(
                "entity record contains a forged selector artifact"
            ) from exc
        if self.selector_artifact.subject_kind != "verification":
            raise ValueError("entity selector must use verification subject kind")
        if self.selector_artifact.subject_ref != self.mention_id:
            raise ValueError("entity selector subject mismatch")
        if len(self.selector_artifact.selectors) != 1:
            raise ValueError("entity mention requires exactly one evidence selector")
        selector = self.selector_artifact.selectors[0]
        if selector.segment_id != self.segment_id:
            raise ValueError("entity selector segment mismatch")
        if selector.quote_sha256 != self.quote_sha256:
            raise ValueError("entity selector quote hash mismatch")
        if self.mention_id != entity_record_id(self):
            raise ValueError("entity mention ID is not canonical")
        return self


def _entity_record_payload(
    record: EntityChallengerRecord | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(record, EntityChallengerRecord):
        payload = record.model_dump(mode="json", exclude_none=True)
    else:
        payload = dict(record)
    payload.pop("mention_id", None)
    payload.pop("selector_artifact", None)
    return payload


def entity_record_id(record: EntityChallengerRecord | Mapping[str, Any]) -> str:
    return canonical_id("entcandv1", _entity_record_payload(record))


class RetryPolicy(ImmutableArtifact):
    max_transport_retries: int = Field(default=1, ge=0, le=3)
    max_parse_retries: int = Field(default=1, ge=0, le=2)
    backoff_seconds: tuple[float, ...] = (0.25, 1.0)
    transcript_in_ordinary_logs: Literal[False] = False
    model_output_in_ordinary_logs: Literal[False] = False

    @field_validator("backoff_seconds")
    @classmethod
    def validate_backoff(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if any(item < 0 for item in value):
            raise ValueError("retry backoff cannot be negative")
        return value


class DiscoveryRunManifest(ImmutableArtifact):
    manifest_version: Literal[
        "adaptive-discovery-manifest-v1.0"
    ] = DISCOVERY_MANIFEST_VERSION
    prompt_version: Literal["adaptive-open-discovery-v1.0"] = DISCOVERY_PROMPT_VERSION
    base_system_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transmitted_system_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_id: str = Field(min_length=1)
    model_digest: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    quantization: str = Field(min_length=1)
    effective_context_tokens: int = Field(ge=256)
    tokenizer_revision: str = Field(min_length=1)
    tokenizer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chat_template_revision: str = Field(min_length=1)
    chat_template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_id: str = Field(min_length=1)
    runtime_digest: str = Field(min_length=1)
    decoding_config: dict[str, JsonValue]
    retry_policy: RetryPolicy
    chunk_plan_id: str = Field(min_length=1)
    chunk_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_token_estimates: dict[str, int] = Field(min_length=1)
    detector_version: Literal["investigation-exact-detectors-v1.0"] = DETECTOR_VERSION
    detector_registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    challenger_id: str | None = Field(default=None, min_length=1)
    challenger_version: str | None = Field(default=None, min_length=1)
    challenger_digest: str | None = Field(default=None, min_length=1)
    source_module_hashes: dict[str, str] = Field(min_length=1)
    git_revision: str = Field(min_length=1)
    git_dirty: bool
    git_untracked: bool
    network_required: Literal[False] = False

    @field_validator("decoding_config")
    @classmethod
    def validate_decoding_config(
        cls, value: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        if not value:
            raise ValueError("decoding_config must not be empty")
        reject_sparse_payload(value, "decoding_config")
        return value

    @field_validator("source_module_hashes")
    @classmethod
    def validate_source_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        for name, digest in value.items():
            require_non_blank(name, "source module name")
            validate_sha256(digest, "source module hash")
        missing = DISCOVERY_REQUIRED_SOURCE_MODULES - set(value)
        if missing:
            raise ValueError(
                "manifest is missing discovery source module hashes: "
                + ", ".join(sorted(missing))
            )
        return value

    @model_validator(mode="after")
    def validate_manifest(self) -> "DiscoveryRunManifest":
        if set(self.chunk_token_estimates) == set():
            raise ValueError("manifest requires chunk token estimates")
        if any(value < 1 for value in self.chunk_token_estimates.values()):
            raise ValueError("chunk token estimates must be positive")
        challenger = (
            self.challenger_id,
            self.challenger_version,
            self.challenger_digest,
        )
        if any(item is not None for item in challenger) and any(
            item is None for item in challenger
        ):
            raise ValueError("challenger manifest fields must be provided together")
        return self


class DiscoveryBatch(ImmutableArtifact):
    discovery_version: Literal["investigation-discovery-v1.0"] = DISCOVERY_VERSION
    batch_id: str = Field(min_length=1)
    batch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["success", "no_candidates"]
    scope: SourceScope
    source_revision_id: str = Field(min_length=1)
    source_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_plan: ChunkPlan
    candidate_records: tuple[DiscoveryCandidateRecord, ...] = ()
    entity_challenger_records: tuple[EntityChallengerRecord, ...] = ()
    manifest: DiscoveryRunManifest
    verification_decisions: Literal[None] = None
    canonical_claims: Literal[None] = None
    release_authority: Literal[False] = False
    network_required: Literal[False] = False

    @model_validator(mode="after")
    def validate_batch(self) -> "DiscoveryBatch":
        has_candidates = bool(self.candidate_records or self.entity_challenger_records)
        if (self.status == "success") != has_candidates:
            raise ValueError("discovery status does not match candidate presence")
        ids = [item.record_id for item in self.candidate_records] + [
            item.mention_id for item in self.entity_challenger_records
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("discovery batch IDs must be unique")
        chunk_ids = {item.chunk_id for item in self.chunk_plan.chunks}
        if any(item.chunk_id not in chunk_ids for item in self.candidate_records):
            raise ValueError("candidate record references an unknown chunk")
        if any(
            item.chunk_id not in chunk_ids for item in self.entity_challenger_records
        ):
            raise ValueError("entity challenger record references an unknown chunk")
        if self.manifest.chunk_plan_id != self.chunk_plan.plan_id or (
            self.manifest.chunk_plan_sha256 != self.chunk_plan.plan_sha256
        ):
            raise ValueError("discovery manifest does not bind the chunk plan")
        expected_hash = discovery_batch_sha256(self)
        if self.batch_sha256 != expected_hash:
            raise ValueError("discovery batch canonical hash mismatch")
        if self.batch_id != f"discv1:{expected_hash}":
            raise ValueError("discovery batch ID is not canonical")
        return self


_VERIFIED_DISCOVERY_AUTHORITY = object()


class VerifiedDiscoveryBatch:
    """Opaque proof that a T3 batch replayed against its immutable source."""

    _batch_json: str
    _sealed: bool
    __slots__ = ("_batch_json", "_sealed")

    def __init__(self, batch: DiscoveryBatch, *, _authority: object):
        if _authority is not _VERIFIED_DISCOVERY_AUTHORITY:
            raise TypeError("verified discovery batch requires internal authority")
        resolved = DiscoveryBatch.model_validate_json(
            batch.model_dump_json(exclude_none=True)
        )
        object.__setattr__(
            self,
            "_batch_json",
            resolved.model_dump_json(exclude_none=True),
        )
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("verified discovery batch is immutable")
        object.__setattr__(self, name, value)

    @property
    def batch(self) -> DiscoveryBatch:
        return DiscoveryBatch.model_validate_json(self._batch_json)


def _seal_verified_discovery_batch(batch: DiscoveryBatch) -> VerifiedDiscoveryBatch:
    return VerifiedDiscoveryBatch(
        batch,
        _authority=_VERIFIED_DISCOVERY_AUTHORITY,
    )


def _discovery_batch_payload(
    batch: DiscoveryBatch | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(batch, DiscoveryBatch):
        payload = batch.model_dump(mode="json", exclude_none=False)
    else:
        payload = dict(batch)
    payload.pop("batch_id", None)
    payload.pop("batch_sha256", None)
    return payload


def discovery_batch_sha256(batch: DiscoveryBatch | Mapping[str, Any]) -> str:
    return canonical_hash(_discovery_batch_payload(batch))


class DiscoveryAblationArm(ImmutableArtifact):
    arm_id: str = Field(min_length=1)
    discovery_schema: Literal["fixed_form", "open_schema"]
    context_strategy: Literal["one_shot", "turn_aware_chunks"]
    deterministic_detectors: bool
    entity_challenger: bool
    candidate_level_scoring: Literal[True] = True


class DiscoveryAblationManifest(ImmutableArtifact):
    manifest_version: Literal[
        "adaptive-discovery-ablation-v1.0"
    ] = ABLATION_MANIFEST_VERSION
    manifest_id: str = Field(min_length=1)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_id: str = Field(min_length=1)
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scorer_id: str = Field(min_length=1)
    scorer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_id: str = Field(min_length=1)
    model_digest: str = Field(min_length=1)
    runtime_digest: str = Field(min_length=1)
    effective_context_tokens: int = Field(ge=256)
    repetitions: int = Field(ge=1)
    decoding_config: dict[str, JsonValue]
    arms: tuple[DiscoveryAblationArm, ...] = Field(min_length=6, max_length=6)
    quality_claim_status: Literal[
        "not_claimed_without_locked_tier_a_human_corpus"
    ] = "not_claimed_without_locked_tier_a_human_corpus"
    network_required: Literal[False] = False

    @model_validator(mode="after")
    def validate_ablation(self) -> "DiscoveryAblationManifest":
        if len({item.arm_id for item in self.arms}) != len(self.arms):
            raise ValueError("ablation arm IDs must be unique")
        expected = ablation_manifest_sha256(self)
        if self.manifest_sha256 != expected:
            raise ValueError("ablation manifest canonical hash mismatch")
        if self.manifest_id != f"discablv1:{expected}":
            raise ValueError("ablation manifest ID is not canonical")
        return self


def _ablation_manifest_payload(
    manifest: DiscoveryAblationManifest | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(manifest, DiscoveryAblationManifest):
        payload = manifest.model_dump(mode="json")
    else:
        payload = dict(manifest)
    payload.pop("manifest_id", None)
    payload.pop("manifest_sha256", None)
    return payload


def ablation_manifest_sha256(
    manifest: DiscoveryAblationManifest | Mapping[str, Any],
) -> str:
    return canonical_hash(_ablation_manifest_payload(manifest))


def build_discovery_ablation_manifest(
    *,
    dataset_id: str,
    dataset_sha256: str,
    scorer_id: str,
    scorer_sha256: str,
    model_id: str,
    model_digest: str,
    runtime_digest: str,
    effective_context_tokens: int,
    repetitions: int,
    decoding_config: Mapping[str, JsonValue],
) -> DiscoveryAblationManifest:
    arms = (
        DiscoveryAblationArm(
            arm_id="fixed-one-shot-llm",
            discovery_schema="fixed_form",
            context_strategy="one_shot",
            deterministic_detectors=False,
            entity_challenger=False,
        ),
        DiscoveryAblationArm(
            arm_id="open-one-shot-llm",
            discovery_schema="open_schema",
            context_strategy="one_shot",
            deterministic_detectors=False,
            entity_challenger=False,
        ),
        DiscoveryAblationArm(
            arm_id="open-chunked-llm",
            discovery_schema="open_schema",
            context_strategy="turn_aware_chunks",
            deterministic_detectors=False,
            entity_challenger=False,
        ),
        DiscoveryAblationArm(
            arm_id="open-chunked-detectors",
            discovery_schema="open_schema",
            context_strategy="turn_aware_chunks",
            deterministic_detectors=True,
            entity_challenger=False,
        ),
        DiscoveryAblationArm(
            arm_id="open-chunked-entity",
            discovery_schema="open_schema",
            context_strategy="turn_aware_chunks",
            deterministic_detectors=False,
            entity_challenger=True,
        ),
        DiscoveryAblationArm(
            arm_id="open-chunked-all",
            discovery_schema="open_schema",
            context_strategy="turn_aware_chunks",
            deterministic_detectors=True,
            entity_challenger=True,
        ),
    )
    payload: dict[str, Any] = {
        "manifest_version": ABLATION_MANIFEST_VERSION,
        "dataset_id": dataset_id,
        "dataset_sha256": dataset_sha256,
        "scorer_id": scorer_id,
        "scorer_sha256": scorer_sha256,
        "model_id": model_id,
        "model_digest": model_digest,
        "runtime_digest": runtime_digest,
        "effective_context_tokens": effective_context_tokens,
        "repetitions": repetitions,
        "decoding_config": dict(decoding_config),
        "arms": arms,
        "quality_claim_status": "not_claimed_without_locked_tier_a_human_corpus",
        "network_required": False,
    }
    manifest_hash = ablation_manifest_sha256(payload)
    return DiscoveryAblationManifest(
        manifest_id=f"discablv1:{manifest_hash}",
        manifest_sha256=manifest_hash,
        **payload,
    )


__all__ = [
    "ChunkPlan",
    "ChunkPlannerConfig",
    "ChunkSegmentRef",
    "DetectedMention",
    "DiscoveryAblationArm",
    "DiscoveryAblationManifest",
    "DiscoveryBatch",
    "DiscoveryCandidateRecord",
    "DiscoveryChunk",
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
    "ablation_manifest_sha256",
    "build_discovery_ablation_manifest",
    "candidate_record_id",
    "chunk_id",
    "chunk_plan_sha256",
    "detected_mention_id",
    "discovery_batch_sha256",
    "discovery_candidate_id",
    "discovery_evidence_id",
    "discovery_response_schema_sha256",
    "entity_record_id",
]
