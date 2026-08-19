"""Benchmark local Vietnamese ASR candidates without exporting transcript text.

The cache must use the Hugging Face layout
``models/whisper/models--ORG--REPO/{refs/main,snapshots/REVISION}``. A CPU run
should pass ``--device cpu --compute-type int8``. Ungated rescue decoding is
available only with ``--ungated-rescue-diagnostic`` and is never production
rescue evidence.
"""

from __future__ import annotations

import argparse
import ast
import gc
import hashlib
import json
import platform
import re
import statistics
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from faster_whisper import WhisperModel, __version__ as faster_whisper_version
import ctranslate2


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_ROOT = REPO_ROOT / "models" / "whisper"


def _load_shared_model_specs() -> dict[str, dict[str, str]]:
    manager_path = (
        REPO_ROOT / "src" / "services" / "transcription" / "models" / "whisper_manager.py"
    )
    tree = ast.parse(manager_path.read_text(encoding="utf-8"), filename=str(manager_path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "WHISPER_MODEL_SPECS"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if not isinstance(value, dict):
                break
            return value
    raise RuntimeError(f"WHISPER_MODEL_SPECS not found in {manager_path}")


_SHARED_MODEL_SPECS = _load_shared_model_specs()
MODEL_SPECS = {
    alias: {
        "model_id": _SHARED_MODEL_SPECS[alias]["provider_id"],
        "cache_dir": _SHARED_MODEL_SPECS[alias]["cache_name"],
        "revision": _SHARED_MODEL_SPECS[alias]["revision"],
    }
    for alias in ("large-v2", "large-v3", "large-v3-turbo")
}
REQUIRED_SNAPSHOT_FILES = ("config.json", "model.bin", "tokenizer.json")
UNGATED_RESCUE_PROFILE = "leading-gap-rescue-v1"


class SnapshotResolutionError(RuntimeError):
    """Raised when refs/main does not select one complete local snapshot."""


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = "".join(
        character if character.isalnum() or character.isspace() else " "
        for character in normalized
    )
    return re.sub(r"\s+", " ", normalized).strip()


def edit_distance(left: Sequence[Any], right: Sequence[Any]) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_item in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_item in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_item != right_item),
                )
            )
        previous = current
    return previous[-1]


def error_rate(reference: Sequence[Any], hypothesis: Sequence[Any]) -> float | None:
    if not reference:
        return None
    return edit_distance(reference, hypothesis) / len(reference)


def interval_union_seconds(intervals: Iterable[tuple[float, float]]) -> float:
    ordered = sorted(
        (max(0.0, float(start)), max(0.0, float(end)))
        for start, end in intervals
        if end > start
    )
    if not ordered:
        return 0.0
    total = 0.0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
            continue
        total += current_end - current_start
        current_start, current_end = start, end
    return total + current_end - current_start


def repeated_ngram_rate(words: Sequence[str], size: int = 3) -> float:
    if len(words) < size:
        return 0.0
    ngrams = [tuple(words[index : index + size]) for index in range(len(words) - size + 1)]
    counts = Counter(ngrams)
    repeated = sum(count for count in counts.values() if count > 1)
    return repeated / len(ngrams)


def transcript_metrics(text: str, segments: Sequence[dict[str, Any]], duration: float) -> dict[str, Any]:
    normalized = normalize_text(text)
    words = normalized.split()
    coverage_seconds = interval_union_seconds(
        (float(segment["start"]), float(segment["end"])) for segment in segments
    )
    avg_logprobs = [
        float(segment["avg_logprob"])
        for segment in segments
        if segment.get("avg_logprob") is not None
    ]
    no_speech_probs = [
        float(segment["no_speech_prob"])
        for segment in segments
        if segment.get("no_speech_prob") is not None
    ]
    return {
        "transcript_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "characters": len(text),
        "normalized_words": len(words),
        "segments": len(segments),
        "timeline_coverage_seconds": round(coverage_seconds, 3),
        "timeline_coverage_ratio": round(coverage_seconds / duration, 6) if duration else None,
        "last_segment_end_seconds": round(
            max((float(segment["end"]) for segment in segments), default=0.0),
            3,
        ),
        "mean_avg_logprob": round(statistics.fmean(avg_logprobs), 6) if avg_logprobs else None,
        "min_avg_logprob": round(min(avg_logprobs), 6) if avg_logprobs else None,
        "mean_no_speech_probability": (
            round(statistics.fmean(no_speech_probs), 6) if no_speech_probs else None
        ),
        "repeated_trigram_rate": round(repeated_ngram_rate(words), 6),
    }


