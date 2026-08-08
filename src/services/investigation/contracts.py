"""Canonical adaptive evidence contract shared by Summary and Analysis.

The contract fixes safety, provenance, references, and reproducibility while
leaving claim/concept vocabularies and sparse ``attributes`` open. It is the
single target shape for future Summary and Analysis paths; legacy adapters are
intentionally out of scope for this module.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from typing import Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

ADAPTIVE_CONTRACT_VERSION: Literal["adaptive-summary-analysis-v1.0"] = (
    "adaptive-summary-analysis-v1.0"
)
ADAPTIVE_MANIFEST_VERSION: Literal["adaptive-run-manifest-v1.0"] = (
    "adaptive-run-manifest-v1.0"
)
ADAPTIVE_DISCOVERY_PROMPT_VERSION: Literal["adaptive-open-discovery-v1.0"] = (
    "adaptive-open-discovery-v1.0"
)

_FILLER_VALUES = {
    "không có thông tin",
    "cần xác minh thêm",
}
_DROP = object()


def _normalized_filler_candidate(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).casefold()


def _is_sparse_invalid(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        normalized = _normalized_filler_candidate(value)
        return not normalized or normalized in _FILLER_VALUES
    if isinstance(value, Mapping):
        return not value
    if isinstance(value, (list, tuple, set, frozenset)):
        return not value
    return False


def _sanitize_sparse(
    value: Any,
    path: tuple[str, ...] = (),
    allowed_empty_paths: frozenset[tuple[str, ...]] = frozenset(),
) -> Any:
    if path in allowed_empty_paths and isinstance(value, (list, tuple)) and not value:
        return []
    if _is_sparse_invalid(value):
        return _DROP
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key)
            sanitized = _sanitize_sparse(
                item,
                (*path, normalized_key),
                allowed_empty_paths,
            )
            if sanitized is not _DROP:
                cleaned[normalized_key] = sanitized
        return cleaned if cleaned else _DROP
    if isinstance(value, (list, tuple, set, frozenset)):
        cleaned_items = []
        for index, item in enumerate(value):
            sanitized = _sanitize_sparse(
                item,
                (*path, str(index)),
                allowed_empty_paths,
            )
            if sanitized is not _DROP:
                cleaned_items.append(sanitized)
        return cleaned_items if cleaned_items else _DROP
    return value


def sanitize_sparse_payload(value: Any) -> Any:
    """Remove sparse filler recursively while preserving meaningful falsy values.

    ``0``, ``False``, negation labels, and verification labels are retained.
    At validation boundaries the canonical models reject these dirty values so
    model output cannot be silently repaired before release.
    """

    sanitized = _sanitize_sparse(value)
    return None if sanitized is _DROP else sanitized


def _invalid_sparse_paths(
    value: Any,
    path: tuple[str, ...] = (),
    allowed_empty_paths: frozenset[tuple[str, ...]] = frozenset(),
) -> list[str]:
    if path in allowed_empty_paths and isinstance(value, (list, tuple)) and not value:
        return []
    if _is_sparse_invalid(value):
        return [".".join(path) or "<root>"]

    invalid: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            invalid.extend(
                _invalid_sparse_paths(
                    item,
                    (*path, str(key)),
                    allowed_empty_paths,
                )
            )
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            invalid.extend(
                _invalid_sparse_paths(
                    item,
                    (*path, str(index)),
                    allowed_empty_paths,
                )
            )
    return invalid


def sha256_utf8(value: str) -> str:
    """Hash the exact UTF-8 bytes without Unicode or whitespace normalization."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    """Serialize JSON deterministically for cross-process hashes."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=True)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_canonical_json(value: Any) -> str:
    return sha256_utf8(canonical_json(value))


def hash_source_modules(sources: Mapping[str, str | bytes]) -> dict[str, str]:
    """Hash exact source-module bytes for an immutable run manifest."""

    hashes: dict[str, str] = {}
    for name in sorted(sources):
        if not name or not name.strip():
            raise ValueError("source module names must be non-blank")
        content = sources[name]
        encoded = (
            content.encode("utf-8") if isinstance(content, str) else bytes(content)
        )
        hashes[name] = hashlib.sha256(encoded).hexdigest()
    return hashes


