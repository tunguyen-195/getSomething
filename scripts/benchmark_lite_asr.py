from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


PHONE_RE = re.compile(r"\b0\d(?:[\s.\-]?\d){8,10}\b")
DATE_RE = re.compile(r"\b(?:ngay\s+)?\d{1,2}\s*(?:/|\s+thang\s+)\s*\d{1,2}\b", re.IGNORECASE)
MONEY_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:trieu|nghin|k|d|dong)\b", re.IGNORECASE)


def process_rss_mb() -> float | None:
    try:
        import psutil

        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        return None


def nvidia_vram_mb() -> float | None:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )
        values = [float(line.strip()) for line in completed.stdout.splitlines() if line.strip()]
        return max(values) if values else None
    except Exception:
        return None


class ResourceSampler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self.peak_ram_mb: float | None = process_rss_mb()
        self.peak_vram_mb: float | None = nvidia_vram_mb()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> "ResourceSampler":
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.wait(0.5):
            ram = process_rss_mb()
            vram = nvidia_vram_mb()
            if ram is not None:
                self.peak_ram_mb = max(self.peak_ram_mb or 0, ram)
            if vram is not None:
                self.peak_vram_mb = max(self.peak_vram_mb or 0, vram)


def load_labels(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def recall_for(text: str, expected: list[str]) -> float | None:
    if not expected:
        return None
    normalized = re.sub(r"\s+", " ", text.lower())
    hits = 0
    for item in expected:
        item_norm = re.sub(r"\s+", " ", str(item).lower()).strip()
        if item_norm and item_norm in normalized:
            hits += 1
    return hits / len(expected)


def benchmark_file(path: Path, *, profile: str, labels: dict[str, Any]) -> dict[str, Any]:
    from src.services.transcription.asr_providers import transcribe_with_provider

    start = time.time()
    with ResourceSampler() as sampler:
        result = transcribe_with_provider(
            audio_path=str(path),
            language="vi",
            profile=profile,
            enable_diarization=False,
            diarization_method="none",
            task_id=f"benchmark-{path.stem}",
        )
    wall_time = time.time() - start
    duration = float(result.get("duration") or 0.0)
    text = result.get("text", "")
    label_set = labels.get(path.name) or labels.get(str(path)) or {}

    return {
        "file": str(path),
        "profile": profile,
        "provider": result.get("provider"),
        "model_info": result.get("model_info", {}),
        "duration_seconds": duration,
        "wall_time_seconds": wall_time,
        "rtf": wall_time / duration if duration > 0 else None,
        "peak_ram_mb": sampler.peak_ram_mb,
        "peak_vram_mb": sampler.peak_vram_mb,
        "failure": None,
        "warnings": result.get("warnings", []),
        "text_chars": len(text),
        "non_speech_hallucination_chars": len(text)
        if any(token in path.name.lower() for token in ["silence", "non-speech", "nonspeech"])
        else None,
        "phone_like_count": len(PHONE_RE.findall(text)),
        "date_like_count": len(DATE_RE.findall(text)),
        "money_like_count": len(MONEY_RE.findall(text)),
        "phone_recall": recall_for(text, label_set.get("phone", [])),
        "date_recall": recall_for(text, label_set.get("date", [])),
        "money_recall": recall_for(text, label_set.get("money", [])),
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    successes = [item for item in results if not item.get("failure")]
    rtf_values = [item["rtf"] for item in successes if item.get("rtf") is not None]
    peak_ram = [item["peak_ram_mb"] for item in successes if item.get("peak_ram_mb") is not None]
    peak_vram = [item["peak_vram_mb"] for item in successes if item.get("peak_vram_mb") is not None]
    return {
        "file_count": len(results),
        "failure_count": len(results) - len(successes),
        "avg_rtf": sum(rtf_values) / len(rtf_values) if rtf_values else None,
        "peak_ram_mb": max(peak_ram) if peak_ram else None,
        "peak_vram_mb": max(peak_vram) if peak_vram else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Lite ASR profiles on local audio files.")
    parser.add_argument("--profile", default="rtx2050_safe")
    parser.add_argument("--files", nargs="+", required=True)
    parser.add_argument("--labels-json", type=Path)
    parser.add_argument("--output", type=Path, default=Path("lite_benchmark.json"))
    args = parser.parse_args()

    labels = load_labels(args.labels_json)
    results: list[dict[str, Any]] = []
    for file_name in args.files:
        path = Path(file_name).resolve()
        try:
            results.append(benchmark_file(path, profile=args.profile, labels=labels))
        except Exception as exc:
            results.append(
                {
                    "file": str(path),
                    "profile": args.profile,
                    "failure": f"{exc.__class__.__name__}: {exc}",
                }
            )

    payload = {
        "benchmark_gate": {
            "set": [
                "5 clean Vietnamese files",
                "5 noisy Vietnamese files",
                "3 silence/non-speech files",
                "2 conversations over 10 minutes",
            ],
            "metrics": [
                "RTF",
                "Peak RAM",
                "Peak VRAM",
                "Failure count",
                "Non-speech hallucination",
                "Phone/date/money extraction recall",
            ],
        },
        "summary": summarize(results),
        "results": results,
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"Wrote {args.output}")
    return 0 if payload["summary"]["failure_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
