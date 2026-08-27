"""Shared request and output contracts for every summarization entry point."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .investigation_scenarios import (
    DEFAULT_INVESTIGATION_SCENARIO,
    InvestigationScenario,
    require_investigation_scenario,
)
from .adaptive_length import SummaryLengthMode


SummaryType = Literal["brief", "detailed", "investigation", "forensic"]
SUMMARY_TYPE_VALUES: Final[tuple[SummaryType, ...]] = (
    "brief",
    "detailed",
    "investigation",
    "forensic",
)
SUMMARY_TYPES = SUMMARY_TYPE_VALUES

DEFAULT_SUMMARY_TYPE: Final[SummaryType] = "detailed"
DEFAULT_SUMMARY_MIN_WORDS: Final[int] = 50
DEFAULT_SUMMARY_MAX_WORDS: Final[int] = 200
DEFAULT_MULTI_SUMMARY_MIN_WORDS: Final[int] = 100
DEFAULT_MULTI_SUMMARY_MAX_WORDS: Final[int] = 400
MIN_INVESTIGATION_SUMMARY_MAX_WORDS: Final[int] = 20
SUMMARY_USER_PROMPT_MAX_LENGTH: Final[int] = 2000

# Compatibility aliases for callers that used the first contract draft.
DEFAULT_SUMMARY_MIN_LENGTH = DEFAULT_SUMMARY_MIN_WORDS
DEFAULT_SUMMARY_MAX_LENGTH = DEFAULT_SUMMARY_MAX_WORDS


class SummaryRequestContractError(ValueError):
    """Typed request failure raised before task, GPU, or model work."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_error(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class UnsupportedSummaryType(SummaryRequestContractError):
    """Raised when a caller supplies a value outside the shared allowlist."""

    def __init__(self, value: object) -> None:
        self.value = value
        allowed = ", ".join(SUMMARY_TYPE_VALUES)
        super().__init__(
            "UNSUPPORTED_SUMMARY_TYPE",
            f"Unsupported summary_type {value!r}; allowed values: {allowed}",
        )


class InvalidSummaryLengthBounds(SummaryRequestContractError):
    """Raised when advisory/enforced word bounds cannot form a valid request."""

    def __init__(self) -> None:
        super().__init__(
            "INVALID_LENGTH_BOUNDS",
            "Summary word bounds require 0 <= min_length <= max_length and "
            "max_length >= 1",
        )


class InvestigationSummaryMaxTooSmall(SummaryRequestContractError):
    """Raised before model work when no complete investigation sentence can fit."""

    def __init__(self, maximum: int) -> None:
        super().__init__(
            "INVESTIGATION_MAX_LENGTH_TOO_SMALL",
            "Investigation summary max_length must be at least "
            f"{MIN_INVESTIGATION_SUMMARY_MAX_WORDS} words; received {maximum}.",
        )


class InvalidSummaryUserPrompt(SummaryRequestContractError):
    """Raised when an optional user preference cannot be accepted safely."""

    def __init__(self) -> None:
        super().__init__(
            "INVALID_SUMMARY_USER_PROMPT",
            "user_prompt must be a string of at most "
            f"{SUMMARY_USER_PROMPT_MAX_LENGTH} Unicode characters.",
        )


def normalize_summary_user_prompt(value: object) -> str | None:
    """Trim one request-scoped prompt and enforce its Unicode character limit."""

    if value is None:
        return None
    if type(value) is not str:
        raise InvalidSummaryUserPrompt()
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > SUMMARY_USER_PROMPT_MAX_LENGTH:
        raise InvalidSummaryUserPrompt()
    return normalized


class SummaryMaximumExceeded(ValueError):
    """Raised when final post-processed summary text exceeds the hard maximum."""

    def __init__(self, contract: dict[str, object]) -> None:
        self.contract = contract
        super().__init__(
            "Summary contains "
            f"{contract['actual']} words; maximum is {contract['maximum']}."
        )


