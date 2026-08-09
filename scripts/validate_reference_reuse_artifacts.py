"""Validate the locked reference-repository audit and implementation artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.reference_port_register import PortRegisterError, validate_register


ARTIFACTS = {
    "protocol": "docs/research/reference-repo-reuse-audit-protocol-2026-08-09.md",
    "source_spec": "docs/research/reference-repo-audit/source-evidence-spec.json",
    "evidence": "docs/research/reference-repo-audit/evidence.json",
    "hardware_profile": "docs/research/reference-repo-audit/hardware-profile.json",
    "prompt_spec": "docs/research/cand-audio-intelligence-prompt-technique-spec-2026-08-09.md",
    "review": "docs/reviews/reference-repository-reuse-audit-2026-08-09.md",
    "plan": "docs/plans/2026-08-09-reference-reuse-offline-cand-plan.md",
    "plan_audit": "docs/reviews/reference-repository-reuse-plan-audit-2026-08-09.md",
    "port_register": "docs/provenance/reference-port-register.yaml",
}

EXPECTED_RECOMMENDATION_IDS = {
    "PR-MODEL-ARTIFACT-FACTS",
    "PR-EVIDENCE-REF-CONTRACT",
    "PR-HUMAN-REVIEW",
    "PR-ROW-LOCK-REVISION",
    "PR-METADATA-DETAIL-API",
    "PR-GPU-LEASE",
    "PR-RUNTIME-PROFILE",
    "PR-REJECT-AUTH-FALLBACK",
    "PR-REJECT-PHYSICAL-ARCHIVE",
    "PR-REJECT-CREATE-ALL",
    "PR-REJECT-JSON-MONOLITH",
    "PR-REJECT-FIXED-PROMPT",
    "PR-REJECT-NETWORK-DEFAULT",
    "CH-ARTIFACT-DISCIPLINE",
    "CH-SELECTIVE-ASR",
    "CH-PORTS-ADAPTERS",
    "CH-GPU-QUEUE",
    "CH-STAGE-ARTIFACTS",
    "CH-RESEARCH-CHALLENGERS",
    "CH-MANUAL-AUDIT",
    "CH-REJECT-SAGE-THRESHOLD",
    "CH-REJECT-JOB-MANAGER",
    "CH-REJECT-MUTATION",
    "CH-REJECT-VLLM",
    "CH-REJECT-FIXED-PROMPT",
    "CH-REJECT-MODEL-INVENTORY",
    "CH-REJECT-DIRTY-RELEASE",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_check(
    name: str,
    text: str,
    required_terms: list[str],
    forbidden_terms: list[str] | None = None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    lowered = text.lower()
    for term in required_terms:
        checks.append(
            {
                "id": f"{name}:contains:{term}",
                "passed": term.lower() in lowered,
            }
        )
    for term in forbidden_terms or []:
        checks.append(
            {
                "id": f"{name}:forbids:{term}",
                "passed": term.lower() not in lowered,
            }
        )
    return checks


def validate(root: Path) -> dict[str, Any]:
    artifacts: dict[str, dict[str, Any]] = {}
    checks: list[dict[str, Any]] = []
    contents: dict[str, str] = {}

    for name, relative in ARTIFACTS.items():
        path = root / relative
        exists = path.is_file() and path.stat().st_size > 0
        checks.append({"id": f"artifact:{name}:exists", "passed": exists})
        if not exists:
            continue
        artifacts[name] = {
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        if path.suffix.lower() == ".md":
            contents[name] = path.read_text(encoding="utf-8")

    source_spec_path = root / ARTIFACTS["source_spec"]
    source_spec: dict[str, Any] = {}
    if source_spec_path.is_file():
        try:
            source_spec = json.loads(source_spec_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            source_spec = {}

    evidence_path = root / ARTIFACTS["evidence"]
    if evidence_path.is_file():
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            evidence = {}
        labels = {
            item.get("label")
            for item in evidence.get("repositories", [])
            if isinstance(item, dict)
        }
        source_evidence = evidence.get("source_evidence", {})
        source_records = source_evidence.get("records", [])
        recommendation_ids = {
            recommendation_id
            for record in source_records
            if isinstance(record, dict)
            for recommendation_id in record.get("recommendation_ids", [])
        }
        expected_source_count = len(source_spec.get("sources", []))
        checks.extend(
            [
                {
                    "id": "evidence:schema_version",
                    "passed": evidence.get("schema_version")
                    == "reference-repo-audit-v2",
                },
                {
                    "id": "evidence:repository_labels",
                    "passed": labels == {"main", "lite", "cherry"},
                },
                {
                    "id": "evidence:pair_comparisons",
                    "passed": len(evidence.get("comparison", {}).get("pairs", [])) == 3,
                },
                {
                    "id": "evidence:source_spec_hash",
                    "passed": bool(source_spec_path.is_file())
                    and source_evidence.get("spec_sha256")
                    == sha256_file(source_spec_path),
                },
                {
                    "id": "evidence:source_record_count",
                    "passed": expected_source_count > 0
                    and len(source_records) == expected_source_count,
                },
                {
                    "id": "evidence:source_record_errors",
                    "passed": source_evidence.get("errors") == [],
                },
                {
                    "id": "evidence:source_record_identity",
                    "passed": bool(source_records)
                    and all(
                        isinstance(record.get("bytes"), int)
                        and record["bytes"] >= 0
                        and len(record.get("sha256", "")) == 64
                        and record.get("source_identity")
                        == f"sha256:{record.get('sha256')}"
                        and record.get("tracked_state")
                        in {"tracked_clean", "modified", "untracked"}
                        and len(record.get("head_commit", "")) == 40
                        for record in source_records
                    ),
                },
                {
                    "id": "evidence:recommendation_coverage",
                    "passed": recommendation_ids == EXPECTED_RECOMMENDATION_IDS,
                },
            ]
        )

    hardware_path = root / ARTIFACTS["hardware_profile"]
    if hardware_path.is_file():
        try:
            hardware = json.loads(hardware_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            hardware = {}
        checks.extend(
            [
                {
                    "id": "hardware:schema_version",
                    "passed": hardware.get("schema_version")
                    == "offline-hardware-profile-v1",
                },
                {
                    "id": "hardware:profile_id",
                    "passed": hardware.get("profile_id") == "cand-dev-win4070s-12g-v1",
                },
                {
                    "id": "hardware:gpu_memory",
                    "passed": hardware.get("gpu", {}).get("memory_mib") == 12282,
                },
                {
                    "id": "hardware:promotion_policy",
                    "passed": "production requires a separate signed target profile"
                    in hardware.get("promotion_policy", "").lower(),
                },
            ]
        )

    if "protocol" in contents:
        checks += text_check(
            "protocol",
            contents["protocol"],
            [
                "R1",
                "R10",
                "ADOPT",
                "ADAPT",
                "REJECT",
                "network-denial",
                "deadlock-safe",
            ],
            ["TBD"],
        )
    if "review" in contents:
        checks += text_check(
            "review",
            contents["review"],
            [
                "Critical 1",
                "SpeechToInfomation-pr",
                "cherry_core",
                "PhoGuard",
                "SAGE",
                "T4",
                "LICENSE",
                "Critical 6",
                "deadlock",
                "proxy labels",
                "original-audio",
                "PENDING_LICENSE",
            ],
            ["TBD"],
        )
        checks.extend(
            {
                "id": f"review:recommendation:{recommendation_id}",
                "passed": recommendation_id in contents["review"],
            }
            for recommendation_id in sorted(EXPECTED_RECOMMENDATION_IDS)
        )
    if "prompt_spec" in contents:
        checks += text_check(
            "prompt_spec",
            contents["prompt_spec"],
            [
                "Prompt P1",
                "Prompt P5",
                "reported assertion",
                "omission critic",
                "HumanReviewAttestation",
                "network-denial",
                "chain-of-thought",
                "correction_revision",
                "original-audio",
                "corroborated world finding",
                "Source-assertion-to-world-fact leakage",
            ],
            ["TBD"],
        )
    if "plan" in contents:
        checks += text_check(
            "plan",
            contents["plan"],
            [
                "Phase R0",
                "Phase R9",
                "reported speech",
                "subject/object reversal",
                "legal hold",
                "Alembic",
                "air-gapped",
                "TranscriptCorrectionRevision",
                "deadlock",
                "fresh, unseen sealed release holdout",
                "sealed release holdout",
                "benchmark-candidate",
                "cand-dev-win4070s-12g-v1",
            ],
            ["TBD"],
        )
    if "plan_audit" in contents:
        checks += text_check(
            "plan_audit",
            contents["plan_audit"],
            [
                "Verdict: PASS",
                "source-evidence v2",
                "corroborated world finding",
                "sealed release holdout",
                "ADAPT / PENDING_LICENSE",
                "benchmark-candidate",
                "hardware profile",
                "T4 remains a separate",
            ],
            ["TBD"],
        )

    try:
        register_failures = validate_register(root)
    except PortRegisterError:
        register_failures = ["register:unreadable"]
    checks.append(
        {
            "id": "port_register:locked_and_fail_closed",
            "passed": not register_failures,
        }
    )
    checks.extend(
        {
            "id": f"port_register:failure:{failure}",
            "passed": False,
        }
        for failure in register_failures
    )

    failed = [check["id"] for check in checks if not check["passed"]]
    return {
        "schema_version": "reference-reuse-validation-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "valid": not failed,
        "checks_total": len(checks),
        "checks_failed": failed,
        "checks": checks,
        "artifacts": artifacts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    report = validate(root)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(output.resolve())
    else:
        print(rendered, end="")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
