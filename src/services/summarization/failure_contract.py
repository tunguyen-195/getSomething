"""Shared fail-closed persistence contract for Summary execution paths."""

from __future__ import annotations

from typing import Any


SAFE_SUMMARY_MESSAGES = {
    "INVESTIGATION_CONTEXT_WINDOW_EXCEEDED": (
        "The grounded investigation context exceeds the verified model window."
    ),
    "INVESTIGATION_COVERAGE_FAILED": (
        "The investigation summary could not preserve all required source content."
    ),
    "INVESTIGATION_LENGTH_CONFLICT": (
        "The investigation summary cannot satisfy the requested length without losing required content."
    ),
    "INVESTIGATION_LENGTH_COVERAGE_CONFLICT": (
        "The investigation summary cannot fit all locked content within the requested length."
    ),
    "INVESTIGATION_WRITER_REJECTED": (
        "The investigation summary failed its grounded-content quality gate."
    ),
    "INVESTIGATION_WRITER_UNAVAILABLE": (
        "The investigation summary writer is unavailable."
    ),
    "LLM_UNAVAILABLE": "The summarization service is unavailable.",
    "MULTI_SUMMARY_SOURCE_INVALID": (
        "Every selected transcript must be present and non-empty."
    ),
    "SUMMARY_CONTEXT_WINDOW_EXCEEDED": (
        "The complete transcript exceeds the verified model context window."
    ),
    "SUMMARY_EMPTY": "The summarization service returned no usable summary.",
    "SUMMARY_GENERATION_FAILED": "Summary generation failed.",
    "SUMMARY_PERSISTENCE_FAILED": "The summary state could not be persisted.",
    "SUMMARY_PROMPT_SOURCE_INVARIANT_FAILED": (
        "The summary prompt did not preserve exactly one complete source block."
    ),
    "SUMMARY_PREVIEW_ONLY": "A transcript preview is not a completed summary.",
    "SUMMARY_REQUEST_CONTRACT_MISMATCH": (
        "The summary worker request contract is incompatible."
    ),
    "SUMMARY_RESULT_INVALID": "The summarization service returned an invalid result.",
    "SUMMARY_UNAVAILABLE": "The summarization service did not produce an available result.",
    "SUMMARY_UNSAFE_HANDOFF": "The model handoff did not complete safely.",
}

NON_RETRYABLE_SUMMARY_ERRORS = {
    "MULTI_SUMMARY_SOURCE_INVALID",
    "SUMMARY_CONTEXT_WINDOW_EXCEEDED",
    "SUMMARY_PROMPT_SOURCE_INVARIANT_FAILED",
}


class SafeSummaryTaskError(RuntimeError):
    def __init__(self, code: str, *, result: dict[str, Any] | None = None) -> None:
        self.code = code if code in SAFE_SUMMARY_MESSAGES else "SUMMARY_UNAVAILABLE"
        self.result = result if isinstance(result, dict) else None
        super().__init__(SAFE_SUMMARY_MESSAGES[self.code])


def build_safe_summary_failure_update(error: SafeSummaryTaskError) -> dict[str, Any]:
    """Return the atomic task patch shared by sync API and Celery failures."""

    service_result = error.result or {}
    retryable = error.code not in NON_RETRYABLE_SUMMARY_ERRORS
    return {
        "status": "failed",
        "error": str(error),
        "result": {
            "summary": None,
            "summary_state": "unavailable",
            "summary_authority": None,
            "summary_error": {
                "code": error.code,
                "message": str(error),
            },
            "summary_notice": {
                "code": error.code,
                "severity": "error",
                "message": str(error),
                "retryable": retryable,
                "next_action": (
                    "use_larger_context_or_shorter_source"
                    if error.code == "SUMMARY_CONTEXT_WINDOW_EXCEEDED"
                    else "contact_support"
                    if error.code == "SUMMARY_PROMPT_SOURCE_INVARIANT_FAILED"
                    else "retry_summary_after_runtime_check"
                ),
            },
            "summary_preview": None,
            "summary_runtime": (
                service_result.get("runtime")
                if isinstance(service_result.get("runtime"), dict)
                else {}
            ),
        },
    }


__all__ = [
    "NON_RETRYABLE_SUMMARY_ERRORS",
    "SAFE_SUMMARY_MESSAGES",
    "SafeSummaryTaskError",
    "build_safe_summary_failure_update",
]
