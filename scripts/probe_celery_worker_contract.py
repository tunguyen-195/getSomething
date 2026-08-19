"""Probe the live Celery worker and fail when its Summary request contract is stale."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

from src.worker.runtime_contract import (  # noqa: E402
    WORKER_RUNTIME_CONTRACT_TASK,
    build_worker_runtime_contract,
    compare_worker_runtime_contracts,
)
from src.worker.tasks.summarize_task import summarize_transcript_task  # noqa: E402
from src.worker.worker import celery_app  # noqa: E402


def probe_worker_contract(timeout_seconds: float) -> dict:
    expected = build_worker_runtime_contract(summarize_transcript_task.run)
    registered_workers: dict[str, list[str]] = {}
    errors: list[str] = []
    try:
        registered = celery_app.control.inspect(timeout=timeout_seconds).registered()
        if not isinstance(registered, dict) or not registered:
            errors.append("no Celery worker returned its registered task set")
        else:
            registered_workers = {
                str(worker): sorted(str(task) for task in tasks)
                for worker, tasks in registered.items()
                if isinstance(tasks, list)
            }
            for worker, task_names in registered_workers.items():
                if WORKER_RUNTIME_CONTRACT_TASK not in task_names:
                    errors.append(
                        f"worker {worker} does not register {WORKER_RUNTIME_CONTRACT_TASK}"
                    )
    except Exception as exc:
        errors.append(f"worker registration probe failed: {type(exc).__name__}")

    observed = None
    if not errors:
        try:
            async_result = celery_app.send_task(WORKER_RUNTIME_CONTRACT_TASK)
            observed = async_result.get(
                timeout=timeout_seconds,
                disable_sync_subtasks=False,
            )
            errors.extend(compare_worker_runtime_contracts(expected, observed))
        except Exception as exc:
            errors.append(f"worker contract probe failed: {type(exc).__name__}")
    return {
        "gate": "celery-worker-summary-request-contract",
        "status": "PASS" if not errors else "FAIL",
        "expected": expected,
        "observed": observed,
        "registered_workers": registered_workers,
        "errors": errors,
    }


def _positive_timeout(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=_positive_timeout, default=15.0)
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Print the expected local contract without contacting Celery.",
    )
    parser.add_argument("--json", action="store_true", help="Emit compact JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.local_only:
        report = {
            "gate": "celery-worker-summary-request-contract",
            "status": "LOCAL_ONLY",
            "expected": build_worker_runtime_contract(
                summarize_transcript_task.run
            ),
            "observed": None,
            "registered_workers": {},
            "errors": [],
        }
    else:
        report = probe_worker_contract(args.timeout)

    if args.json:
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"PASS", "LOCAL_ONLY"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
