"""Audit Pyannote migration, local artifacts, and runtime compatibility."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


CANONICAL_ROOT = Path(r"E:\research\STT")
MIGRATION_EVIDENCE_ROOT = Path(
    r"E:\research\_STT_migration_evidence\2026-08-09-d-to-e"
)
DEFAULT_OUTPUT = Path(
    "docs/reviews/artifacts/2026-08-09-pyannote-migration-config-audit.json"
)
PRIMARY_CAPTURE_PATH = Path(
    "docs/reviews/artifacts/2026-08-09-diarization-primary-source-verification.json"
)
COMMUNITY_1_MODEL_ID = "pyannote/speaker-diarization-community-1"
COMMUNITY_1_REVISION = "3533c8cf8e369892e6b79ff1bf80f7b0286a54ee"
COMMUNITY_1_REQUIRED_FILES = (
    "config.yaml",
    "embedding/pytorch_model.bin",
    "plda/plda.npz",
    "plda/xvec_transform.npz",
    "segmentation/pytorch_model.bin",
)
SOURCE_PATHS = (
    "scripts/audit_pyannote_migration_config.py",
    "scripts/capture_diarization_primary_sources.py",
    str(PRIMARY_CAPTURE_PATH).replace("\\", "/"),
    "src/services/model_runtime/local_artifacts.py",
    "src/services/transcription/models/pyannote_manager.py",
    "src/cherry_core/adapters/diarization/pyannote_adapter.py",
    "src/services/transcription/transcribe_service_v2.py",
    "src/services/transcription/cherry_transcription_service.py",
    "src/core/config.py",
    "requirements.txt",
    "requirements-torch-cu121.txt",
)
def _normalized_absolute(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _canonical_repo(path: Path) -> Path:
    if _normalized_absolute(path) != _normalized_absolute(CANONICAL_ROOT):
        raise ValueError(f"repo must be exactly {CANONICAL_ROOT}")
    return CANONICAL_ROOT


def _validated_output(repo_root: Path, value: Path) -> Path:
    output = value if value.is_absolute() else repo_root / value
    output = output.resolve(strict=False)
    allowed_root = (repo_root / "docs/reviews/artifacts").resolve()
    try:
        within_allowed_root = (
            os.path.commonpath((str(output), str(allowed_root)))
            == str(allowed_root)
        )
    except ValueError:
        within_allowed_root = False
    if not within_allowed_root:
        raise ValueError("output must stay under docs/reviews/artifacts")
    return output


def _observed_at(value: str | None) -> str:
    if value is None:
        return datetime.now().astimezone().isoformat()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("generated-at must include a timezone")
    return parsed.isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_hashes(repo_root: Path) -> dict[str, str | None]:
    return {
        relative: _sha256(repo_root / relative)
        if (repo_root / relative).is_file()
        else None
        for relative in SOURCE_PATHS
    }


def _read_csv_rows(path: Path, prefix: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            relative = str(row.get("RelativePath", "")).replace("/", "\\")
            if relative.casefold().startswith(prefix.casefold()):
                rows.append(dict(row))
    return rows


def _normalized_relative_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().casefold()


def _inventory_map(rows: list[dict[str, str]]) -> dict[str, int] | None:
    inventory: dict[str, int] = {}
    for row in rows:
        relative = _normalized_relative_path(row.get("RelativePath"))
        try:
            length = int(row.get("Length", ""))
        except (TypeError, ValueError):
            return None
        if not relative or length < 0 or relative in inventory:
            return None
        inventory[relative] = length
    return inventory


def _material_map(
    rows: list[dict[str, str]],
) -> dict[str, tuple[int, str, str]] | None:
    material: dict[str, tuple[int, str, str]] = {}
    for row in rows:
        relative = _normalized_relative_path(row.get("RelativePath"))
        source_sha256 = str(row.get("SourceSha256", "")).casefold()
        destination_sha256 = str(row.get("DestinationSha256", "")).casefold()
        try:
            length = int(row.get("Length", ""))
        except (TypeError, ValueError):
            return None
        digests_valid = all(
            len(digest) == 64
            and all(character in "0123456789abcdef" for character in digest)
            for digest in (source_sha256, destination_sha256)
        )
        if (
            not relative
            or length < 0
            or relative in material
            or not digests_valid
            or str(row.get("Match", "")).casefold() != "true"
            or source_sha256 != destination_sha256
        ):
            return None
        material[relative] = (length, source_sha256, destination_sha256)
    return material


def _file_inventory(root: Path, repo_root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        rows.append(
            {
                "path": path.relative_to(repo_root).as_posix(),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return rows


def _installed_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _version_tuple(value: str | None) -> tuple[int, ...]:
    if value is None:
        return ()
    match = re.match(r"^(\d+(?:\.\d+)*)", value)
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def _official_sources(repo_root: Path, no_network: bool) -> dict[str, Any]:
    from scripts.capture_diarization_primary_sources import (
        MIGRATION_SOURCE_IDS,
        source_binding,
        validate_capture_payload,
    )

    capture_path = repo_root / PRIMARY_CAPTURE_PATH
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("primary-source capture must be a JSON object")
    capture_valid, capture_errors = validate_capture_payload(repo_root, payload)
    rows = {
        str(row.get("id")): row
        for row in payload.get("sources", [])
        if isinstance(row, dict) and row.get("id")
    }
    sources = (
        {source_id: source_binding(rows[source_id]) for source_id in MIGRATION_SOURCE_IDS}
        if capture_valid and all(source_id in rows for source_id in MIGRATION_SOURCE_IDS)
        else {}
    )
    return {
        "network_skipped": no_network,
        "capture_path": str(PRIMARY_CAPTURE_PATH).replace("\\", "/"),
        "capture_sha256": _sha256(capture_path),
        "capture_id": payload.get("capture_id"),
        "capture_observed_at": payload.get("observed_at"),
        "capture_valid": capture_valid,
        "capture_errors": capture_errors,
        "sources": sources,
    }


def _runtime_log_observation(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "celery.runtime.e.log"
    if not path.is_file():
        return {"path": str(path), "present": False, "matches": []}
    content = path.read_text(encoding="utf-8", errors="replace")
    matches = [
        {"line": number, "text": line}
        for number, line in enumerate(content.splitlines(), start=1)
        if "No complete local snapshot; offline strict mode refuses provider fallback"
        in line
    ]
    return {
        "path": str(path),
        "present": True,
        "observed_size": path.stat().st_size,
        "matches": matches[-10:],
    }


def build_report(
    repo_root: Path,
    *,
    generated_at: str | None,
    no_network: bool,
) -> dict[str, Any]:
    repo_root = _canonical_repo(repo_root)
    if not MIGRATION_EVIDENCE_ROOT.is_dir():
        raise ValueError(f"missing migration evidence: {MIGRATION_EVIDENCE_ROOT}")

    source_rows = _read_csv_rows(
        MIGRATION_EVIDENCE_ROOT / "source-inventory.csv",
        "models\\pyannote_cache\\",
    )
    destination_rows = _read_csv_rows(
        MIGRATION_EVIDENCE_ROOT / "destination-inventory.csv",
        "models\\pyannote_cache\\",
    )
    material_rows = _read_csv_rows(
        MIGRATION_EVIDENCE_ROOT / "material-hashes.csv",
        "models\\pyannote_cache\\",
    )
    source_inventory = _inventory_map(source_rows)
    destination_inventory = _inventory_map(destination_rows)
    material_inventory = _material_map(material_rows)

    target_files = _file_inventory(repo_root / "models/pyannote", repo_root)
    legacy_cache_files = _file_inventory(repo_root / "models/pyannote_cache", repo_root)
    evidence_rows_consistent = bool(
        source_inventory is not None
        and destination_inventory is not None
        and material_inventory is not None
        and source_inventory == destination_inventory
        and source_inventory
        == {
            relative: length
            for relative, (length, _source_sha256, _destination_sha256) in (
                material_inventory.items()
            )
        }
    )
    material_hashes_match = bool(
        material_inventory is not None
        and len(material_rows) == 9
        and len(material_inventory) == 9
    )
    current_e_cache = {
        _normalized_relative_path(row.get("path")): (
            int(row.get("size", -1)),
            str(row.get("sha256", "")).casefold(),
        )
        for row in legacy_cache_files
    }
    expected_destination = (
        {
            relative: (length, destination_sha256)
            for relative, (length, _source_sha256, destination_sha256) in (
                material_inventory.items()
            )
        }
        if material_inventory is not None
        else {}
    )
    current_e_cache_matches_destination = bool(
        evidence_rows_consistent
        and len(legacy_cache_files) == 9
        and len(current_e_cache) == 9
        and current_e_cache == expected_destination
    )

    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from src.core.config import settings
    from src.services.model_runtime import resolve_huggingface_snapshot

    target_root = repo_root / "models/pyannote"
    community_snapshot = resolve_huggingface_snapshot(
        target_root,
        COMMUNITY_1_MODEL_ID,
        required_files=COMMUNITY_1_REQUIRED_FILES,
    )
    legacy_31_snapshot = resolve_huggingface_snapshot(
        target_root,
        "pyannote/speaker-diarization-3.1",
    )

    manager_source = (
        repo_root / "src/services/transcription/models/pyannote_manager.py"
    ).read_text(encoding="utf-8")
    adapter_source = (
        repo_root / "src/cherry_core/adapters/diarization/pyannote_adapter.py"
    ).read_text(encoding="utf-8")
    requirements_source = (repo_root / "requirements.txt").read_text(
        encoding="utf-8"
    )
    installed = {
        name: _installed_version(name)
        for name in (
            "pyannote.audio",
            "pyannote.core",
            "torch",
            "torchaudio",
            "torchcodec",
            "diart",
        )
    }
    runtime_stack_compatible = bool(
        _version_tuple(installed["pyannote.audio"]) >= (4, 0, 0)
        and _version_tuple(installed["torch"]) >= (2, 8, 0)
        and _version_tuple(installed["torchaudio"]) >= (2, 8, 0)
        and _version_tuple(installed["torchcodec"]) >= (0, 6, 0)
    )
    code_community_1_compatible = bool(
        "use_auth_token" not in manager_source
        and "use_auth_token" not in adapter_source
        and "exclusive_speaker_diarization" in adapter_source
    )

    official = _official_sources(repo_root, no_network)
    source_hashes = _source_hashes(repo_root)
    migration_match = (
        evidence_rows_consistent
        and len(source_rows) == 9
        and len(destination_rows) == 9
        and len(material_rows) == 9
        and sum(int(row.get("Length", "0")) for row in source_rows) == 25179
        and sum(int(row.get("Length", "0")) for row in destination_rows) == 25179
        and material_hashes_match
        and current_e_cache_matches_destination
    )
    checks = {
        "migration_inventory_and_hashes_match": migration_match,
        "current_e_cache_matches_destination": current_e_cache_matches_destination,
        "community_1_target_snapshot_present": community_snapshot is not None,
        "community_1_full_required_tree_present": community_snapshot is not None
        and all((community_snapshot / relative).is_file() for relative in COMMUNITY_1_REQUIRED_FILES),
        "runtime_uses_canonical_model_root": "models/pyannote" in manager_source.replace(
            "\\", "/"
        )
        and "pyannote_cache" not in manager_source
        and "pyannote_cache" not in adapter_source,
        "runtime_model_root_consistent_and_absolute": (
            'MODELS_DIR / "pyannote"' in manager_source
            and 'MODELS_DIR / "pyannote"' in adapter_source
        ),
        "runtime_resolver_requires_full_tree": (
            "required_files=" in manager_source and "required_files=" in adapter_source
        ),
        "community_1_runtime_stack_compatible": runtime_stack_compatible,
        "community_1_code_api_compatible": code_community_1_compatible,
        "pyannote_dependency_declared": "pyannote.audio" in requirements_source.casefold(),
        "torchcodec_dependency_declared": "torchcodec" in requirements_source.casefold(),
        "token_source_consistent": (
            "settings.HF_TOKEN" in manager_source
            and "settings.HF_TOKEN" in adapter_source
            and 'os.getenv("HF_TOKEN")' not in adapter_source
        ),
        "offline_environment_flags_set": os.getenv("HF_HUB_OFFLINE") == "1"
        and os.getenv("TRANSFORMERS_OFFLINE") == "1",
        "network_denied_loader_evidence_present": (
            repo_root
            / "docs/reviews/artifacts/pyannote-community-1-network-denied-loader.json"
        ).is_file(),
    }
    blockers = sorted(name for name, passed in checks.items() if not passed)
    return {
        "schema_version": "rtk-evidence-v1",
        "artifact_type": "pyannote-migration-config-audit",
        "observed_at": _observed_at(generated_at),
        "repo_root": str(repo_root),
        "canonical_workspace": True,
        "scope": "read_only_no_model_download_no_model_activation",
        "migration_verdict": "PASS_NO_ADDITIONAL_LOSS" if migration_match else "BLOCKED",
        "verdict": "BLOCKED" if blockers else "PASS",
        "exit_code": 2 if blockers else 0,
        "command": [
            str(repo_root / "venv/Scripts/python.exe"),
            "-B",
            "scripts/audit_pyannote_migration_config.py",
        ]
        + (["--no-network"] if no_network else []),
        "harness_path": "scripts/audit_pyannote_migration_config.py",
        "harness_sha256": source_hashes["scripts/audit_pyannote_migration_config.py"],
        "source_sha256": source_hashes,
        "migration_evidence": {
            "root": str(MIGRATION_EVIDENCE_ROOT),
            "source_inventory_sha256": _sha256(
                MIGRATION_EVIDENCE_ROOT / "source-inventory.csv"
            ),
            "destination_inventory_sha256": _sha256(
                MIGRATION_EVIDENCE_ROOT / "destination-inventory.csv"
            ),
            "material_hashes_sha256": _sha256(
                MIGRATION_EVIDENCE_ROOT / "material-hashes.csv"
            ),
            "source_model_files": len(source_rows),
            "destination_model_files": len(destination_rows),
            "source_model_bytes": sum(
                int(row.get("Length", "0")) for row in source_rows
            ),
            "destination_model_bytes": sum(
                int(row.get("Length", "0")) for row in destination_rows
            ),
            "material_hash_rows": len(material_rows),
            "material_hashes_match": material_hashes_match,
            "evidence_rows_consistent": evidence_rows_consistent,
            "current_e_cache_matches_destination": current_e_cache_matches_destination,
            "current_e_cache_files": len(legacy_cache_files),
            "current_e_cache_bytes": sum(
                int(row.get("size", 0)) for row in legacy_cache_files
            ),
        },
        "local_artifacts": {
            "target_root": str(target_root),
            "target_files": target_files,
            "legacy_cache_root": str(repo_root / "models/pyannote_cache"),
            "legacy_cache_files": legacy_cache_files,
            "community_1_snapshot": str(community_snapshot)
            if community_snapshot
            else None,
            "legacy_3_1_snapshot": str(legacy_31_snapshot)
            if legacy_31_snapshot
            else None,
            "required_files": list(COMMUNITY_1_REQUIRED_FILES),
        },
        "effective_config": {
            "offline_strict": bool(settings.OFFLINE_STRICT),
            "transcription_engine": str(settings.TRANSCRIPTION_ENGINE),
            "hf_token_configured": bool(getattr(settings, "HF_TOKEN", "")),
            "hf_hub_offline": os.getenv("HF_HUB_OFFLINE"),
            "transformers_offline": os.getenv("TRANSFORMERS_OFFLINE"),
            "token_value_recorded": False,
        },
        "runtime_compatibility": {
            "installed": installed,
            "community_1_stack_compatible": runtime_stack_compatible,
            "community_1_code_api_compatible": code_community_1_compatible,
            "manager_uses_relative_model_root": 'Path("models/pyannote")'
            in manager_source,
            "adapter_uses_models_dir": 'MODELS_DIR / "pyannote"' in adapter_source,
            "runtime_mentions_legacy_cache": "pyannote_cache"
            in (manager_source + adapter_source),
            "manager_requires_full_tree": "required_files=" in manager_source,
            "adapter_requires_full_tree": "required_files=" in adapter_source,
            "uses_legacy_use_auth_token_keyword": "use_auth_token"
            in (manager_source + adapter_source),
            "handles_community_1_output_object": "exclusive_speaker_diarization"
            in adapter_source,
        },
        "official_sources": official,
        "runtime_log": _runtime_log_observation(repo_root),
        "checks": checks,
        "blockers": blockers,
        "limitations": [
            "No gated model file was downloaded or loaded by this audit.",
            "Official metadata does not prove Vietnamese diarization quality.",
            "The live Celery log is mutable and is recorded as an observation, not a release signature.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=CANONICAL_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at")
    parser.add_argument("--no-network", action="store_true")
    args = parser.parse_args()
    try:
        repo_root = _canonical_repo(args.repo)
        output = _validated_output(repo_root, args.output)
        report = build_report(
            repo_root,
            generated_at=args.generated_at,
            no_network=args.no_network,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
