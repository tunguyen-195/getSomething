"""Strict, safe contracts shared by the durable multi-audio workflow."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.services.summarization.contracts import (
    DEFAULT_MULTI_SUMMARY_MAX_WORDS,
    DEFAULT_MULTI_SUMMARY_MIN_WORDS,
    DEFAULT_SUMMARY_TYPE,
    MIN_INVESTIGATION_SUMMARY_MAX_WORDS,
    SUMMARY_TYPE_VALUES,
    SummaryRequestOptions,
)


BATCH_MAX_FILES: Final[int] = 20
BATCH_MAX_FILE_BYTES: Final[int] = 100_000_000
BATCH_MAX_AGGREGATE_BYTES: Final[int] = 1_000_000_000
BATCH_IDEMPOTENCY_KEY_MAX_LENGTH: Final[int] = 128
BATCH_SAFE_ERROR_CODE_MAX_LENGTH: Final[int] = 80

AudioBatchStatus = Literal[
    "created",
    "queued",
    "processing",
    "partially_succeeded",
    "succeeded",
    "failed",
    "cancel_requested",
    "cancelled",
]
AudioBatchItemStatus = Literal[
    "uploaded",
    "queued",
    "transcribing",
    "transcribed",
    "failed",
    "cancel_requested",
    "cancelled",
]
AudioBatchSummaryType = Literal["brief", "detailed"]
AudioBatchSummaryVariantType = Literal[
    "brief", "detailed", "investigation", "forensic"
]
AudioBatchSummaryResultStatus = Literal[
    "queued", "processing", "succeeded", "failed", "cancelled"
]
AudioBatchSummaryJobStatus = Literal[
    "queued",
    "processing",
    "succeeded",
    "partially_succeeded",
    "failed",
    "cancel_requested",
    "cancelled",
]

_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_SAFE_ERROR_CODE_PATTERN = re.compile(r"^[A-Z0-9_]{1,80}$")


def _contains_unicode_control(value: str) -> bool:
    """Reject controls and invisible format/bidirectional override characters."""

    return any(unicodedata.category(character) in {"Cc", "Cf"} for character in value)


class AudioBatchContractError(ValueError):
    """Safe typed failure that never embeds filenames, keys, or provider details."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def normalize_batch_idempotency_key(value: object) -> str:
    """Normalize an opaque replay key without accepting controls or blank values."""

    if type(value) is not str:
        raise AudioBatchContractError(
            "INVALID_IDEMPOTENCY_KEY", "idempotency_key must be a string."
        )
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > BATCH_IDEMPOTENCY_KEY_MAX_LENGTH
        or _contains_unicode_control(normalized)
    ):
        raise AudioBatchContractError(
            "INVALID_IDEMPOTENCY_KEY",
            "idempotency_key must contain 1 to 128 non-control characters.",
        )
    return normalized


def normalize_audio_batch_id(value: object) -> str:
    """Require a canonical UUID4 without reflecting malformed input in failures."""

    if type(value) is not str:
        raise AudioBatchContractError(
            "INVALID_AUDIO_BATCH_ID", "batch_id must be a canonical UUID4."
        )
    try:
        resolved = UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise AudioBatchContractError(
            "INVALID_AUDIO_BATCH_ID", "batch_id must be a canonical UUID4."
        ) from exc
    if str(resolved) != value or resolved.version != 4:
        raise AudioBatchContractError(
            "INVALID_AUDIO_BATCH_ID", "batch_id must be a canonical UUID4."
        )
    return value


def _normalize_original_filename(value: object) -> str:
    if type(value) is not str:
        raise AudioBatchContractError(
            "INVALID_BATCH_FILENAME", "Each batch item requires a valid filename."
        )
    normalized = unicodedata.normalize("NFC", value).strip()
    if (
        not normalized
        or len(normalized) > 255
        or normalized in {".", ".."}
        or "/" in normalized
        or "\\" in normalized
        or ":" in normalized
        or _contains_unicode_control(normalized)
    ):
        raise AudioBatchContractError(
            "INVALID_BATCH_FILENAME", "Each batch item requires a valid filename."
        )
    return normalized