def _ensure_unique(values: list[str], label: str) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must not contain duplicates")
    return values


class StrictEnvelope(BaseModel):
    """Reject undeclared envelope fields and dirty sparse values."""

    model_config = ConfigDict(
        extra="forbid",
        protected_namespaces=(),
        allow_inf_nan=False,
    )
    _allowed_empty_paths: ClassVar[frozenset[tuple[str, ...]]] = frozenset()

    @classmethod
    def _allowed_sparse_empty_paths(cls, value: Any) -> frozenset[tuple[str, ...]]:
        return cls._allowed_empty_paths

    @model_validator(mode="before")
    @classmethod
    def reject_sparse_invalid_values(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            invalid = _invalid_sparse_paths(
                value,
                allowed_empty_paths=cls._allowed_sparse_empty_paths(value),
            )
            if invalid:
                rendered = ", ".join(invalid[:8])
                raise ValueError(
                    f"null, blank, empty, or filler values are forbidden: {rendered}"
                )
        return value

    def model_dump_sparse(self) -> dict[str, Any]:
        dumped = self.model_dump(mode="json", exclude_none=True)
        sanitized = _sanitize_sparse(
            dumped,
            allowed_empty_paths=self._allowed_sparse_empty_paths(dumped),
        )
        return sanitized if isinstance(sanitized, dict) else {}


Sha256Hex = str


class EvidenceSpan(StrictEnvelope):
    evidence_id: str = Field(min_length=1)
    segment_id: str = Field(min_length=1)
    quote_exact: str = Field(min_length=1)
    quote_prefix: str | None = Field(default=None, min_length=1)
    quote_suffix: str | None = Field(default=None, min_length=1)
    raw_char_start: int | None = Field(default=None, ge=0)
    raw_char_end: int | None = Field(default=None, ge=0)
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    speaker_id: str | None = Field(default=None, min_length=1)
    quote_sha256: Sha256Hex = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: Sha256Hex = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_ranges(self) -> "EvidenceSpan":
        if (self.raw_char_start is None) != (self.raw_char_end is None):
            raise ValueError("raw character offsets must be provided together")
        if (
            self.raw_char_start is not None
            and self.raw_char_end is not None
            and self.raw_char_end <= self.raw_char_start
        ):
            raise ValueError("raw_char_end must be greater than raw_char_start")
        if (self.start_seconds is None) != (self.end_seconds is None):
            raise ValueError("audio timestamps must be provided together")
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds <= self.start_seconds
        ):
            raise ValueError("end_seconds must be greater than start_seconds")
        return self