class SummaryRequestOptions(BaseModel):
    """Canonical semantic options shared by HTTP, service, and worker callers."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
        protected_namespaces=(),
    )

    summary_type: SummaryType = DEFAULT_SUMMARY_TYPE
    length_mode: SummaryLengthMode = "auto"
    min_length: int = Field(default=DEFAULT_SUMMARY_MIN_WORDS, ge=0)
    max_length: int = Field(default=DEFAULT_SUMMARY_MAX_WORDS, ge=1)
    user_prompt: str | None = Field(
        default=None,
        max_length=SUMMARY_USER_PROMPT_MAX_LENGTH,
        description=(
            "Optional request-scoped focus or formatting preference, limited to "
            f"{SUMMARY_USER_PROMPT_MAX_LENGTH} Unicode characters."
        ),
    )

    @field_validator("user_prompt", mode="before")
    @classmethod
    def validate_user_prompt(cls, value: object) -> str | None:
        return normalize_summary_user_prompt(value)

    @model_validator(mode="after")
    def validate_length_order(self) -> "SummaryRequestOptions":
        if self.min_length > self.max_length:
            raise ValueError("min_length must be less than or equal to max_length")
        if (
            self.summary_type == "investigation"
            and self.length_mode == "manual"
            and self.max_length < MIN_INVESTIGATION_SUMMARY_MAX_WORDS
        ):
            raise ValueError(
                "investigation max_length must be at least "
                f"{MIN_INVESTIGATION_SUMMARY_MAX_WORDS}"
            )
        return self


class SummaryRequest(SummaryRequestOptions):
    """HTTP request shared by v2 and compatibility single-summary routes."""

    model_name: str | None = None
    include_context: bool = False
    async_mode: bool = True
    investigation_scenario: InvestigationScenario = DEFAULT_INVESTIGATION_SCENARIO

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_context_name(cls, value: Any) -> Any:
        if not isinstance(value, Mapping) or "include_context_analysis" not in value:
            return value
        normalized = dict(value)
        legacy_value = normalized.pop("include_context_analysis")
        if (
            "include_context" in normalized
            and normalized["include_context"] != legacy_value
        ):
            raise ValueError(
                "include_context and include_context_analysis must not conflict"
            )
        normalized["include_context"] = legacy_value
        return normalized

    @field_validator("model_name", mode="before")
    @classmethod
    def normalize_model_name(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().casefold() == "auto":
            return None
        return value

    @field_validator("investigation_scenario", mode="before")
    @classmethod
    def validate_investigation_scenario(cls, value: Any) -> InvestigationScenario:
        return require_investigation_scenario(value)


class MultiSummaryRequest(SummaryRequestOptions):
    """Compatibility request for a transcript collection or an authorized case."""

    transcripts: list[str] = Field(default_factory=list)
    case_id: str | None = None
    model_name: str | None = None
    context_analysis: dict[str, Any] | None = None

    @field_validator("model_name", mode="before")
    @classmethod
    def normalize_model_name(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().casefold() == "auto":
            return None
        return value

    @field_validator("transcripts")
    @classmethod
    def validate_transcripts(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("transcripts must contain only non-empty strings")
        return values

    @model_validator(mode="after")
    def validate_source_and_release_mode(self) -> "MultiSummaryRequest":
        if not self.transcripts and not self.case_id:
            raise ValueError("transcripts or case_id is required")
        if self.summary_type == "investigation":
            raise ValueError(
                "investigation multi-summary requires a trusted released narrative"
            )
        return self


class CaseSummaryRequest(SummaryRequestOptions):
    """Compatibility request for summarizing all transcripts in one case."""

    case_id: str
    model_name: str | None = None
    context_analysis: dict[str, Any] | None = None

    @field_validator("model_name", mode="before")
    @classmethod
    def normalize_model_name(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().casefold() == "auto":
            return None
        return value

    @model_validator(mode="after")
    def reject_unreleased_investigation_mode(self) -> "CaseSummaryRequest":
        if self.summary_type == "investigation":
            raise ValueError(
                "investigation case summary requires a trusted released narrative"
            )
        return self


def require_summary_type(value: object) -> SummaryType:
    """Return a typed allowlisted value without coercion or fallback."""

    if type(value) is not str or value not in SUMMARY_TYPE_VALUES:
        raise UnsupportedSummaryType(value)
    return cast(SummaryType, value)


def validate_summary_length_bounds(min_length: int, max_length: int) -> None:
    """Validate request bounds; the minimum remains advisory for final output."""

    if (
        isinstance(min_length, bool)
        or isinstance(max_length, bool)
        or not isinstance(min_length, int)
        or not isinstance(max_length, int)
        or min_length < 0
        or max_length < 1
        or min_length > max_length
    ):
        raise InvalidSummaryLengthBounds()


def validate_summary_request_options(
    *,
    summary_type: object,
    min_length: int,
    max_length: int,
    length_mode: object = "manual",
    user_prompt: object = None,
) -> SummaryRequestOptions:
    """Validate direct calls before task lookup, GPU acquisition, or model work."""

    typed_summary_type = require_summary_type(summary_type)
    if type(length_mode) is not str and hasattr(length_mode, "default"):
        length_mode = getattr(length_mode, "default")
    if type(length_mode) is not str or length_mode not in {"auto", "manual"}:
        raise SummaryRequestContractError(
            "UNSUPPORTED_LENGTH_MODE",
            "length_mode must be 'auto' or 'manual'",
        )
    validate_summary_length_bounds(min_length, max_length)
    if (
        typed_summary_type == "investigation"
        and length_mode == "manual"
        and max_length < MIN_INVESTIGATION_SUMMARY_MAX_WORDS
    ):
        raise InvestigationSummaryMaxTooSmall(max_length)
    return SummaryRequestOptions(
        summary_type=typed_summary_type,
        length_mode=cast(SummaryLengthMode, length_mode),
        min_length=min_length,
        max_length=max_length,
        user_prompt=normalize_summary_user_prompt(user_prompt),
    )


def evaluate_summary_length(
    summary: str,
    *,
    min_length: int,
    max_length: int,
) -> dict[str, object]:
    """Evaluate final text with an advisory minimum and enforced maximum."""

    validate_summary_length_bounds(min_length, max_length)
    actual = len(summary.split())
    minimum_met = actual >= min_length
    maximum_met = actual <= max_length
    if not maximum_met:
        status = "maximum_exceeded"
    elif not minimum_met:
        status = "below_advisory_minimum"
    else:
        status = "within_requested_range"
    return {
        "schema_version": "summary-length-contract-v1",
        "unit": "whitespace_delimited_words",
        "minimum": min_length,
        "maximum": max_length,
        "actual": actual,
        "minimum_met": minimum_met,
        "maximum_met": maximum_met,
        "minimum_enforced": False,
        "maximum_enforced": True,
        "satisfied": maximum_met,
        "status": status,
    }


build_summary_length_contract = evaluate_summary_length


def enforce_summary_maximum(
    summary: str,
    *,
    min_length: int,
    max_length: int,
) -> dict[str, object]:
    """Return metadata or raise if the final summary exceeds its hard maximum."""

    contract = evaluate_summary_length(
        summary,
        min_length=min_length,
        max_length=max_length,
    )
    if not contract["maximum_met"]:
        raise SummaryMaximumExceeded(contract)
    return contract


__all__ = [
    "CaseSummaryRequest",
    "DEFAULT_MULTI_SUMMARY_MAX_WORDS",
    "DEFAULT_MULTI_SUMMARY_MIN_WORDS",
    "DEFAULT_SUMMARY_MAX_LENGTH",
    "DEFAULT_SUMMARY_MAX_WORDS",
    "DEFAULT_SUMMARY_MIN_LENGTH",
    "DEFAULT_SUMMARY_MIN_WORDS",
    "DEFAULT_SUMMARY_TYPE",
    "InvalidSummaryLengthBounds",
    "InvalidSummaryUserPrompt",
    "InvestigationSummaryMaxTooSmall",
    "MIN_INVESTIGATION_SUMMARY_MAX_WORDS",
    "MultiSummaryRequest",
    "SUMMARY_TYPES",
    "SUMMARY_TYPE_VALUES",
    "SUMMARY_USER_PROMPT_MAX_LENGTH",
    "SummaryMaximumExceeded",
    "SummaryLengthMode",
    "SummaryRequest",
    "SummaryRequestContractError",
    "SummaryRequestOptions",
    "SummaryType",
    "UnsupportedSummaryType",
    "build_summary_length_contract",
    "enforce_summary_maximum",
    "evaluate_summary_length",
    "normalize_summary_user_prompt",
    "require_summary_type",
    "validate_summary_length_bounds",
    "validate_summary_request_options",
]
