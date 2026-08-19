"""Benchmark bounded T4 contradiction discovery for collision and unique inputs."""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.investigation.claim_semantics import (  # noqa: E402
    extract_semantic_roles,
)
from src.services.investigation.contracts import (  # noqa: E402
    sha256_canonical_json,
    sha256_utf8,
)
from src.services.investigation.contradictions import (  # noqa: E402
    discover_contradictions,
)
from src.services.investigation.release_adapter import (  # noqa: E402
    capture_repository_state,
)
from src.services.investigation.verification_contracts import (  # noqa: E402
    SemanticClaimFrame,
)

DEFAULT_SIZES = (100, 500, 1_000, 2_000)
LATENCY_BUDGET_MS = {100: 3_000, 500: 15_000, 1_000: 30_000, 2_000: 60_000}
MEMORY_BUDGET_MIB = {100: 192, 500: 384, 1_000: 512, 2_000: 768}
DEFAULT_OUTPUT = Path("docs/evals/runs/t4/contradiction-matrix-latest.json")


def _frame(index: int, *, polarity: str, collision: bool) -> SemanticClaimFrame:
    subject = "Minh" if collision else f"DoiTuong{index}"
    statement = (
        f"{subject} không đến điểm hẹn."
        if polarity == "negated"
        else f"{subject} đến điểm hẹn."
    )
    candidate_ref = f"candidate-{index:06d}"
    evidence_ref = f"evidence-{index:06d}"
    payload = {
        "semantic_policy_version": "investigation-semantic-policy-v1.1",
        "candidate_ref": candidate_ref,
        "candidate_sha256": sha256_canonical_json({"candidate": candidate_ref}),
        "source_revision_id": "srcv1:" + "a" * 64,
        "segment_id": f"segment-{index:06d}",
        "raw_char_start": index * 64,
        "raw_char_end": index * 64 + len(statement),
        "quote_sha256": sha256_utf8(statement),
        "claim_type": "event.arrival",
        "candidate_statement": statement,
        "source_assertion": statement,
        "polarity": polarity,
        "source_modality": polarity,
        "atomicity": "atomic",
        "atomic_units": (statement,),
        "evidence_refs": (evidence_ref,),
        "speaker_id": f"SPEAKER_{index % 8}",
        "exact_values": (),
        "source_roles": extract_semantic_roles(statement).model_dump(
            mode="json",
            exclude_none=True,
        ),
        "safe_attributes": {
            "semantic_policy_version": "investigation-semantic-policy-v1.1"
        },
    }
    frame_hash = sha256_canonical_json(payload)
    return SemanticClaimFrame(
        frame_id=f"semv1:{frame_hash}",
        frame_sha256=frame_hash,
        **payload,
    )


def _inputs(candidate_count: int, *, collision: bool):
    frames: dict[str, SemanticClaimFrame] = {}
    candidate_to_claim: dict[str, str] = {}
    for index in range(candidate_count):
        polarity = (
            "affirmed" if not collision or index < candidate_count // 2 else "negated"
        )
        frame = _frame(index, polarity=polarity, collision=collision)
        frames[frame.candidate_ref] = frame
        candidate_to_claim[frame.candidate_ref] = f"claim-{index:06d}"
    return frames, candidate_to_claim


def _measure(candidate_count: int, *, collision: bool) -> dict[str, object]:
    frames, candidate_to_claim = _inputs(candidate_count, collision=collision)
    gc.collect()
    started = time.perf_counter()
    first = discover_contradictions(
        frames=frames,
        candidate_to_claim=candidate_to_claim,
    )
    second = discover_contradictions(
        frames=frames,
        candidate_to_claim=candidate_to_claim,
    )
    latency_ms = (time.perf_counter() - started) * 1_000

    gc.collect()
    tracemalloc.start()
    discover_contradictions(
        frames=frames,
        candidate_to_claim=candidate_to_claim,
    )
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_mib = peak_bytes / (1024 * 1024)

    expected_pairs = (
        (candidate_count // 2) * (candidate_count - candidate_count // 2)
        if collision
        else 0
    )
    expected_records = 1 if collision and candidate_count >= 2 else 0
    grouped_pairs = sum(item.total_pair_count for item in first)
    materialized_pairs = sum(item.materialized_pair_count for item in first)
    passed = (
        first == second
        and len(first) == expected_records
        and grouped_pairs == expected_pairs
        and materialized_pairs == 0
        and latency_ms <= LATENCY_BUDGET_MS[candidate_count]
        and peak_mib <= MEMORY_BUDGET_MIB[candidate_count]
    )
    return {
        "shape": "collision" if collision else "unique",
        "candidate_count": candidate_count,
        "record_count": len(first),
        "grouped_pair_count": grouped_pairs,
        "materialized_pair_count": materialized_pairs,
        "deterministic": first == second,
        "latency_ms": latency_ms,
        "latency_budget_ms": LATENCY_BUDGET_MS[candidate_count],
        "peak_memory_mib": peak_mib,
        "peak_memory_budget_mib": MEMORY_BUDGET_MIB[candidate_count],
        "passed": passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    results = [
        _measure(size, collision=collision)
        for size in DEFAULT_SIZES
        for collision in (False, True)
    ]
    state = capture_repository_state(PROJECT_ROOT)
    report = {
        "protocol_version": "t4-contradiction-performance-v1.0",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "git_revision": state.git_revision,
        "git_dirty": state.git_dirty,
        "git_untracked": state.git_untracked,
        "source_hashes": {
            name: state.verification_source_hashes[name]
            for name in (
                "claim_semantics.py",
                "contradictions.py",
                "verification_contracts.py",
            )
        },
        "results": results,
        "passed": all(bool(item["passed"]) for item in results),
        "limitations": [
            "This benchmark isolates contradiction discovery from full T3/T4 replay.",
            "Thresholds are release gates for this workstation, not universal SLAs.",
        ],
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"passed": report["passed"], "output": str(output), "results": results},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
