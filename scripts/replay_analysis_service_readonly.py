"""Replay persisted transcripts through Analysis v2 without updating tasks."""

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

from src.services.summarization.context_service import analyze_conversation_context
from src.services.summarization.models.llm_manager import get_llm_manager
from src.services.task_service import get_task


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _task_fingerprint(task: dict[str, Any]) -> str:
    return _sha256_text(_canonical_json(task))


def _source_metadata(
    task_id: str,
    task: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "audio_id": result.get("audio_id"),
        "audio_sha256": result.get("audio_sha256"),
        "case_id": task.get("case_id") or result.get("case_id"),
        "file_name": task.get("filename") or result.get("filename"),
        "num_speakers": result.get("num_speakers"),
        "has_diarization": result.get("has_diarization"),
    }


def _count_business_items(analysis: dict[str, Any]) -> dict[str, int]:
    fields = (
        "key_points",
        "participants",
        "events",
        "actions",
        "entities",
        "relationships",
        "contradictions",
        "uncertainties",
        "follow_ups",
    )
    return {
        field: len(analysis.get(field)) if isinstance(analysis.get(field), list) else 0
        for field in fields
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manager = get_llm_manager()
    manifest: list[dict[str, Any]] = []
    failed = False

    for task_id in args.task_id:
        task = get_task(task_id)
        if not task:
            raise SystemExit(f"Task not found: {task_id}")
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        transcript = result.get("transcription")
        segments = result.get("segments")
        if not isinstance(transcript, str) or not transcript.strip():
            raise SystemExit(f"Task has no transcription: {task_id}")
        if not isinstance(segments, list):
            segments = []

        task_fingerprint_before = _task_fingerprint(task)
        generation_before = manager.get_generation_count()
        analysis = analyze_conversation_context(
            transcript,
            model_name=None,
            user_prompt=None,
            segments=segments,
            source_metadata=_source_metadata(task_id, task, result),
            investigation_scenario="auto",
        )
        generation_after = manager.get_generation_count()
        task_after = get_task(task_id) or {}
        task_fingerprint_after = _task_fingerprint(task_after)
        analysis = analysis if isinstance(analysis, dict) else {}
        call_count = generation_after - generation_before
        status = analysis.get("analysis_status")
        usable = status in {"success", "partial"} and bool(
            str(analysis.get("overview") or analysis.get("analysis_text") or "").strip()
            or sum(_count_business_items(analysis).values())
        )
        artifact = {
            "schema_version": "stt-analysis-service-readonly-replay-v1",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "task_id": task_id,
            "input": {
                "transcript_chars": len(transcript),
                "transcript_words": len(transcript.split()),
                "transcript_sha256": _sha256_text(transcript),
                "segment_count": len(segments),
                "segments_sha256": _sha256_text(_canonical_json(segments)),
                "task_fingerprint_before": task_fingerprint_before,
                "task_fingerprint_after": task_fingerprint_after,
                "task_unchanged": task_fingerprint_after == task_fingerprint_before,
            },
            "result": {
                "analysis_status": status,
                "analysis_generation": analysis.get("analysis_generation"),
                "prompt_version": analysis.get("prompt_version"),
                "llm_call_count": call_count,
                "usable": usable,
                "business_item_counts": _count_business_items(analysis),
                "analysis": analysis,
            },
        }
        artifact_path = output_dir / f"{task_id}.json"
        artifact_path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        row = {
            "task_id": task_id,
            "output": str(artifact_path),
            "status": status,
            "usable": usable,
            "llm_call_count": call_count,
            "business_item_count": sum(_count_business_items(analysis).values()),
        }
        manifest.append(row)
        print(json.dumps(row, ensure_ascii=False))
        if (
            not usable
            or call_count != 1
            or task_fingerprint_after != task_fingerprint_before
        ):
            failed = True

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
