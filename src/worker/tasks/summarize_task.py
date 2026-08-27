"""
Summarize Task - Celery background task for summarization
Handles: Transcribe → Summarize (OPTIONAL, only if requested)
"""
import logging

from contextlib import contextmanager
from typing import Iterator

from src.core.config import settings
from src.services.model_runtime.gpu_lease import (
    arm_gpu_quarantine,
    verify_and_clear_gpu_quarantine,
)
from src.services.summarization.contracts import (
    DEFAULT_MULTI_SUMMARY_MAX_WORDS,
    DEFAULT_MULTI_SUMMARY_MIN_WORDS,
    DEFAULT_SUMMARY_MAX_WORDS,
    DEFAULT_SUMMARY_MIN_WORDS,
    DEFAULT_SUMMARY_TYPE,
    SummaryType,
    validate_summary_request_options,
)
from src.services.summarization.investigation_scenarios import (
    DEFAULT_INVESTIGATION_SCENARIO,
    InvestigationScenario,
    require_investigation_scenario,
)
from src.services.summarization.failure_contract import (
    SAFE_SUMMARY_MESSAGES as _SAFE_TASK_MESSAGES,
    SafeSummaryTaskError,
    build_safe_summary_failure_update as _safe_failure_update,
)
from src.worker.worker import celery_app
from src.services.task_service import get_task, update_task

logger = logging.getLogger(__name__)


class UnsafeGpuHandoff(RuntimeError):
    """Raised when llama-server cannot prove it released GPU memory."""


def _result_error_code(result: object, fallback: str) -> str:
    if not isinstance(result, dict):
        return fallback
    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    code = error.get("code")
    return code if isinstance(code, str) and code in _SAFE_TASK_MESSAGES else fallback


def _current_transcript_segments(task_result: dict) -> list[dict]:
    """Keep summary grounding on the latest diarized segment projection."""

    segments = task_result.get("segments")
    if isinstance(segments, list) and all(
        isinstance(item, dict) for item in segments
    ):
        return segments

    transcription_result = task_result.get("transcription_result")
    if isinstance(transcription_result, dict):
        segments = transcription_result.get("segments")
        if isinstance(segments, list) and all(
            isinstance(item, dict) for item in segments
        ):
            return segments
    return []


def _verify_llama_server_sleeping() -> bool:
    from src.services.summarization.models.llm_manager import get_llm_manager

    return bool(get_llm_manager().unload_last_model())


@contextmanager
def _llama_server_handoff(owner: str, summary_stage: str) -> Iterator[None]:
    """Keep non-LLM GPU stages quarantined until server sleep is verified."""

    if str(settings.LOCAL_LLM_PROVIDER).strip().casefold() != "llama_cpp_server":
        yield
        return
    if not settings.GPU_LEASE_ENABLED:
        raise UnsafeGpuHandoff(
            "llama-server requires GPU_LEASE_ENABLED=true for a safe GPU handoff"
        )

    quarantine = arm_gpu_quarantine(
        stage=summary_stage,
        owner=owner,
        reason="llama-server GPU handoff is pending sleep verification",
        allowed_stages=(summary_stage,),
    )
    try:
        yield
    finally:
        try:
            cleared = verify_and_clear_gpu_quarantine(
                _verify_llama_server_sleeping,
                verified_by=f"{owner}:{summary_stage}:sleep-check",
                expected_quarantine_id=quarantine.quarantine_id,
            )
        except Exception as exc:
            raise UnsafeGpuHandoff(
                "llama-server sleep verification failed; GPU quarantine remains "
                "active. Confirm /props reports is_sleeping=true and run the "
                "quarantine recovery verifier before starting audio GPU work."
            ) from exc
        if not cleared:
            raise UnsafeGpuHandoff(
                "llama-server did not enter idle sleep; GPU quarantine remains "
                "active. Confirm /props reports is_sleeping=true and run the "
                "quarantine recovery verifier before starting audio GPU work."
            )