def _safe_error_code(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not _SAFE_ERROR_CODE_PATTERN.fullmatch(value):
        raise AudioBatchContractError(
            "INVALID_BATCH_ERROR_CODE", "Batch error_code must be a safe code."
        )
    return value


class AudioBatchUploadOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    enable_diarization: bool = True
    diarization_method: Literal["none", "pyannote"] = "pyannote"
    language: str = Field(
        default="vi", min_length=2, max_length=16, pattern=r"^[A-Za-z-]+$"
    )
    fast_mode: bool = False


class AudioBatchFileDescriptor(BaseModel):
    """Metadata produced only after existing streaming audio validation succeeds."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    original_filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0, le=BATCH_MAX_FILE_BYTES)
    verified_audio_sha256: str = Field(min_length=64, max_length=64)

    @field_validator("original_filename", mode="before")
    @classmethod
    def validate_filename(cls, value: object) -> str:
        return _normalize_original_filename(value)

    @field_validator("verified_audio_sha256", mode="before")
    @classmethod
    def validate_sha256(cls, value: object) -> str:
        if type(value) is not str or not _SHA256_PATTERN.fullmatch(value):
            raise AudioBatchContractError(
                "INVALID_AUDIO_SHA256",
                "verified_audio_sha256 must be a SHA-256 digest.",
            )
        return value.lower()


class AudioBatchCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    case_id: int = Field(gt=0)
    idempotency_key: str = Field(
        min_length=1, max_length=BATCH_IDEMPOTENCY_KEY_MAX_LENGTH
    )
    files: list[AudioBatchFileDescriptor] = Field(
        min_length=1, max_length=BATCH_MAX_FILES
    )
    upload_options: AudioBatchUploadOptions = Field(
        default_factory=AudioBatchUploadOptions
    )

    @field_validator("idempotency_key", mode="before")
    @classmethod
    def validate_idempotency_key(cls, value: object) -> str:
        return normalize_batch_idempotency_key(value)

    @model_validator(mode="after")
    def validate_batch_limits(self) -> "AudioBatchCreateRequest":
        duplicate_keys = [
            unicodedata.normalize("NFKC", item.original_filename).casefold()
            for item in self.files
        ]
        if len(duplicate_keys) != len(set(duplicate_keys)):
            raise AudioBatchContractError(
                "DUPLICATE_BATCH_FILENAME",
                "A batch cannot contain duplicate filenames.",
            )
        if sum(item.size_bytes for item in self.files) > BATCH_MAX_AGGREGATE_BYTES:
            raise AudioBatchContractError(
                "BATCH_AGGREGATE_SIZE_EXCEEDED",
                "Batch audio bytes exceed the 1 GB aggregate limit.",
            )
        return self

    @property
    def total_size_bytes(self) -> int:
        return sum(item.size_bytes for item in self.files)


class AudioBatchItemBinding(BaseModel):
    """Internal binding created after Task and AudioFile rows are durable."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    task_id: str = Field(min_length=1, max_length=255)
    audio_id: int = Field(gt=0)


class AudioBatchItemResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, str_strip_whitespace=True, from_attributes=True
    )

    id: int = Field(gt=0)
    position: int = Field(ge=0)
    task_id: str = Field(min_length=1, max_length=255)
    audio_id: int = Field(gt=0)
    original_filename: str = Field(min_length=1, max_length=255)
    status: AudioBatchItemStatus
    error_code: str | None = Field(
        default=None, max_length=BATCH_SAFE_ERROR_CODE_MAX_LENGTH
    )
    celery_task_id: str | None = Field(default=None, max_length=255)
    created_at: datetime
    updated_at: datetime

    @field_validator("error_code", mode="before")
    @classmethod
    def validate_error_code(cls, value: object) -> str | None:
        return _safe_error_code(value)


class AudioBatchResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, str_strip_whitespace=True, from_attributes=True
    )

    id: str = Field(min_length=36, max_length=36)
    case_id: int = Field(gt=0)
    status: AudioBatchStatus
    requested_count: int = Field(gt=0, le=BATCH_MAX_FILES)
    completed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    cancelled_count: int = Field(ge=0)
    total_size_bytes: int = Field(ge=0, le=BATCH_MAX_AGGREGATE_BYTES)
    error_code: str | None = Field(
        default=None, max_length=BATCH_SAFE_ERROR_CODE_MAX_LENGTH
    )
    created_at: datetime
    updated_at: datetime
    items: list[AudioBatchItemResponse] = Field(max_length=BATCH_MAX_FILES)

    @field_validator("id", mode="before")
    @classmethod
    def validate_batch_id(cls, value: object) -> str:
        return normalize_audio_batch_id(value)

    @field_validator("error_code", mode="before")
    @classmethod
    def validate_error_code(cls, value: object) -> str | None:
        return _safe_error_code(value)

    @model_validator(mode="after")
    def validate_counts_and_order(self) -> "AudioBatchResponse":
        terminal_count = self.completed_count + self.failed_count + self.cancelled_count
        if terminal_count > self.requested_count:
            raise ValueError("terminal item counts exceed requested_count")
        if len(self.items) != self.requested_count:
            raise ValueError("item count must equal requested_count")
        if self.status == "succeeded" and (
            self.completed_count != self.requested_count
            or self.failed_count != 0
            or self.cancelled_count != 0
        ):
            raise ValueError("succeeded requires every requested item to complete")
        if self.status == "cancelled" and self.cancelled_count != self.requested_count:
            raise ValueError("cancelled requires every requested item to be cancelled")
        positions = [item.position for item in self.items]
        if positions != list(range(self.requested_count)):
            raise ValueError("batch items must have contiguous request-order positions")
        completed = sum(item.status == "transcribed" for item in self.items)
        failed = sum(item.status == "failed" for item in self.items)
        cancelled = sum(item.status == "cancelled" for item in self.items)
        if (
            completed != self.completed_count
            or failed != self.failed_count
            or cancelled != self.cancelled_count
        ):
            raise ValueError("batch counters must match item states")
        return self


class AudioBatchAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: AudioBatchStatus
    requested_count: int = Field(gt=0, le=BATCH_MAX_FILES)
    completed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    cancelled_count: int = Field(ge=0)


class AudioBatchTranscribeRequest(AudioBatchUploadOptions):
    """Explicit ordered subset plus options applied uniformly to selected items."""

    task_ids: list[str] = Field(min_length=1, max_length=BATCH_MAX_FILES)

    @field_validator("task_ids")
    @classmethod
    def validate_task_ids(cls, values: list[str]) -> list[str]:
        if any(
            type(value) is not str
            or not value.strip()
            or value != value.strip()
            or len(value) > 255
            or _contains_unicode_control(value)
            for value in values
        ):
            raise ValueError("task_ids must contain canonical non-empty task IDs")
        if len(values) != len(set(values)):
            raise ValueError("task_ids must not contain duplicates")
        return values


