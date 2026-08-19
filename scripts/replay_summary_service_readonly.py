"""Replay one persisted summary through the service without updating the task."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.summarization.summary_service_v2 import summarize_transcript_v2
from src.services.task_service import get_task


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_text(_canonical_json(value))


def _source_metadata(task_id: str, task: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "audio_id": result.get("audio_id"),
        "audio_sha256": result.get("audio_sha256"),
        "audio_integrity_status": result.get("audio_integrity_status"),
        "case_id": task.get("case_id") or result.get("case_id"),
        "file_name": task.get("filename") or result.get("filename"),
        "num_speakers": result.get("num_speakers"),
        "has_diarization": result.get("has_diarization"),
        "degraded": result.get("degraded"),
        "diarization_status": result.get("diarization_status"),
        "diarization_method_used": result.get("diarization_method_used"),
        "diarization_fallback_reason": result.get("diarization_fallback_reason"),
        "diarization_degraded_reasons": result.get("diarization_degraded_reasons"),
        "speaker_provenance": result.get("speaker_provenance"),
        "current_transcript_segments": result.get("segments") or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--length-mode", choices=("auto", "manual"), default="auto")
    parser.add_argument("--min-length", type=int, default=120)
    parser.add_argument("--max-length", type=int, default=400)
    args = parser.parse_args()

    task = get_task(args.task_id)
    if not task:
        raise SystemExit(f"Task not found: {args.task_id}")
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    transcript = result.get("transcription")
    segments = result.get("segments")
    if not isinstance(transcript, str) or not transcript.strip():
        raise SystemExit("Task has no transcription")
    if not isinstance(segments, list):
        raise SystemExit("Task has no top-level segments")

    replay_result = summarize_transcript_v2(
        transcript=transcript,
        model_name=None,
        summary_type="investigation",
        include_context=True,
        user_prompt=None,
        min_length=args.min_length,
        max_length=args.max_length,
        length_mode=args.length_mode,
        transcript_segments=segments,
        source_metadata=_source_metadata(args.task_id, task, result),
        grounded_context=(
            result.get("context_analysis")
            if isinstance(result.get("context_analysis"), dict)
            else None
        ),
        allow_evidence_preview=True,
        investigation_scenario="auto",
    )
    summary = replay_result.get("summary")
    summary_text = summary if isinstance(summary, str) else ""
    artifact = {
        "schema_version": "stt-summary-service-readonly-replay-v2",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "task_id": args.task_id,
        "input": {
            "transcription_length": len(transcript),
            "transcription_sha256": _sha256_text(transcript),
            "segment_count": len(segments),
            "segments_sha256": _sha256_json(segments),
            "length_mode": args.length_mode,
            "requested_min_length": args.min_length,
            "requested_max_length": args.max_length,
        },
        "result": {
            "available": replay_result.get("available"),
            "summary_state": replay_result.get("summary_state"),
            "summary": summary_text,
            "summary_length": len(summary_text),
            "summary_word_count": len(summary_text.split()),
            "summary_sha256": _sha256_text(summary_text) if summary_text else None,
            "error": replay_result.get("error"),
            "runtime": replay_result.get("runtime"),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "available": artifact["result"]["available"],
                "summary_state": artifact["result"]["summary_state"],
                "summary_word_count": artifact["result"]["summary_word_count"],
                "summary_generation": (
                    artifact["result"].get("runtime") or {}
                ).get("summary_generation"),
                "prompt_version": (
                    artifact["result"].get("runtime") or {}
                ).get("prompt_version"),
                "llm_call_count": (
                    artifact["result"].get("runtime") or {}
                ).get("llm_call_count"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if replay_result.get("available") else 2


if __name__ == "__main__":
    raise SystemExit(main())