@celery_app.task(bind=True, name='tasks.summarize_transcript')
def summarize_transcript_task(
    self,
    task_id: str,
    model_name: str = None,
    summary_type: SummaryType = DEFAULT_SUMMARY_TYPE,
    include_context: bool = True,
    user_prompt: str = None,
    min_length: int = DEFAULT_SUMMARY_MIN_WORDS,
    max_length: int = DEFAULT_SUMMARY_MAX_WORDS,
    length_mode: str = "auto",
    investigation_scenario: InvestigationScenario = DEFAULT_INVESTIGATION_SCENARIO,
    **unexpected_options: object,
):
    """
    Celery task for transcript summarization

    Args:
        task_id: Task ID (must have transcript)
        model_name: LLM model to use
        summary_type: Type of summary
        include_context: Include context analysis
        user_prompt: Optional user prompt

    Returns:
        Result dict or error
    """
    options = validate_summary_request_options(
        summary_type=summary_type,
        min_length=min_length,
        max_length=max_length,
        length_mode=length_mode,
        user_prompt=user_prompt,
    )
    summary_type = options.summary_type
    min_length = options.min_length
    max_length = options.max_length
    length_mode = options.length_mode
    user_prompt = options.user_prompt
    investigation_scenario = require_investigation_scenario(investigation_scenario)

    logger.info(
        f"[CELERY_SUMMARIZE] Task started | task_id={task_id} | "
        f"celery_id={self.request.id} | model={model_name}"
    )

    try:
        if unexpected_options:
            logger.error(
                "[CELERY_SUMMARIZE] Request contract mismatch | task_id=%s | fields=%s",
                task_id,
                sorted(unexpected_options),
            )
            raise SafeSummaryTaskError("SUMMARY_REQUEST_CONTRACT_MISMATCH")

        # Get task to extract transcript
        task = get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # Get transcript from task result (standardized to "transcription")
        transcript = None
        transcript_segments = []
        grounded_context = None
        source_metadata = {"task_id": task_id}
        if task.get("result") and isinstance(task["result"], dict):
            # Transcript is stored in result["transcription"] (TaskResult schema)
            task_result = task["result"]
            transcript = task_result.get("transcription")
            transcript_segments = _current_transcript_segments(task_result)
            grounded_context = task_result.get("context_analysis")
            source_metadata.update(
                audio_id=task_result.get("audio_id"),
                audio_sha256=task_result.get("audio_sha256"),
                audio_integrity_status=task_result.get("audio_integrity_status"),
                case_id=task.get("case_id") or task_result.get("case_id"),
                file_name=task.get("filename") or task_result.get("filename"),
                num_speakers=task_result.get("num_speakers"),
                has_diarization=task_result.get("has_diarization"),
                degraded=task_result.get("degraded"),
                diarization_status=task_result.get("diarization_status"),
                diarization_method_used=task_result.get(
                    "diarization_method_used"
                ),
                diarization_fallback_reason=task_result.get(
                    "diarization_fallback_reason"
                ),
                diarization_degraded_reasons=task_result.get(
                    "diarization_degraded_reasons"
                ),
                speaker_provenance=task_result.get("speaker_provenance"),
                current_transcript_segments=transcript_segments,
            )

        if not transcript or not transcript.strip():
            logger.warning(f"[CELERY_SUMMARIZE] No transcription found for task {task_id}. Task result keys: {list(task.get('result', {}).keys()) if task.get('result') else 'No result'}")
            raise ValueError(f"Task {task_id} has no transcription. Run transcription first.")

        # Import here to avoid circular dependencies
        from src.services.summarization.summary_service_v2 import summarize_transcript_v2

        if not update_task(task_id, {"status": "summarizing"}):
            raise SafeSummaryTaskError("SUMMARY_PERSISTENCE_FAILED")

        # Execute summarization with timeout protection
        logger.info(f"[CELERY_SUMMARIZE] Starting summarization | transcript_length={len(transcript)}")

        try:
            with _llama_server_handoff(f"task:{task_id}", "summary"):
                result = summarize_transcript_v2(
                    transcript=transcript,
                    model_name=model_name,
                    summary_type=summary_type,
                    include_context=include_context,
                    user_prompt=user_prompt,
                    min_length=min_length,
                    max_length=max_length,
                    length_mode=length_mode,
                    transcript_segments=transcript_segments,
                    source_metadata=source_metadata,
                    grounded_context=(
                        grounded_context if isinstance(grounded_context, dict) else None
                    ),
                    allow_evidence_preview=summary_type == "investigation",
                    investigation_scenario=investigation_scenario,
                )
        except UnsafeGpuHandoff:
            raise SafeSummaryTaskError("SUMMARY_UNSAFE_HANDOFF") from None
        except SafeSummaryTaskError:
            raise
        except Exception as summary_error:
            logger.error(
                "[CELERY_SUMMARIZE] Summarization failed | task_id=%s | error_type=%s",
                task_id,
                type(summary_error).__name__,
            )
            raise SafeSummaryTaskError("SUMMARY_GENERATION_FAILED") from None

        if not result.get("available"):
            raise SafeSummaryTaskError(
                _result_error_code(result, "SUMMARY_UNAVAILABLE"),
                result=result,
            )

        summary_state = result.get("summary_state")
        summary_text = result.get("summary")
        if not isinstance(summary_text, str):
            summary_text = ""
        if summary_state == "grounded_transcript_only":
            raise SafeSummaryTaskError("SUMMARY_PREVIEW_ONLY")
        if not summary_text.strip():
            raise SafeSummaryTaskError("SUMMARY_EMPTY")

        # Summary owns only this partial result patch. The task service merges it
        # atomically so independently published visualization bytes stay untouched.
        summary_result_patch = {
            "summary": summary_text or None,
            "summary_model": result.get("model"),
            "summary_type": summary_type,
            "summary_state": summary_state,
            "summary_authority": result.get("summary_authority"),
            "summary_notice": result.get("summary_notice"),
            "summary_error": result.get("error"),
            "summary_preview": result.get("summary_preview"),
            "summary_runtime": result.get("runtime") or {},
        }
        generated_context = result.get("context")
        if isinstance(generated_context, dict):
            summary_result_patch["context_analysis"] = generated_context

        # Update task with summary
        persisted = update_task(task_id, {
            "status": "summarized",
            "result": summary_result_patch,
            "summary": summary_text or None,
            "model_name": result.get("model"),
            "error": None,
        })
        if not persisted:
            raise SafeSummaryTaskError("SUMMARY_PERSISTENCE_FAILED")

        logger.info(f"[CELERY_SUMMARIZE] Task complete | task_id={task_id}")

        return {
            "status": "success",
            "task_id": task_id,
            "result": result
        }

    except SafeSummaryTaskError as exc:
        logger.error(
            "[CELERY_SUMMARIZE] Task failed | task_id=%s | code=%s",
            task_id,
            exc.code,
        )
        persisted = update_task(
            task_id,
            _safe_failure_update(exc),
        )
        if not persisted and exc.code != "SUMMARY_PERSISTENCE_FAILED":
            raise SafeSummaryTaskError("SUMMARY_PERSISTENCE_FAILED") from None
        raise
    except Exception as exc:
        logger.error(
            "[CELERY_SUMMARIZE] Task failed | task_id=%s | error_type=%s",
            task_id,
            type(exc).__name__,
        )
        persisted = update_task(
            task_id,
            {"status": "failed", "error": _SAFE_TASK_MESSAGES["SUMMARY_GENERATION_FAILED"]},
        )
        if not persisted:
            raise SafeSummaryTaskError("SUMMARY_PERSISTENCE_FAILED") from None
        raise SafeSummaryTaskError("SUMMARY_GENERATION_FAILED") from None