class AudioBatchSummaryRequest(SummaryRequestOptions):
    """Explicit ordered transcript selection for one merged summary job."""

    task_ids: list[str] = Field(min_length=1, max_length=BATCH_MAX_FILES)
    model_name: str | None = None
    summary_type: AudioBatchSummaryType = DEFAULT_SUMMARY_TYPE
    min_length: int = Field(default=DEFAULT_MULTI_SUMMARY_MIN_WORDS, ge=0)
    max_length: int = Field(default=DEFAULT_MULTI_SUMMARY_MAX_WORDS, ge=1)
    summary_types: list[AudioBatchSummaryVariantType] = Field(
        default_factory=list, max_length=4
    )

    @field_validator("task_ids")
    @classmethod
    def validate_task_ids(cls, values: list[str]) -> list[str]:
        if any(
            type(value) is not str
            or not value.strip()
            or value != value.strip()
            or len(value) > 255
            or _contains_unicode_control(value)
            for value in values
        ):
            raise ValueError("task_ids must contain canonical non-empty task IDs")
        if len(values) != len(set(values)):
            raise ValueError("task_ids must not contain duplicates")
        return values

    @field_validator("model_name", mode="before")
    @classmethod
    def normalize_model_name(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().casefold() == "auto":
            return None
        return value

    @field_validator("summary_types")
    @classmethod
    def validate_summary_types(
        cls, values: list[AudioBatchSummaryVariantType]
    ) -> list[AudioBatchSummaryVariantType]:
        if not values:
            return values
        if any(value not in SUMMARY_TYPE_VALUES for value in values):
            raise ValueError("summary_types contains an unsupported summary type")
        if len(values) != len(set(values)):
            raise ValueError("summary_types must not contain duplicates")
        return values

    @model_validator(mode="after")
    def normalize_legacy_summary_type(self) -> "AudioBatchSummaryRequest":
        # Older clients submit one summary_type.  Normalize it to the ordered
        # collection while retaining summary_type as the compatibility alias.
        if not self.summary_types:
            self.summary_types = [self.summary_type]
        else:
            if self.summary_types[0] in {"brief", "detailed"}:
                self.summary_type = self.summary_types[0]
        if (
            "investigation" in self.summary_types
            and self.length_mode == "manual"
            and self.max_length < MIN_INVESTIGATION_SUMMARY_MAX_WORDS
        ):
            raise ValueError(
                "investigation max_length must be at least "
                f"{MIN_INVESTIGATION_SUMMARY_MAX_WORDS}"
            )
        return self


class AudioBatchSummaryManifestItem(BaseModel):
    """Internal immutable binding revalidated by the summary worker."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    position: int = Field(ge=0, lt=BATCH_MAX_FILES)
    batch_item_id: int = Field(gt=0)
    task_id: str = Field(min_length=1, max_length=255)
    audio_id: int = Field(gt=0)
    filename: str = Field(min_length=1, max_length=255)
    transcript_sha256: str = Field(min_length=64, max_length=64)
    source_revision_id: str = Field(min_length=1, max_length=255)

    @field_validator("filename", mode="before")
    @classmethod
    def validate_filename(cls, value: object) -> str:
        return _normalize_original_filename(value)

    @field_validator("transcript_sha256", mode="before")
    @classmethod
    def validate_transcript_sha256(cls, value: object) -> str:
        if type(value) is not str or not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("transcript_sha256 must be a SHA-256 digest")
        return value.lower()


class AudioBatchSummarySourceResponse(BaseModel):
    """Public provenance projection without hashes or internal audio identifiers."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    position: int = Field(ge=0, lt=BATCH_MAX_FILES)
    task_id: str = Field(min_length=1, max_length=255)
    filename: str = Field(min_length=1, max_length=255)


class AudioBatchSafeErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    code: str = Field(pattern=r"^[A-Z0-9_]{1,80}$")
    message: str = Field(min_length=1, max_length=255)
    retryable: bool = False


class AudioBatchSummaryRuntimeResponse(BaseModel):
    """Allowlisted, reader-safe runtime metadata for one summary variant."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    prompt_version: str | None = Field(default=None, max_length=255)
    summary_generation: str | None = Field(default=None, max_length=80)
    provider: str | None = Field(default=None, max_length=80)
    llm_call_count: int | None = Field(default=None, ge=0)
    availability_attempts: int | None = Field(default=None, ge=0)
    user_prompt_applied: bool | None = None


class AudioBatchSummaryResultResponse(BaseModel):
    """One independently persisted summary variant in a merged job."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    summary_type: AudioBatchSummaryVariantType
    status: AudioBatchSummaryResultStatus
    summary: str | None = None
    summary_model: str | None = Field(default=None, max_length=255)
    runtime: AudioBatchSummaryRuntimeResponse | None = None
    error: AudioBatchSafeErrorResponse | None = None

    @model_validator(mode="after")
    def validate_result_terminal_projection(self) -> "AudioBatchSummaryResultResponse":
        if self.status == "succeeded" and not (self.summary or "").strip():
            raise ValueError("succeeded summary variants require summary text")
        if self.status != "succeeded" and self.summary is not None:
            raise ValueError("non-succeeded summary variants cannot expose summary text")
        return self


class AudioBatchSummaryJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    batch_id: str = Field(min_length=36, max_length=36)
    summary_job_id: str = Field(min_length=36, max_length=36)
    status: AudioBatchSummaryJobStatus
    summary_type: AudioBatchSummaryType
    summary: str | None = None
    summary_results: list[AudioBatchSummaryResultResponse] = Field(
        min_length=1, max_length=4
    )
    source_manifest: list[AudioBatchSummarySourceResponse] = Field(
        min_length=1, max_length=BATCH_MAX_FILES
    )
    user_prompt_applied: bool
    error: AudioBatchSafeErrorResponse | None = None

    @field_validator("batch_id", "summary_job_id", mode="before")
    @classmethod
    def validate_uuid(cls, value: object) -> str:
        return normalize_audio_batch_id(value)

    @model_validator(mode="after")
    def validate_terminal_projection(self) -> "AudioBatchSummaryJobResponse":
        if self.status == "succeeded" and not (self.summary or "").strip():
            raise ValueError("succeeded summary jobs require summary text")
        if self.status not in {"succeeded", "partially_succeeded"} and self.summary is not None:
            raise ValueError("non-succeeded summary jobs cannot expose summary text")
        if self.status == "succeeded" and not any(
            item.status == "succeeded" for item in self.summary_results
        ):
            raise ValueError("succeeded summary jobs require a successful variant")
        positions = [source.position for source in self.source_manifest]
        if positions != list(range(len(self.source_manifest))):
            raise ValueError("summary sources must retain contiguous selection order")
        return self


class AudioBatchAcceptedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    batch_id: str = Field(min_length=36, max_length=36)
    status: AudioBatchStatus

    @field_validator("batch_id", mode="before")
    @classmethod
    def validate_batch_id(cls, value: object) -> str:
        return normalize_audio_batch_id(value)


def canonical_batch_request_fingerprint(request: AudioBatchCreateRequest) -> str:
    """Hash normalized request content while keeping the replay key out of the hash."""

    payload = request.model_dump(mode="json", exclude={"idempotency_key"})
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def canonical_summary_source_manifest_sha256(
    manifest: list[AudioBatchSummaryManifestItem] | list[dict[str, object]],
) -> str:
    """Hash the strict ordered manifest identically at API and worker boundaries."""

    normalized = [
        (
            item.model_dump(mode="json")
            if isinstance(item, AudioBatchSummaryManifestItem)
            else AudioBatchSummaryManifestItem.model_validate(item).model_dump(
                mode="json"
            )
        )
        for item in manifest
    ]
    canonical = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def derive_audio_batch_aggregate(
    statuses: list[AudioBatchItemStatus],
) -> AudioBatchAggregate:
    """Derive one parent state without silently omitting failed/cancelled items."""

    if not statuses:
        raise AudioBatchContractError(
            "EMPTY_AUDIO_BATCH", "An audio batch must contain at least one item."
        )
    if len(statuses) > BATCH_MAX_FILES:
        raise AudioBatchContractError(
            "BATCH_FILE_COUNT_EXCEEDED", "An audio batch cannot exceed 20 items."
        )

    completed_count = statuses.count("transcribed")
    failed_count = statuses.count("failed")
    cancelled_count = statuses.count("cancelled")
    terminal = {"transcribed", "failed", "cancelled"}
    if all(status == "transcribed" for status in statuses):
        status: AudioBatchStatus = "succeeded"
    elif all(status == "cancelled" for status in statuses):
        status = "cancelled"
    elif all(item in terminal for item in statuses):
        status = "partially_succeeded" if completed_count else "failed"
    elif "cancel_requested" in statuses:
        status = "cancel_requested"
    elif any(item == "transcribing" for item in statuses):
        status = "processing"
    elif any(item == "queued" for item in statuses):
        status = "queued"
    else:
        status = "created"

    return AudioBatchAggregate(
        status=status,
        requested_count=len(statuses),
        completed_count=completed_count,
        failed_count=failed_count,
        cancelled_count=cancelled_count,
    )


__all__ = [
    "AudioBatchAggregate",
    "AudioBatchAcceptedResponse",
    "AudioBatchContractError",
    "AudioBatchCreateRequest",
    "AudioBatchFileDescriptor",
    "AudioBatchItemBinding",
    "AudioBatchItemResponse",
    "AudioBatchItemStatus",
    "AudioBatchResponse",
    "AudioBatchStatus",
    "AudioBatchSummaryJobResponse",
    "AudioBatchSummaryJobStatus",
    "AudioBatchSummaryResultResponse",
    "AudioBatchSummaryRuntimeResponse",
    "AudioBatchSummaryResultStatus",
    "AudioBatchSummaryVariantType",
    "AudioBatchSummaryManifestItem",
    "AudioBatchSummaryRequest",
    "AudioBatchSummarySourceResponse",
    "AudioBatchSafeErrorResponse",
    "AudioBatchTranscribeRequest",
    "AudioBatchUploadOptions",
    "BATCH_IDEMPOTENCY_KEY_MAX_LENGTH",
    "BATCH_MAX_AGGREGATE_BYTES",
    "BATCH_MAX_FILE_BYTES",
    "BATCH_MAX_FILES",
    "BATCH_SAFE_ERROR_CODE_MAX_LENGTH",
    "canonical_batch_request_fingerprint",
    "canonical_summary_source_manifest_sha256",
    "derive_audio_batch_aggregate",
    "normalize_audio_batch_id",
    "normalize_batch_idempotency_key",
]