def reference_metrics(reference: str, hypothesis: str) -> dict[str, Any]:
    normalized_reference = normalize_text(reference)
    normalized_hypothesis = normalize_text(hypothesis)
    return {
        "wer": error_rate(normalized_reference.split(), normalized_hypothesis.split()),
        "cer": error_rate(list(normalized_reference), list(normalized_hypothesis)),
        "reference_words": len(normalized_reference.split()),
        "reference_characters": len(normalized_reference),
    }


def entity_recall(entity_payload: dict[str, Any], hypothesis: str) -> dict[str, Any]:
    normalized_hypothesis = normalize_text(hypothesis)
    by_type: dict[str, dict[str, int]] = {}
    matched = 0
    entities = entity_payload.get("entities", [])
    missed_ids: list[str] = []
    for index, entity in enumerate(entities):
        entity_type = str(entity.get("type") or "unknown")
        entity_id = str(entity.get("id") or f"entity-{index}")
        candidates = [entity.get("value"), *(entity.get("aliases") or [])]
        normalized_candidates = [normalize_text(str(value)) for value in candidates if value]
        found = any(
            candidate and re.search(rf"(?<!\w){re.escape(candidate)}(?!\w)", normalized_hypothesis)
            for candidate in normalized_candidates
        )
        bucket = by_type.setdefault(entity_type, {"total": 0, "matched": 0})
        bucket["total"] += 1
        if found:
            matched += 1
            bucket["matched"] += 1
        else:
            missed_ids.append(entity_id)
    for bucket in by_type.values():
        bucket["recall"] = bucket["matched"] / bucket["total"] if bucket["total"] else None
    return {
        "total": len(entities),
        "matched": matched,
        "recall": matched / len(entities) if entities else None,
        "by_type": by_type,
        "missed_entity_ids": missed_ids,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_snapshot(alias: str, cache_root: Path) -> tuple[dict[str, str], Path, str]:
    if alias not in MODEL_SPECS:
        raise ValueError(f"Unsupported local ASR model alias: {alias}")
    spec = MODEL_SPECS[alias]
    model_root = cache_root / spec["cache_dir"]
    ref_path = model_root / "refs" / "main"
    if not model_root.is_dir():
        raise FileNotFoundError(f"No local model cache for {alias}: {model_root}")
    if not ref_path.is_file():
        raise SnapshotResolutionError(
            f"Missing exact refs/main revision selector for {alias}: {ref_path}"
        )
    revisions = [
        line.strip()
        for line in ref_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(revisions) != 1:
        raise SnapshotResolutionError(
            f"Ambiguous refs/main revision selector for {alias}: {ref_path}"
        )
    revision = revisions[0]
    if revision in {".", ".."} or "/" in revision or "\\" in revision:
        raise SnapshotResolutionError(
            f"Invalid refs/main revision selector for {alias}: {ref_path}"
        )
    expected_revision = spec["revision"]
    if revision != expected_revision:
        raise SnapshotResolutionError(
            "refs/main revision does not match the pinned immutable revision "
            f"for {alias}: expected {expected_revision}, got {revision}"
        )
    snapshots_root = (model_root / "snapshots").resolve()
    snapshot = (snapshots_root / revision).resolve()
    if snapshot.parent != snapshots_root or not snapshot.is_dir():
        raise SnapshotResolutionError(
            f"refs/main for {alias} points to a missing snapshot: {revision}"
        )
    incomplete = [
        filename
        for filename in REQUIRED_SNAPSHOT_FILES
        if not (snapshot / filename).is_file() or (snapshot / filename).stat().st_size <= 0
    ]
    if incomplete:
        raise SnapshotResolutionError(
            f"refs/main for {alias} points to an incomplete snapshot "
            f"({revision}): {', '.join(incomplete)}"
        )
    return spec, snapshot.resolve(), snapshot.name


def normalize_benchmark_runtime(
    device: str,
    compute_type: str,
) -> tuple[str, str, str | None]:
    """Normalize known unsupported explicit runtime combinations."""

    normalized_device = str(device).strip().casefold()
    normalized_compute_type = str(compute_type).strip().casefold()
    if not normalized_device or not normalized_compute_type:
        raise ValueError("Benchmark device and compute_type must be non-empty")
    if normalized_device == "cpu" and normalized_compute_type == "float16":
        return "cpu", "int8", "cpu_float16_unsupported_normalized_to_int8"
    return normalized_device, normalized_compute_type, None


def profile_execution_semantics(
    profile: str,
    *,
    ungated_rescue_diagnostic: bool,
) -> dict[str, Any]:
    if profile == UNGATED_RESCUE_PROFILE:
        if not ungated_rescue_diagnostic:
            raise ValueError(
                "leading-gap-rescue-v1 runs ungated no-VAD decoding in this benchmark; "
                "pass --ungated-rescue-diagnostic to label it explicitly as diagnostic"
            )
        return {
            "result_role": "diagnostic_ungated_rescue_candidate_generation",
            "production_rescue_gate_applied": False,
            "production_rescue_eligible": False,
        }
    if profile == "coverage-diagnostic-no-vad-v1":
        return {
            "result_role": "diagnostic_no_vad_coverage_probe",
            "production_rescue_gate_applied": False,
            "production_rescue_eligible": False,
        }
    return {
        "result_role": "primary_decode_benchmark",
        "production_rescue_gate_applied": False,
        "production_rescue_eligible": False,
    }


def decode_parameters(profile: str) -> dict[str, Any]:
    common = {
        "language": "vi",
        "compression_ratio_threshold": 2.4,
        "log_prob_threshold": -1.0,
        "vad_filter": True,
        "vad_parameters": {
            "threshold": 0.4,
            "min_speech_duration_ms": 200,
            "min_silence_duration_ms": 1500,
            "speech_pad_ms": 800,
        },
        "word_timestamps": True,
        "condition_on_previous_text": False,
    }
    if profile == "fast-v1":
        return {
            **common,
            "beam_size": 1,
            "temperature": 0.0,
            "no_speech_threshold": 0.5,
        }
    if profile == "investigation-accuracy-v1":
        return {
            **common,
            "beam_size": 5,
            "temperature": 0.0,
            "no_speech_threshold": 0.6,
            "hallucination_silence_threshold": 1.5,
        }
    if profile == "coverage-diagnostic-no-vad-v1":
        return {
            **common,
            "beam_size": 5,
            "temperature": 0.0,
            "no_speech_threshold": 0.6,
            "vad_filter": False,
            "hallucination_silence_threshold": 1.5,
        }
    if profile == "leading-gap-rescue-v1":
        return {
            **common,
            "beam_size": 5,
            "temperature": 0.0,
            "no_speech_threshold": 0.5,
            "vad_filter": False,
            "hallucination_silence_threshold": 1.0,
        }
    raise ValueError(f"Unsupported decode profile: {profile}")


def run_model(
    *,
    alias: str,
    audio_path: Path,
    cache_root: Path,
    profile: str,
    device: str,
    compute_type: str,
    hash_model: bool,
    reference: str | None,
    entities: dict[str, Any] | None,
    include_transcript: bool,
    include_artifact_path: bool,
    clip_timestamps: str | None,
    execution_semantics: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    spec, snapshot, revision = resolve_snapshot(alias, cache_root)
    model_file = snapshot / "model.bin"
    if not model_file.is_file():
        raise FileNotFoundError(f"Missing model.bin: {model_file}")

    effective_device, effective_compute_type, normalization_reason = (
        normalize_benchmark_runtime(device, compute_type)
    )
    load_started = time.perf_counter()
    model = WhisperModel(
        str(snapshot),
        device=effective_device,
        compute_type=effective_compute_type,
        local_files_only=True,
    )
    load_seconds = time.perf_counter() - load_started

    parameters = decode_parameters(profile)
    if clip_timestamps:
        parameters["clip_timestamps"] = clip_timestamps
    decode_started = time.perf_counter()
    segment_iterator, info = model.transcribe(str(audio_path), **parameters)
    segments: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for segment in segment_iterator:
        text = segment.text.strip()
        if not text:
            continue
        text_parts.append(text)
        segments.append(
            {
                "start": float(segment.start),
                "end": float(segment.end),
                "avg_logprob": getattr(segment, "avg_logprob", None),
                "no_speech_prob": getattr(segment, "no_speech_prob", None),
            }
        )
    decode_seconds = time.perf_counter() - decode_started
    transcript = " ".join(text_parts)
    duration = float(info.duration)

    result: dict[str, Any] = {
        "alias": alias,
        "model_id": spec["model_id"],
        "revision": revision,
        "expected_revision": spec["revision"],
        "revision_matches_pin": revision == spec["revision"],
        "revision_policy": "pinned_immutable",
        "revision_source": "pinned_refs/main",
        "artifact_size_bytes": model_file.stat().st_size,
        "artifact_sha256": sha256_file(model_file) if hash_model else None,
        "requested_device": device,
        "requested_compute_type": compute_type,
        "device": effective_device,
        "compute_type": effective_compute_type,
        "runtime_normalized": normalization_reason is not None,
        "runtime_normalization_reason": normalization_reason,
        "decode_profile": profile,
        "execution_semantics": execution_semantics,
        "decode_parameters": parameters,
        "detected_language": info.language,
        "language_probability": float(info.language_probability),
        "duration_seconds": duration,
        "model_load_seconds": round(load_seconds, 3),
        "decode_seconds": round(decode_seconds, 3),
        "real_time_factor": round(decode_seconds / duration, 6) if duration else None,
        "output": transcript_metrics(transcript, segments, duration),
    }
    if include_artifact_path:
        result["artifact_path"] = str(snapshot)
    if reference is not None:
        result["reference_metrics"] = reference_metrics(reference, transcript)
    if entities is not None:
        result["critical_entity_metrics"] = entity_recall(entities, transcript)
    if include_transcript:
        result["output"]["transcript"] = transcript

    del model
    gc.collect()
    return result, transcript


def pairwise_disagreement(outputs: dict[str, str]) -> list[dict[str, Any]]:
    aliases = list(outputs)
    comparisons: list[dict[str, Any]] = []
    for left_index, left_alias in enumerate(aliases):
        for right_alias in aliases[left_index + 1 :]:
            left_words = normalize_text(outputs[left_alias]).split()
            right_words = normalize_text(outputs[right_alias]).split()
            denominator = max(len(left_words), len(right_words), 1)
            comparisons.append(
                {
                    "left": left_alias,
                    "right": right_alias,
                    "normalized_word_disagreement": round(
                        edit_distance(left_words, right_words) / denominator,
                        6,
                    ),
                }
            )
    return comparisons


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--models", nargs="+", choices=sorted(MODEL_SPECS), required=True)
    parser.add_argument(
        "--profile",
        choices=(
            "fast-v1",
            "investigation-accuracy-v1",
            "coverage-diagnostic-no-vad-v1",
            "leading-gap-rescue-v1",
        ),
        default="investigation-accuracy-v1",
    )
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--compute-type", default="float16")
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--entities", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-model-hash", action="store_true")
    parser.add_argument("--include-transcript", action="store_true")
    parser.add_argument("--include-artifact-path", action="store_true")
    parser.add_argument(
        "--ungated-rescue-diagnostic",
        action="store_true",
        help=(
            "Allow leading-gap-rescue-v1 only as explicitly labeled ungated "
            "diagnostic output; it is never production-rescue evidence."
        ),
    )
    parser.add_argument("--clip-timestamps")
    args = parser.parse_args()
    try:
        profile_execution_semantics(
            args.profile,
            ungated_rescue_diagnostic=args.ungated_rescue_diagnostic,
        )
    except ValueError as error:
        parser.error(str(error))
    return args


def main() -> int:
    args = parse_args()
    audio_path = args.audio.resolve()
    if not audio_path.is_file():
        raise FileNotFoundError(audio_path)
    reference = args.reference.read_text(encoding="utf-8") if args.reference else None
    entities = json.loads(args.entities.read_text(encoding="utf-8")) if args.entities else None
    execution_semantics = profile_execution_semantics(
        args.profile,
        ungated_rescue_diagnostic=args.ungated_rescue_diagnostic,
    )
    effective_device, effective_compute_type, normalization_reason = (
        normalize_benchmark_runtime(args.device, args.compute_type)
    )

    report: dict[str, Any] = {
        "schema_version": "vietnamese-asr-benchmark-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "privacy": {
            "transcript_included": bool(args.include_transcript),
            "transcript_location": (
                "results[].output.transcript" if args.include_transcript else None
            ),
            "audio_path_included": False,
            "audio_name_included": False,
            "absolute_artifact_path_included": bool(args.include_artifact_path),
        },
        "audio": {
            "size_bytes": audio_path.stat().st_size,
            "sha256": sha256_file(audio_path),
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "faster_whisper": faster_whisper_version,
            "ctranslate2": ctranslate2.__version__,
            "requested_device": args.device,
            "requested_compute_type": args.compute_type,
            "device": effective_device,
            "compute_type": effective_compute_type,
            "runtime_normalized": normalization_reason is not None,
            "runtime_normalization_reason": normalization_reason,
        },
        "profile": args.profile,
        "profile_execution_semantics": execution_semantics,
        "results": [],
    }
    outputs: dict[str, str] = {}
    for alias in args.models:
        result, transcript = run_model(
            alias=alias,
            audio_path=audio_path,
            cache_root=args.cache_root.resolve(),
            profile=args.profile,
            device=args.device,
            compute_type=args.compute_type,
            hash_model=not args.skip_model_hash,
            reference=reference,
            entities=entities,
            include_transcript=args.include_transcript,
            include_artifact_path=args.include_artifact_path,
            clip_timestamps=args.clip_timestamps,
            execution_semantics=execution_semantics,
        )
        report["results"].append(result)
        outputs[alias] = transcript
    report["pairwise_disagreement"] = pairwise_disagreement(outputs)

    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    sys.exit(main())