@celery_app.task(bind=True, name='tasks.summarize_multi')
def summarize_multi_task(
    self,
    task_ids: list,
    model_name: str = None,
    summary_type: SummaryType = DEFAULT_SUMMARY_TYPE,
    case_id: str = None,
    min_length: int = DEFAULT_MULTI_SUMMARY_MIN_WORDS,
    max_length: int = DEFAULT_MULTI_SUMMARY_MAX_WORDS,
    length_mode: str = "auto",
    user_prompt: str = None,
):
    """
    Celery task for multi-transcript summarization

    Args:
        task_ids: List of task IDs
        model_name: LLM model to use
        summary_type: Type of summary
        case_id: Case ID

    Returns:
        Result dict or error
    """
    options = validate_summary_request_options(
        summary_type=summary_type,
        min_length=min_length,
        max_length=max_length,
        length_mode=length_mode,
        user_prompt=user_prompt,
    )
    summary_type = options.summary_type
    min_length = options.min_length
    max_length = options.max_length
    length_mode = options.length_mode
    user_prompt = options.user_prompt

    logger.info(
        f"[CELERY_MULTI_SUMMARY] Task started | count={len(task_ids)} | "
        f"celery_id={self.request.id} | case={case_id}"
    )

    try:
        # Collect transcripts from all tasks
        transcripts = []

        for tid in task_ids:
            task = get_task(tid)
            if task and task.get("result"):
                transcript = task["result"].get("transcription")
                if transcript:
                    transcripts.append(transcript)

        if not transcripts:
            raise ValueError("No transcripts found in provided tasks")

        # Import here
        from src.services.summarization.summary_service_v2 import summarize_multi_transcripts_v2

        # Execute multi-summarization
        owner = f"case:{case_id or 'synchronous'}"
        with _llama_server_handoff(owner, "multi_summary"):
            result = summarize_multi_transcripts_v2(
                transcripts=transcripts,
                model_name=model_name,
                summary_type=summary_type,
                case_id=case_id,
                min_length=min_length,
                max_length=max_length,
                length_mode=length_mode,
                user_prompt=user_prompt,
            )

        if not result.get("available"):
            raise SafeSummaryTaskError(
                _result_error_code(result, "SUMMARY_UNAVAILABLE"),
                result=result,
            )

        logger.info(f"[CELERY_MULTI_SUMMARY] Task complete | case={case_id}")

        return {
            "status": "success",
            "case_id": case_id,
            "result": result
        }

    except SafeSummaryTaskError as exc:
        logger.error(
            "[CELERY_MULTI_SUMMARY] Task failed | case=%s | code=%s",
            case_id,
            exc.code,
        )
        raise
    except Exception as exc:
        logger.error(
            "[CELERY_MULTI_SUMMARY] Task failed | case=%s | error_type=%s",
            case_id,
            type(exc).__name__,
        )
        raise SafeSummaryTaskError("SUMMARY_GENERATION_FAILED") from None
