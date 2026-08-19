"""Dry-run or recover stale Summary tasks after checking live Celery ownership."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

from src.database.config.database import SessionLocal  # noqa: E402
from src.worker.summary_reconciliation import (  # noqa: E402
    inspect_worker_activity,
    reconciliation_apply_refusal_reason,
    reconcile_stale_summary_tasks,
    stale_cutoff,
)
from src.worker.worker import celery_app  # noqa: E402


def _at_least_sixty(value: str) -> int:
    parsed = int(value)
    if parsed < 60:
        raise argparse.ArgumentTypeError("value must be at least 60 seconds")
    return parsed


def _positive_timeout(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--older-than-seconds", type=_at_least_sixty, default=900)
    parser.add_argument("--inspect-timeout", type=_positive_timeout, default=5.0)
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--allow-no-workers",
        action="store_true",
        help="Permit apply when no Celery worker replies; use only after verifying workers are stopped.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    activity = inspect_worker_activity(celery_app, args.inspect_timeout)
    refusal_reason = reconciliation_apply_refusal_reason(
        activity,
        allow_no_workers=args.allow_no_workers,
    )
    if args.apply and refusal_reason is not None:
        report = {
            "gate": "stale-summary-reconciliation",
            "status": "REFUSED",
            "reason": refusal_reason,
            "worker_activity": {
                "worker_names": list(activity.worker_names),
                "summary_task_ids": sorted(activity.summary_task_ids),
                "errors": list(activity.errors),
            },
        }
        print(json.dumps(report, ensure_ascii=args.json, indent=None if args.json else 2))
        return 2

    now_utc = datetime.utcnow()
    cutoff_utc = stale_cutoff(now_utc, args.older_than_seconds)
    with SessionLocal() as db:
        reconciliation = reconcile_stale_summary_tasks(
            db,
            cutoff_utc=cutoff_utc,
            active_task_ids=activity.summary_task_ids,
            task_ids=frozenset(args.task_id) if args.task_id else None,
            apply=args.apply,
            now_utc=now_utc,
        )
    report = {
        "gate": "stale-summary-reconciliation",
        "status": "APPLIED" if args.apply else "DRY_RUN",
        "worker_activity": {
            "worker_names": list(activity.worker_names),
            "summary_task_ids": sorted(activity.summary_task_ids),
            "errors": list(activity.errors),
        },
        "reconciliation": reconciliation.as_dict(),
    }
    print(
        json.dumps(
            report,
            ensure_ascii=args.json,
            indent=None if args.json else 2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