class ConceptMention(StrictEnvelope):
    concept_id: str = Field(min_length=1)
    concept_type: str = Field(min_length=1)
    surface: str = Field(min_length=1)
    role: str | None = Field(default=None, min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    attributes: dict[str, JsonValue] | None = None

    @field_validator("evidence_refs")
    @classmethod
    def unique_evidence_refs(cls, values: list[str]) -> list[str]:
        return _ensure_unique(values, "concept evidence_refs")


class GroundedClaim(StrictEnvelope):
    claim_id: str = Field(min_length=1)
    claim_type: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    polarity: Literal[
        "affirmed", "negated", "uncertain", "reported", "quoted_instruction"
    ]
    disposition: Literal[
        "supported", "partially_supported", "contradicted", "unverifiable"
    ]
    epistemic_status: Literal["fact", "hypothesis"] = "fact"
    risk_tier: Literal["ordinary", "high_risk"] = "ordinary"
    requires_human_verification: bool = False
    evidence_refs: list[str] = Field(min_length=1)
    concept_refs: list[str] | None = None
    attributes: dict[str, JsonValue] | None = None

    @field_validator("evidence_refs", "concept_refs")
    @classmethod
    def unique_refs(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return _ensure_unique(values, "claim references")

    @model_validator(mode="after")
    def protect_high_risk_claims(self) -> "GroundedClaim":
        if self.risk_tier == "high_risk":
            if self.epistemic_status != "hypothesis":
                raise ValueError("high-risk claims must be represented as hypotheses")
            if not self.requires_human_verification:
                raise ValueError("high-risk hypotheses require human verification")
            if self.disposition not in {"supported", "partially_supported"}:
                raise ValueError("unsupported high-risk hypotheses cannot be released")
        return self


class GroundedRelationship(StrictEnvelope):
    relationship_id: str = Field(min_length=1)
    relationship_type: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    attributes: dict[str, JsonValue] | None = None

    @field_validator("evidence_refs")
    @classmethod
    def unique_evidence_refs(cls, values: list[str]) -> list[str]:
        return _ensure_unique(values, "relationship evidence_refs")

    @model_validator(mode="after")
    def reject_self_reference(self) -> "GroundedRelationship":
        if self.source_ref == self.target_ref:
            raise ValueError("relationship source_ref and target_ref must differ")
        return self


class AdaptiveTheme(StrictEnvelope):
    theme_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    claim_refs: list[str] = Field(min_length=1)
    attributes: dict[str, JsonValue] | None = None

    @field_validator("claim_refs")
    @classmethod
    def unique_claim_refs(cls, values: list[str]) -> list[str]:
        return _ensure_unique(values, "theme claim_refs")


class NarrativeSentence(StrictEnvelope):
    text: str = Field(min_length=1)
    sentence_kind: Literal["factual", "uncertainty"] = "factual"
    claim_refs: list[str] = Field(min_length=1)

    @field_validator("claim_refs")
    @classmethod
    def unique_claim_refs(cls, values: list[str]) -> list[str]:
        return _ensure_unique(values, "narrative claim_refs")


class ThematicNarrative(StrictEnvelope):
    theme_ref: str = Field(min_length=1)
    sentences: list[NarrativeSentence] = Field(min_length=1)


class NarrativeSynthesis(StrictEnvelope):
    overview: list[NarrativeSentence] = Field(min_length=1)
    thematic_groups: list[ThematicNarrative] | None = None


class SourceProvenance(StrictEnvelope):
    source_revision_id: str = Field(min_length=1)
    task_id: str | None = Field(default=None, min_length=1)
    audio_id: int | str | None = None
    audio_sha256: Sha256Hex | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    raw_transcript_sha256: Sha256Hex = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_transcript_sha256: Sha256Hex = Field(pattern=r"^[0-9a-f]{64}$")
    segment_count: int = Field(ge=0)
    asr_model_id: str | None = Field(default=None, min_length=1)
    diarization_model_id: str | None = Field(default=None, min_length=1)


class SafetyEnvelope(StrictEnvelope):
    transcript_is_untrusted_data: Literal[True] = True
    evidence_required_for_released_claims: Literal[True] = True
    high_risk_requires_human_verification: Literal[True] = True
    unsupported_high_risk_claims_released: Literal[False] = False


class RunManifest(StrictEnvelope):
    manifest_version: Literal["adaptive-run-manifest-v1.0"] = ADAPTIVE_MANIFEST_VERSION
    contract_version: Literal["adaptive-summary-analysis-v1.0"] = (
        ADAPTIVE_CONTRACT_VERSION
    )
    prompt_version: str = Field(min_length=1)
    prompt_sha256: Sha256Hex = Field(pattern=r"^[0-9a-f]{64}$")
    json_schema_sha256: Sha256Hex = Field(pattern=r"^[0-9a-f]{64}$")
    model_id: str = Field(min_length=1)
    model_digest: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    decoding_config: dict[str, JsonValue]
    source_module_hashes: dict[str, Sha256Hex] | None = None
    git_revision: str | None = Field(default=None, min_length=1)
    git_dirty: bool
    git_untracked: bool

    @field_validator("decoding_config")
    @classmethod
    def require_decoding_config(
        cls,
        value: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        if not value:
            raise ValueError("decoding_config must record at least one option")
        return value

    @field_validator("source_module_hashes")
    @classmethod
    def validate_source_module_hashes(
        cls,
        value: dict[str, Sha256Hex] | None,
    ) -> dict[str, Sha256Hex] | None:
        if value is None:
            return None
        for name, digest in value.items():
            if not name.strip():
                raise ValueError("source module hash keys must be non-blank")
            if len(digest) != 64 or any(
                char not in "0123456789abcdef" for char in digest
            ):
                raise ValueError("source module hashes must be lowercase SHA-256")
        return value


class AdaptiveSummaryAnalysisContract(StrictEnvelope):
    """Single canonical output model used by both Summary and Analysis."""

    schema_version: Literal["adaptive-summary-analysis-v1.0"] = (
        ADAPTIVE_CONTRACT_VERSION
    )
    run_status: Literal["success", "no_extractable_claims"]
    claims: list[GroundedClaim]
    evidence: list[EvidenceSpan] | None = None
    concepts: list[ConceptMention] | None = None
    relationships: list[GroundedRelationship] | None = None
    themes: list[AdaptiveTheme] | None = None
    narrative: NarrativeSynthesis | None = None
    provenance: SourceProvenance
    safety: SafetyEnvelope
    manifest: RunManifest

    @classmethod
    def _allowed_sparse_empty_paths(cls, value: Any) -> frozenset[tuple[str, ...]]:
        if (
            isinstance(value, Mapping)
            and value.get("run_status") == "no_extractable_claims"
        ):
            return frozenset({("claims",)})
        return frozenset()

    @model_validator(mode="after")
    def validate_graph(self) -> "AdaptiveSummaryAnalysisContract":
        if self.run_status == "no_extractable_claims":
            if self.claims:
                raise ValueError("no_extractable_claims requires claims=[]")
            if any(
                value is not None
                for value in (
                    self.evidence,
                    self.concepts,
                    self.relationships,
                    self.themes,
                    self.narrative,
                )
            ):
                raise ValueError(
                    "no_extractable_claims cannot include evidence, concepts, "
                    "relationships, themes, or narrative"
                )
            return self

        if not self.claims:
            raise ValueError("success requires at least one claim")
        if not self.evidence:
            raise ValueError("success requires evidence for released claims")

        collections: tuple[tuple[str, list[Any]], ...] = (
            ("claim", self.claims),
            ("evidence", self.evidence or []),
            ("concept", self.concepts or []),
            ("relationship", self.relationships or []),
            ("theme", self.themes or []),
        )
        identifier_fields = {
            "claim": "claim_id",
            "evidence": "evidence_id",
            "concept": "concept_id",
            "relationship": "relationship_id",
            "theme": "theme_id",
        }
        seen_ids: dict[str, str] = {}
        for label, items in collections:
            field_name = identifier_fields[label]
            for item in items:
                identifier = str(getattr(item, field_name))
                if identifier in seen_ids:
                    raise ValueError(
                        f"duplicate ID {identifier!r} in {label}; already used by "
                        f"{seen_ids[identifier]}"
                    )
                seen_ids[identifier] = label

        evidence_ids = {item.evidence_id for item in self.evidence or []}
        claim_ids = {item.claim_id for item in self.claims}
        concept_ids = {item.concept_id for item in self.concepts or []}
        node_ids = claim_ids | concept_ids
        theme_ids = {item.theme_id for item in self.themes or []}

        def require_refs(refs: list[str], available: set[str], label: str) -> None:
            missing = sorted(set(refs) - available)
            if missing:
                raise ValueError(f"dangling {label}: {', '.join(missing)}")

        for claim in self.claims:
            require_refs(claim.evidence_refs, evidence_ids, "claim evidence_refs")
            if claim.concept_refs:
                require_refs(claim.concept_refs, concept_ids, "claim concept_refs")
        for concept in self.concepts or []:
            require_refs(concept.evidence_refs, evidence_ids, "concept evidence_refs")
        for relationship in self.relationships or []:
            require_refs(
                [relationship.source_ref, relationship.target_ref],
                node_ids,
                "relationship node refs",
            )
            require_refs(
                relationship.evidence_refs,
                evidence_ids,
                "relationship evidence_refs",
            )

        primary_theme_claims: set[str] = set()
        for theme in self.themes or []:
            require_refs(theme.claim_refs, claim_ids, "theme claim_refs")
            duplicate_assignment = primary_theme_claims & set(theme.claim_refs)
            if duplicate_assignment:
                raise ValueError(
                    "claims cannot be assigned to multiple primary themes: "
                    + ", ".join(sorted(duplicate_assignment))
                )
            primary_theme_claims.update(theme.claim_refs)

        claim_by_id = {claim.claim_id: claim for claim in self.claims}
        if self.narrative:
            for sentence in self.narrative.overview:
                self._validate_narrative_sentence(sentence, claim_ids, claim_by_id)
            for group in self.narrative.thematic_groups or []:
                require_refs([group.theme_ref], theme_ids, "narrative theme refs")
                for sentence in group.sentences:
                    self._validate_narrative_sentence(sentence, claim_ids, claim_by_id)
        return self

    @staticmethod
    def _validate_narrative_sentence(
        sentence: NarrativeSentence,
        claim_ids: set[str],
        claim_by_id: dict[str, GroundedClaim],
    ) -> None:
        missing = sorted(set(sentence.claim_refs) - claim_ids)
        if missing:
            raise ValueError(f"dangling narrative claim_refs: {', '.join(missing)}")
        if sentence.sentence_kind != "factual":
            return
        for claim_ref in sentence.claim_refs:
            claim = claim_by_id[claim_ref]
            if claim.disposition not in {"supported", "partially_supported"}:
                raise ValueError("factual narrative cannot cite unsupported claims")
            if claim.risk_tier == "high_risk":
                raise ValueError(
                    "high-risk hypotheses cannot be released as factual narrative"
                )


# Summary and Analysis deliberately resolve to the same canonical Pydantic model.
AdaptiveSummaryContract = AdaptiveSummaryAnalysisContract
AdaptiveAnalysisContract = AdaptiveSummaryAnalysisContract


def adaptive_contract_json_schema() -> dict[str, Any]:
    """Return the canonical JSON schema accepted by local structured decoders."""

    return AdaptiveSummaryAnalysisContract.model_json_schema()


def adaptive_contract_schema_sha256() -> str:
    """Return a canonical schema SHA stable across interpreter processes."""

    return sha256_canonical_json(adaptive_contract_json_schema())


def build_run_manifest(
    *,
    prompt: str,
    prompt_version: str,
    model_id: str,
    model_digest: str,
    provider: str,
    decoding_config: Mapping[str, Any],
    source_module_hashes: Mapping[str, str] | None = None,
    git_revision: str | None = None,
    git_dirty: bool,
    git_untracked: bool,
) -> RunManifest:
    """Build a reproducible model/config/version manifest from exact inputs."""

    return RunManifest(
        prompt_version=prompt_version,
        prompt_sha256=sha256_utf8(prompt),
        json_schema_sha256=adaptive_contract_schema_sha256(),
        model_id=model_id,
        model_digest=model_digest,
        provider=provider,
        decoding_config=dict(decoding_config),
        source_module_hashes=(
            dict(source_module_hashes) if source_module_hashes else None
        ),
        git_revision=git_revision,
        git_dirty=git_dirty,
        git_untracked=git_untracked,
    )


def validate_adaptive_contract(value: Any) -> AdaptiveSummaryAnalysisContract:
    """Validate raw model output without silently sanitizing invalid sparse data."""

    if isinstance(value, str):
        return AdaptiveSummaryAnalysisContract.model_validate_json(value)
    return AdaptiveSummaryAnalysisContract.model_validate(value)


__all__ = [
    "ADAPTIVE_CONTRACT_VERSION",
    "ADAPTIVE_DISCOVERY_PROMPT_VERSION",
    "ADAPTIVE_MANIFEST_VERSION",
    "AdaptiveAnalysisContract",
    "AdaptiveSummaryAnalysisContract",
    "AdaptiveSummaryContract",
    "AdaptiveTheme",
    "ConceptMention",
    "EvidenceSpan",
    "GroundedClaim",
    "GroundedRelationship",
    "NarrativeSentence",
    "NarrativeSynthesis",
    "RunManifest",
    "SafetyEnvelope",
    "SourceProvenance",
    "ThematicNarrative",
    "adaptive_contract_json_schema",
    "adaptive_contract_schema_sha256",
    "build_run_manifest",
    "canonical_json",
    "hash_source_modules",
    "sanitize_sparse_payload",
    "sha256_canonical_json",
    "sha256_utf8",
    "validate_adaptive_contract",
]
