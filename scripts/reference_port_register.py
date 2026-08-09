"""Build and verify the content-addressed reference reuse register.

The ``.yaml`` output is emitted as JSON, which is valid YAML 1.2, so the
release gate does not depend on a YAML parser that may be unavailable offline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping


REGISTER_SCHEMA_VERSION = "reference-port-register-v1"
POLICY_VERSION = "reference-reuse-policy-v1"
DEFAULT_REVIEW = Path("docs/reviews/reference-repository-reuse-audit-2026-08-09.md")
DEFAULT_EVIDENCE = Path("docs/research/reference-repo-audit/evidence.json")
DEFAULT_SOURCE_SPEC = Path(
    "docs/research/reference-repo-audit/source-evidence-spec.json"
)
DEFAULT_OUTPUT = Path("docs/provenance/reference-port-register.yaml")

_TABLE_ROW = re.compile(
    r"^\| `(?P<recommendation_id>(?:PR|CH)-[^`]+)` "
    r"\| (?P<decision>[^|]+) \| (?P<item>[^|]+) \| [^|]+ "
    r"\| (?P<action>[^|]+) \|$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{40}$")
_DECISIONS = {"ADAPT", "RESEARCH_CHALLENGER", "REJECT"}
_TRACKED_STATES = {"tracked_clean", "modified", "untracked"}


class PortRegisterError(ValueError):
    """Raised when the reuse register cannot be built or verified."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    rendered = json.dumps(
        dict(payload),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PortRegisterError(f"cannot read JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise PortRegisterError(f"JSON artifact must be an object: {path}")
    return value


def _parse_review(review_path: Path) -> dict[str, dict[str, str]]:
    try:
        lines = review_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise PortRegisterError(f"cannot read reuse review: {review_path}") from exc

    entries: dict[str, dict[str, str]] = {}
    for line in lines:
        match = _TABLE_ROW.match(line.strip())
        if not match:
            continue
        raw = {key: value.strip() for key, value in match.groupdict().items()}
        raw_decision = raw.pop("decision")
        decision = raw_decision.split("/", maxsplit=1)[0].strip()
        if decision not in _DECISIONS:
            raise PortRegisterError(f"unsupported reuse decision: {raw_decision}")
        recommendation_id = raw.pop("recommendation_id")
        if recommendation_id in entries:
            raise PortRegisterError(
                f"duplicate recommendation in review: {recommendation_id}"
            )
        entries[recommendation_id] = {
            **raw,
            "decision": decision,
            "pending_license": str("PENDING_LICENSE" in raw_decision).lower(),
        }
    if not entries:
        raise PortRegisterError("reuse review does not contain a decision matrix")
    return entries


def _source_records(evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    source_evidence = evidence.get("source_evidence")
    if not isinstance(source_evidence, Mapping):
        raise PortRegisterError("evidence bundle is missing source_evidence")
    if source_evidence.get("errors") != []:
        raise PortRegisterError("source evidence contains unresolved errors")
    records = source_evidence.get("records")
    if not isinstance(records, list) or not records:
        raise PortRegisterError("source evidence does not contain records")
    if not all(isinstance(item, Mapping) for item in records):
        raise PortRegisterError("source evidence contains a non-object record")
    return [dict(item) for item in records]


def _source_key(record: Mapping[str, Any]) -> tuple[str, str, str, tuple[str, ...]]:
    recommendation_ids = record.get("recommendation_ids")
    if not isinstance(recommendation_ids, list) or not recommendation_ids:
        raise PortRegisterError("source record is missing recommendation IDs")
    return (
        str(record.get("repo", "")),
        str(record.get("path", "")),
        str(record.get("purpose", "")),
        tuple(sorted(str(item) for item in recommendation_ids)),
    )


def _validate_source_evidence(
    evidence: Mapping[str, Any],
    source_spec: Mapping[str, Any],
    source_spec_path: Path,
    records: list[dict[str, Any]],
) -> None:
    """Fail closed before deriving the durable port register."""

    source_evidence = evidence["source_evidence"]
    if source_evidence.get("spec_sha256") != _sha256_file(source_spec_path):
        raise PortRegisterError("source evidence does not match the source spec")

    sources = source_spec.get("sources")
    if not isinstance(sources, list) or not sources:
        raise PortRegisterError("source spec does not contain sources")
    if not all(isinstance(item, Mapping) for item in sources):
        raise PortRegisterError("source spec contains a non-object source")

    expected_keys = [_source_key(item) for item in sources]
    actual_keys = [_source_key(item) for item in records]
    if len(set(expected_keys)) != len(expected_keys):
        raise PortRegisterError("source spec contains duplicate source records")
    if len(set(actual_keys)) != len(actual_keys):
        raise PortRegisterError("source evidence contains duplicate source records")
    if set(actual_keys) != set(expected_keys):
        raise PortRegisterError("source evidence records do not match the source spec")

    for record in records:
        digest = str(record.get("sha256", ""))
        if not _SHA256_RE.fullmatch(digest):
            raise PortRegisterError("source evidence contains an invalid SHA-256")
        if record.get("source_identity") != f"sha256:{digest}":
            raise PortRegisterError("source evidence contains an invalid identity")
        size = record.get("bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise PortRegisterError("source evidence contains an invalid byte count")
        if record.get("tracked_state") not in _TRACKED_STATES:
            raise PortRegisterError("source evidence contains an invalid tracked state")
        if not _GIT_OBJECT_RE.fullmatch(str(record.get("head_commit", ""))):
            raise PortRegisterError("source evidence contains an invalid HEAD commit")
        for field in ("head_git_blob", "worktree_git_blob"):
            value = record.get(field)
            if value is not None and not _GIT_OBJECT_RE.fullmatch(str(value)):
                raise PortRegisterError(
                    f"source evidence contains an invalid Git object: {field}"
                )


def _repo_snapshot(evidence: Mapping[str, Any], label: str) -> dict[str, Any]:
    for item in evidence.get("repositories", []):
        if isinstance(item, Mapping) and item.get("label") == label:
            git = item.get("git") if isinstance(item.get("git"), Mapping) else {}
            return {
                "label": label,
                "audit_root": item.get("root"),
                "head_commit": git.get("head"),
                "branch": git.get("branch"),
                "dirty": git.get("dirty"),
            }
    raise PortRegisterError(f"evidence bundle is missing repository: {label}")


def _registered_source(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "repo": record.get("repo"),
        "path": record.get("path"),
        "purpose": record.get("purpose"),
        "tracked_state": record.get("tracked_state"),
        "head_commit": record.get("head_commit"),
        "head_git_blob": record.get("head_git_blob"),
        "worktree_git_blob": record.get("worktree_git_blob"),
        "bytes": record.get("bytes"),
        "sha256": record.get("sha256"),
        "source_identity": record.get("source_identity"),
    }


def build_register(root: Path) -> dict[str, Any]:
    """Build a deterministic register from the independently audited artifacts."""

    root = root.resolve()
    review_path = root / DEFAULT_REVIEW
    evidence_path = root / DEFAULT_EVIDENCE
    source_spec_path = root / DEFAULT_SOURCE_SPEC
    review = _parse_review(review_path)
    evidence = _load_json(evidence_path)
    source_spec = _load_json(source_spec_path)
    records = _source_records(evidence)
    _validate_source_evidence(evidence, source_spec, source_spec_path, records)

    expected_ids = {
        recommendation_id
        for item in source_spec.get("sources", [])
        if isinstance(item, Mapping)
        for recommendation_id in item.get("recommendation_ids", [])
    }
    if set(review) != expected_ids:
        missing = sorted(expected_ids - set(review))
        unexpected = sorted(set(review) - expected_ids)
        raise PortRegisterError(
            f"review/source-spec recommendation mismatch; missing={missing}, "
            f"unexpected={unexpected}"
        )

    records_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        for recommendation_id in record.get("recommendation_ids", []):
            records_by_id[str(recommendation_id)].append(record)

    entries: list[dict[str, Any]] = []
    for recommendation_id in sorted(expected_ids):
        metadata = review[recommendation_id]
        decision = metadata["decision"]
        pending_license = metadata["pending_license"] == "true"
        sources = sorted(
            (_registered_source(record) for record in records_by_id[recommendation_id]),
            key=lambda item: (str(item["repo"]), str(item["path"])),
        )
        if not sources:
            raise PortRegisterError(
                f"recommendation has no content-addressed source: {recommendation_id}"
            )
        if decision == "REJECT":
            license_status = "not_applicable_rejected"
            implementation_status = "prohibited"
            use_scope = "negative_control_only"
        else:
            if not pending_license:
                raise PortRegisterError(
                    f"reusable recommendation lacks PENDING_LICENSE: {recommendation_id}"
                )
            license_status = "pending_owner_authorization"
            implementation_status = "blocked_pending_license"
            use_scope = (
                "benchmark_challenger_only"
                if decision == "RESEARCH_CHALLENGER"
                else "target_reimplementation_only"
            )
        entries.append(
            {
                "recommendation_id": recommendation_id,
                "decision": decision,
                "reusable_item": metadata["item"],
                "target_action": metadata["action"],
                "license_status": license_status,
                "implementation_status": implementation_status,
                "use_scope": use_scope,
                "copy_code_allowed": False,
                "source_snapshot_status": (
                    "clean_content_addressed"
                    if all(item["tracked_state"] == "tracked_clean" for item in sources)
                    else "dirty_content_addressed"
                ),
                "sources": sources,
            }
        )

    payload: dict[str, Any] = {
        "schema_version": REGISTER_SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "source_evidence_schema_version": evidence.get("schema_version"),
        "source_evidence_spec_sha256": _sha256_file(source_spec_path),
        "review_sha256": _sha256_file(review_path),
        "audit_generated_at_utc": evidence.get("generated_at_utc"),
        "repositories": {
            label: _repo_snapshot(evidence, label) for label in ("main", "lite", "cherry")
        },
        "default_copy_policy": "forbidden_until_explicit_authorization",
        "entries": entries,
    }
    payload["register_sha256"] = _canonical_sha256(payload)
    return payload


def validate_register(root: Path, register: Mapping[str, Any] | None = None) -> list[str]:
    """Return stable failure codes for a stale, forged, or permissive register."""

    root = root.resolve()
    expected = build_register(root)
    if register is None:
        register = _load_json(root / DEFAULT_OUTPUT)
    actual = dict(register)
    failures: list[str] = []
    if actual.get("schema_version") != REGISTER_SCHEMA_VERSION:
        failures.append("register:schema_version")
    recorded_hash = actual.get("register_sha256")
    unhashed = dict(actual)
    unhashed.pop("register_sha256", None)
    if recorded_hash != _canonical_sha256(unhashed):
        failures.append("register:self_hash")
    if actual != expected:
        failures.append("register:locked_content")

    entries = actual.get("entries")
    if not isinstance(entries, list):
        failures.append("register:entries")
        return sorted(set(failures))
    for entry in entries:
        if not isinstance(entry, Mapping):
            failures.append("register:entry_type")
            continue
        recommendation_id = str(entry.get("recommendation_id", "unknown"))
        if entry.get("copy_code_allowed") is not False:
            failures.append(f"register:copy_allowed:{recommendation_id}")
        decision = entry.get("decision")
        if decision not in _DECISIONS:
            failures.append(f"register:decision:{recommendation_id}")
        if decision != "REJECT" and entry.get("license_status") != (
            "pending_owner_authorization"
        ):
            failures.append(f"register:license_gate:{recommendation_id}")
        for source in entry.get("sources", []):
            if not isinstance(source, Mapping) or not _SHA256_RE.fullmatch(
                str(source.get("sha256", ""))
            ):
                failures.append(f"register:source_hash:{recommendation_id}")
    return sorted(set(failures))


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    if args.command == "build":
        register = build_register(root)
        _write_json(output, register)
        print(output.resolve())
        return 0

    failures = validate_register(root, _load_json(output))
    print(
        json.dumps(
            {"valid": not failures, "register": str(output.resolve()), "failures": failures},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
