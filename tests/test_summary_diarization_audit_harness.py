from __future__ import annotations

import hashlib
import json
from pathlib import Path

import scripts.audit_pyannote_migration_config as migration_audit
import scripts.audit_summary_diarization_readiness as readiness
from scripts.audit_summary_diarization_readiness import (
    CANONICAL_ROOT,
    PACKAGE_EVIDENCE_REQUIREMENTS,
    _canonical_repo,
    _evidence_artifact_pass,
    _package_evidence_state,
    _plan_package_allowlists,
    _primary_source_state,
    _pyannote_migration_audit_state,
    _source_hashes,
    _validated_output,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _patch_migration_payload(monkeypatch, payload: dict[str, object]) -> None:
    original_load = readiness._load_manifest

    def load(path: Path) -> dict[str, object] | None:
        if path.name == "2026-08-09-pyannote-migration-config-audit.json":
            return payload
        return original_load(path)

    monkeypatch.setattr(readiness, "_load_manifest", load)


def test_plan_and_validator_package_sets_match_exactly() -> None:
    allowlists, errors = _plan_package_allowlists(CANONICAL_ROOT)

    assert errors == []
    assert set(allowlists) == set(PACKAGE_EVIDENCE_REQUIREMENTS)
    for package, requirement in PACKAGE_EVIDENCE_REQUIREMENTS.items():
        assert requirement["artifact"] in allowlists[package]


def test_readiness_source_map_covers_previously_missing_allowlist_paths() -> None:
    hashes = _source_hashes(CANONICAL_ROOT)

    required = {
        "src/api/endpoints/summary.py",
        "src/services/investigation/discovery.py",
        "src/services/investigation/discovery_contracts.py",
        "src/services/investigation/source_revision.py",
        "tests/eval/whole_audio_coverage_cases.jsonl",
        "docs/reviews/artifacts/x1-speaker-claim-release.json",
        "docs/reviews/artifacts/f1b-file-aware-evidence.json",
    }
    assert required.issubset(hashes)
    assert hashes["tests/eval/whole_audio_coverage_cases.jsonl"] is None


def test_package_evidence_binds_complete_s3_g1_f1a_and_d1_allowlists() -> None:
    allowlists, errors = _plan_package_allowlists(CANONICAL_ROOT)
    state = _package_evidence_state(CANONICAL_ROOT)

    assert errors == []
    for package in ("s3", "g1", "f1a", "d1"):
        artifact = str(PACKAGE_EVIDENCE_REQUIREMENTS[package]["artifact"])
        assert set(state[package]["bound_paths"]) == set(allowlists[package]) - {
            artifact
        }


def test_c1_evidence_cannot_pass_without_bound_dynamic_alembic_path(
    tmp_path: Path,
) -> None:
    harness = tmp_path / "harness.py"
    source = tmp_path / "source.py"
    migration = tmp_path / "src/database/migrations/versions/a1_test.py"
    artifact = tmp_path / "evidence.json"
    migration.parent.mkdir(parents=True)
    harness.write_text("pass\n", encoding="utf-8")
    source.write_text("pass\n", encoding="utf-8")
    migration.write_text("revision = 'a1'\n", encoding="utf-8")

    payload = {
        "schema_version": "rtk-evidence-v1",
        "verdict": "PASS",
        "exit_code": 0,
        "command": ["python", "harness.py"],
        "environment": {"database": "isolated_test"},
        "observed_at": "2026-08-09T16:45:00+07:00",
        "harness_path": "harness.py",
        "harness_sha256": _sha256(harness),
        "alembic_version_path": "src/database/migrations/versions/a1_test.py",
        "source_sha256": {
            "source.py": _sha256(source),
            "src/database/migrations/versions/a1_test.py": _sha256(migration),
        },
        "checks": {"migration_rehearsal_passed": True},
    }
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    assert _evidence_artifact_pass(
        tmp_path,
        artifact,
        {"migration_rehearsal_passed"},
        {"source.py"},
        dynamic_bound_path_field="alembic_version_path",
    )

    payload["source_sha256"].pop("src/database/migrations/versions/a1_test.py")
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    assert not _evidence_artifact_pass(
        tmp_path,
        artifact,
        {"migration_rehearsal_passed"},
        {"source.py"},
        dynamic_bound_path_field="alembic_version_path",
    )


def test_canonical_and_output_guards_reject_out_of_scope_paths(tmp_path: Path) -> None:
    assert _canonical_repo(CANONICAL_ROOT) == CANONICAL_ROOT

    noncanonical = tmp_path / "not-stt"
    try:
        _canonical_repo(noncanonical)
    except ValueError as exc:
        assert "noncanonical workspace" in str(exc)
    else:
        raise AssertionError("noncanonical repo must be rejected")

    try:
        _validated_output(CANONICAL_ROOT, tmp_path / "outside.json")
    except ValueError as exc:
        assert "Audit output must stay" in str(exc)
    else:
        raise AssertionError("out-of-root output must be rejected")


def test_pyannote_migration_audit_is_current_and_source_bound() -> None:
    state = _pyannote_migration_audit_state(CANONICAL_ROOT)

    assert state["valid"] is True
    assert state["migration_verdict"] == "PASS_NO_ADDITIONAL_LOSS"
    assert state["product_verdict"] == "BLOCKED"
    assert state["source_hashes_valid"] is True
    assert state["official_sources_valid"] is True
    assert state["recomputed_local_state_valid"] is True


def test_pyannote_audit_rejects_fabricated_official_semantics(
    monkeypatch,
) -> None:
    artifact_path = (
        CANONICAL_ROOT
        / "docs/reviews/artifacts/2026-08-09-pyannote-migration-config-audit.json"
    )
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["official_sources"]["sources"]["community_1_metadata"][
        "verified_fields"
    ]["revision"] = "0" * 40
    payload["official_sources"]["sources"]["community_1_metadata"][
        "verified_fields"
    ]["license"] = "proprietary"

    _patch_migration_payload(monkeypatch, payload)
    state = readiness._pyannote_migration_audit_state(CANONICAL_ROOT)

    assert state["valid"] is False
    assert state["official_sources_valid"] is False


def test_pyannote_audit_rejects_fabricated_official_provenance(
    monkeypatch,
) -> None:
    artifact_path = (
        CANONICAL_ROOT
        / "docs/reviews/artifacts/2026-08-09-pyannote-migration-config-audit.json"
    )
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    for source in payload["official_sources"]["sources"].values():
        source["url"] = "https://invalid.example/fabricated"
        source["content_bytes"] = 1
        source["content_sha256"] = "0" * 64

    _patch_migration_payload(monkeypatch, payload)
    state = readiness._pyannote_migration_audit_state(CANONICAL_ROOT)

    assert state["valid"] is False
    assert state["official_sources_valid"] is False


def test_primary_source_capture_rejects_url_and_raw_digest_tamper(
    monkeypatch,
) -> None:
    artifact_path = (
        CANONICAL_ROOT
        / "docs/reviews/artifacts/2026-08-09-diarization-primary-source-verification.json"
    )
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["sources"][0]["url"] = "https://invalid.example/fabricated"
    payload["sources"][0]["content_sha256"] = "0" * 64
    original_load = readiness._load_manifest

    def load(path: Path) -> dict[str, object] | None:
        return payload if path == artifact_path else original_load(path)

    monkeypatch.setattr(readiness, "_load_manifest", load)
    state = _primary_source_state(CANONICAL_ROOT)

    assert state["valid"] is False
    assert "community_1_metadata:provenance_invalid" in state["validation_errors"]


def test_pyannote_audit_rejects_digest_from_different_capture(monkeypatch) -> None:
    artifact_path = (
        CANONICAL_ROOT
        / "docs/reviews/artifacts/2026-08-09-pyannote-migration-config-audit.json"
    )
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["official_sources"]["sources"]["community_1_metadata"][
        "content_sha256"
    ] = "8166bdfc98e6e67f494e2121fef2be15b8c0acc713c53aa6fbcf900a5b549f5f"

    _patch_migration_payload(monkeypatch, payload)
    state = readiness._pyannote_migration_audit_state(CANONICAL_ROOT)

    assert state["valid"] is False
    assert state["capture_reference_valid"] is True
    assert state["official_sources_valid"] is False


def test_pyannote_audit_rejects_missing_capture_reference(monkeypatch) -> None:
    artifact_path = (
        CANONICAL_ROOT
        / "docs/reviews/artifacts/2026-08-09-pyannote-migration-config-audit.json"
    )
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["official_sources"].pop("capture_sha256")

    _patch_migration_payload(monkeypatch, payload)
    state = readiness._pyannote_migration_audit_state(CANONICAL_ROOT)

    assert state["valid"] is False
    assert state["capture_reference_valid"] is False
    assert state["official_sources_valid"] is False


def test_pyannote_audit_rejects_self_asserted_pass(monkeypatch) -> None:
    artifact_path = (
        CANONICAL_ROOT
        / "docs/reviews/artifacts/2026-08-09-pyannote-migration-config-audit.json"
    )
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["verdict"] = "PASS"
    payload["exit_code"] = 0
    payload["blockers"] = []
    payload["checks"] = {name: True for name in payload["checks"]}

    _patch_migration_payload(monkeypatch, payload)
    state = readiness._pyannote_migration_audit_state(CANONICAL_ROOT)

    assert state["valid"] is False
    assert state["recomputed_local_state_valid"] is False


def test_pyannote_migration_rejects_truncated_material_rows(monkeypatch) -> None:
    original_read = migration_audit._read_csv_rows

    def truncated_material(path: Path, prefix: str) -> list[dict[str, str]]:
        rows = original_read(path, prefix)
        return rows[:1] if path.name == "material-hashes.csv" else rows

    monkeypatch.setattr(migration_audit, "_read_csv_rows", truncated_material)
    report = migration_audit.build_report(
        CANONICAL_ROOT,
        generated_at="2026-08-09T17:00:00+07:00",
        no_network=True,
    )

    assert report["migration_verdict"] == "BLOCKED"
    assert report["checks"]["migration_inventory_and_hashes_match"] is False
    assert report["migration_evidence"]["material_hash_rows"] == 1


def test_pyannote_migration_rejects_empty_current_e_cache(monkeypatch) -> None:
    original_inventory = migration_audit._file_inventory

    def empty_current_cache(root: Path, repo_root: Path) -> list[dict[str, object]]:
        if root == repo_root / "models/pyannote_cache":
            return []
        return original_inventory(root, repo_root)

    monkeypatch.setattr(migration_audit, "_file_inventory", empty_current_cache)
    report = migration_audit.build_report(
        CANONICAL_ROOT,
        generated_at="2026-08-09T17:00:00+07:00",
        no_network=True,
    )

    assert report["migration_verdict"] == "BLOCKED"
    assert report["checks"]["current_e_cache_matches_destination"] is False
    assert report["migration_evidence"]["current_e_cache_files"] == 0
