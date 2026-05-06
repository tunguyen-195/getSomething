from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path("docs/model_artifacts.required.json")


@dataclass
class ArtifactVerification:
    ok: bool
    artifact_id: str
    resolved_path: Path | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ModelArtifactError(RuntimeError):
    def __init__(self, reason_code: str, guidance: str = "") -> None:
        self.reason_code = reason_code
        self.guidance = guidance
        message = reason_code if not guidance else f"{reason_code}: {guidance}"
        super().__init__(message)


_HEALTH_VERIFICATION_CACHE: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
DEFAULT_HEALTH_CACHE_TTL_SECONDS = 120.0


def repo_root(root: Path | str | None = None) -> Path:
    return Path(root).resolve() if root is not None else DEFAULT_ROOT.resolve()


def manifest_path(root: Path | str | None = None, manifest: Path | str | None = None) -> Path:
    if manifest is not None:
        path = Path(manifest)
        return path if path.is_absolute() else repo_root(root) / path
    return repo_root(root) / DEFAULT_MANIFEST


def load_manifest(root: Path | str | None = None, manifest: Path | str | None = None) -> dict[str, Any]:
    with manifest_path(root, manifest).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def artifacts_by_id(manifest_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in manifest_data.get("artifacts", [])}


def selected_artifact_ids(manifest_data: dict[str, Any], profile: str, include_optional: bool = False) -> list[str]:
    profile_data = manifest_data.get("profiles", {}).get(profile)
    if not profile_data:
        raise ModelArtifactError("unknown_profile", profile)
    selected = list(profile_data.get("required") or [])
    if include_optional:
        selected.extend(profile_data.get("optional") or [])
    return sorted(set(str(item) for item in selected))


def artifact_with_cache_root(artifact: dict[str, Any], cache_root: str | Path | None) -> dict[str, Any]:
    if cache_root in (None, ""):
        return artifact
    copied = deepcopy(artifact)
    copied["cache_root"] = str(cache_root)
    return copied


def repo_local_name(repo_id: str) -> str:
    return repo_id.replace("/", "--")


def normalize_model_name(value: str) -> str:
    text = (value or "").strip().lower()
    text = text.replace("systran/", "")
    text = text.replace("faster-whisper-", "")
    return "".join(ch for ch in text if ch.isalnum())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest().lower()


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _resolve_root_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _copy_verification(result: ArtifactVerification) -> ArtifactVerification:
    return ArtifactVerification(
        ok=result.ok,
        artifact_id=result.artifact_id,
        resolved_path=result.resolved_path,
        errors=list(result.errors),
        warnings=list(result.warnings),
    )


def provenance_path(root: Path, artifact: dict[str, Any]) -> Path:
    cache_root = _resolve_root_path(root, artifact["cache_root"])
    if artifact.get("layout") == "local_dir":
        return cache_root / repo_local_name(str(artifact["repo_id"])) / "PROVENANCE.json"
    return cache_root / "_sti_artifacts" / str(artifact["id"]) / "PROVENANCE.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _has_required_files(path: Path, artifact: dict[str, Any]) -> bool:
    for item in artifact.get("files", []):
        if item.get("required", True) and not (path / str(item["path"])).is_file():
            return False
    return True


def _candidate_from_provenance(root: Path, artifact: dict[str, Any], failures: list[str], warnings: list[str]) -> Path | None:
    path = provenance_path(root, artifact)
    if not path.exists():
        return None
    payload = _read_json(path)
    if not payload:
        failure = f"invalid_provenance:{artifact['id']}"
        failures.append(failure)
        warnings.append(failure)
        return None
    if payload.get("artifact_id") != artifact.get("id"):
        failure = f"provenance_artifact_mismatch:{artifact['id']}"
        failures.append(failure)
        warnings.append(failure)
        return None
    if payload.get("revision") != artifact.get("revision"):
        failure = f"provenance_revision_mismatch:{artifact['id']}"
        failures.append(failure)
        warnings.append(failure)
        return None
    relative = payload.get("snapshot_relative_path")
    if not relative:
        failure = f"provenance_missing_snapshot:{artifact['id']}"
        failures.append(failure)
        warnings.append(failure)
        return None
    candidate = _resolve_root_path(root, str(relative))
    if not candidate.exists():
        failure = f"provenance_snapshot_missing:{artifact['id']}"
        failures.append(failure)
        warnings.append(failure)
        return None
    return candidate


def _candidate_from_snapshot_markers(root: Path, artifact: dict[str, Any], failures: list[str], warnings: list[str]) -> Path | None:
    cache_root = _resolve_root_path(root, artifact["cache_root"])
    revision = str(artifact["revision"])
    for marker in cache_root.rglob("SNAPSHOT_PATH.txt") if cache_root.exists() else []:
        try:
            text = marker.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if not text:
            continue
        candidate = Path(text)
        if not candidate.exists():
            failure = f"snapshot_marker_stale:{artifact['id']}"
            failures.append(failure)
            warnings.append(failure)
            continue
        if revision not in candidate.parts:
            failure = f"snapshot_marker_revision_mismatch:{artifact['id']}"
            failures.append(failure)
            warnings.append(failure)
            continue
        if _has_required_files(candidate, artifact):
            return candidate
    return None


def _candidate_from_cache(root: Path, artifact: dict[str, Any]) -> Path | None:
    cache_root = _resolve_root_path(root, artifact["cache_root"])
    if not cache_root.exists():
        return None
    revision = str(artifact["revision"])
    layout = artifact.get("layout") or "hf_cache"
    repo_dir = repo_local_name(str(artifact["repo_id"]))
    if layout == "local_dir":
        candidate = cache_root / repo_dir
        return candidate if candidate.exists() else None

    direct = cache_root / f"models--{repo_dir}" / "snapshots" / revision
    if direct.exists():
        return direct
    for candidate in cache_root.rglob(revision):
        if candidate.is_dir() and candidate.parent.name == "snapshots":
            return candidate
    return None


def _candidate_for_health_fingerprint(
    root: Path,
    artifact: dict[str, Any],
    candidate_path: Path | str | None = None,
) -> Path | None:
    candidates: list[Path] = []
    if candidate_path is not None:
        candidates.append(_resolve_root_path(root, candidate_path))

    discovery_failures: list[str] = []
    warnings: list[str] = []
    for candidate in (
        _candidate_from_provenance(root, artifact, discovery_failures, warnings),
        _candidate_from_snapshot_markers(root, artifact, discovery_failures, warnings),
        _candidate_from_cache(root, artifact),
    ):
        if candidate is not None:
            candidates.append(candidate)

    revision = str(artifact.get("revision") or "")
    for candidate in candidates:
        if not candidate.exists():
            continue
        if artifact.get("layout") != "local_dir" and revision and revision not in candidate.parts:
            continue
        return candidate
    return None


def _file_stat_fingerprint(path: Path) -> tuple[Any, ...]:
    if not path.exists():
        return (path.resolve().as_posix(), False, None, None)
    stat = path.stat()
    return (path.resolve().as_posix(), path.is_file(), stat.st_size, stat.st_mtime_ns)


def _declared_files_fingerprint(base_path: Path, artifact: dict[str, Any]) -> tuple[Any, ...]:
    values: list[tuple[Any, ...]] = []
    for item in artifact.get("files") or []:
        rel_path = Path(str(item.get("path") or ""))
        if not str(rel_path):
            continue
        file_path = rel_path if rel_path.is_absolute() else base_path / rel_path
        values.append((rel_path.as_posix(),) + _file_stat_fingerprint(file_path))
    return tuple(values)


def _artifact_health_fingerprint(
    root: Path,
    artifact: dict[str, Any],
    result: ArtifactVerification | None = None,
    candidate_path: Path | str | None = None,
) -> tuple[Any, ...]:
    artifact_id = str(artifact.get("id") or "unknown")
    kind = str(artifact.get("kind") or "")
    base = result.resolved_path if result and result.resolved_path is not None else None

    if kind in {"hf_snapshot", "hf_snapshot_gated"}:
        base = base or _candidate_for_health_fingerprint(root, artifact, candidate_path)
        if base is None:
            cache_root = _resolve_root_path(root, artifact.get("cache_root") or "")
            return ("hf_missing", artifact_id, cache_root.resolve().as_posix(), artifact.get("revision"))
        return ("hf_snapshot", artifact_id, base.resolve().as_posix(), _declared_files_fingerprint(base, artifact))

    if kind in {"file", "file_with_manifest"}:
        base = base or _existing_path(root, artifact)
        if base is None:
            return ("file_missing", artifact_id, artifact.get("path"), tuple(artifact.get("alternate_paths") or []))
        return ("file", artifact_id, _file_stat_fingerprint(base))

    if kind == "directory":
        base = base or _existing_path(root, artifact)
        if base is None:
            return ("directory_missing", artifact_id, artifact.get("path"), tuple(artifact.get("alternate_paths") or []))
        if artifact.get("files"):
            return ("directory", artifact_id, base.resolve().as_posix(), _declared_files_fingerprint(base, artifact))
        return ("directory", artifact_id, _file_stat_fingerprint(base))

    if kind == "file_set":
        declared = []
        for value in artifact.get("paths") or []:
            declared.append(_file_stat_fingerprint(_resolve_root_path(root, value)))
        if artifact.get("files"):
            declared.extend(_declared_files_fingerprint(root, artifact))
        return ("file_set", artifact_id, tuple(declared))

    return ("unsupported", artifact_id, kind)


def _verify_hf_files(root: Path, artifact: dict[str, Any], snapshot: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for item in artifact.get("files", []):
        rel_path = str(item["path"])
        file_path = snapshot / rel_path
        required = bool(item.get("required", True))
        if not file_path.is_file():
            if required:
                errors.append(f"missing_required_file:{artifact['id']}:{rel_path}")
            continue
        expected_size = item.get("size_bytes")
        actual_size = file_path.stat().st_size
        if expected_size is not None and actual_size != int(expected_size):
            errors.append(f"size_mismatch:{artifact['id']}:{rel_path}")
            continue
        expected_lfs_sha = item.get("lfs_sha256")
        if expected_lfs_sha and sha256_file(file_path) != str(expected_lfs_sha).lower():
            errors.append(f"lfs_sha256_mismatch:{artifact['id']}:{rel_path}")
        expected_sha = item.get("sha256")
        if expected_sha and sha256_file(file_path) != str(expected_sha).lower():
            errors.append(f"sha256_mismatch:{artifact['id']}:{rel_path}")
        expected_blob = item.get("hf_blob_id")
        if expected_blob and git_blob_sha1(file_path) != str(expected_blob).lower():
            errors.append(f"hf_blob_id_mismatch:{artifact['id']}:{rel_path}")
    if not artifact.get("files"):
        warnings.append(f"hf_files_not_declared:{artifact['id']}")
    return errors, warnings


def _write_provenance(root: Path, artifact: dict[str, Any], snapshot: Path) -> None:
    path = provenance_path(root, artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "artifact_id": artifact["id"],
        "repo_id": artifact.get("repo_id"),
        "revision": artifact.get("revision"),
        "cache_root": artifact.get("cache_root"),
        "layout": artifact.get("layout") or "hf_cache",
        "snapshot_relative_path": _relative_to_root(snapshot, root),
        "files": [item.get("path") for item in artifact.get("files", [])],
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def verify_hf_artifact(
    artifact: dict[str, Any],
    *,
    root: Path | str | None = None,
    write_provenance: bool = False,
    candidate_path: Path | str | None = None,
) -> ArtifactVerification:
    root_path = repo_root(root)
    artifact_id = str(artifact["id"])
    errors: list[str] = []
    warnings: list[str] = []
    discovery_failures: list[str] = []
    revision = str(artifact.get("revision") or "")
    if not revision or revision == "main":
        return ArtifactVerification(False, artifact_id, errors=[f"unpinned_hf_revision:{artifact_id}"])

    candidates: list[Path] = []
    if candidate_path is not None:
        candidates.append(_resolve_root_path(root_path, candidate_path))

    provenance_candidate = _candidate_from_provenance(root_path, artifact, discovery_failures, warnings)
    if provenance_candidate is not None:
        candidates.append(provenance_candidate)

    marker_candidate = _candidate_from_snapshot_markers(root_path, artifact, discovery_failures, warnings)
    if marker_candidate is not None:
        candidates.append(marker_candidate)

    cache_candidate = _candidate_from_cache(root_path, artifact)
    if cache_candidate is not None:
        candidates.append(cache_candidate)

    seen: set[str] = set()
    candidate_errors: list[str] = []
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if not candidate.exists():
            candidate_errors.append(f"snapshot_missing:{artifact_id}")
            continue
        if artifact.get("layout") != "local_dir" and revision not in candidate.parts:
            candidate_errors.append(f"snapshot_revision_mismatch:{artifact_id}")
            continue
        file_errors, file_warnings = _verify_hf_files(root_path, artifact, candidate)
        warnings.extend(file_warnings)
        if not file_errors:
            if write_provenance:
                _write_provenance(root_path, artifact, candidate)
            return ArtifactVerification(True, artifact_id, candidate, warnings=warnings)
        candidate_errors.extend(file_errors)

    errors.extend(candidate_errors or discovery_failures or [f"hf_snapshot_missing:{artifact_id}"])
    return ArtifactVerification(False, artifact_id, errors=errors, warnings=warnings)


def _existing_path(root: Path, artifact: dict[str, Any]) -> Path | None:
    candidates: list[str] = []
    if artifact.get("path"):
        candidates.append(str(artifact["path"]))
    candidates.extend(str(item) for item in artifact.get("alternate_paths") or [])
    for value in candidates:
        path = _resolve_root_path(root, value)
        if path.exists():
            return path
    return None


def _verify_file_artifact(root: Path, artifact: dict[str, Any]) -> ArtifactVerification:
    artifact_id = str(artifact["id"])
    path = _existing_path(root, artifact)
    if not path or not path.is_file():
        return ArtifactVerification(False, artifact_id, errors=[f"missing_file:{artifact_id}"])
    errors: list[str] = []
    if artifact.get("source_type") == "manual_copy" and (
        artifact.get("size_bytes") is None or not artifact.get("sha256")
    ):
        errors.append(f"artifact_integrity_metadata_missing:{artifact_id}")
        return ArtifactVerification(False, artifact_id, errors=errors)
    if artifact.get("size_bytes") is not None and path.stat().st_size != int(artifact["size_bytes"]):
        errors.append(f"size_mismatch:{artifact_id}")
    if artifact.get("sha256") and sha256_file(path) != str(artifact["sha256"]).lower():
        errors.append(f"sha256_mismatch:{artifact_id}")
    manifest = artifact.get("manifest_path")
    if manifest and not _resolve_root_path(root, manifest).exists():
        errors.append(f"missing_manifest:{artifact_id}")
    return ArtifactVerification(not errors, artifact_id, path if not errors else None, errors=errors)


def _verify_declared_file_items(root: Path, artifact: dict[str, Any], *, base_path: Path | None = None) -> list[str]:
    artifact_id = str(artifact["id"])
    files = artifact.get("files") or []
    if not files:
        return [f"artifact_integrity_metadata_missing:{artifact_id}"]

    errors: list[str] = []
    for item in files:
        rel_path = Path(str(item.get("path") or ""))
        if not str(rel_path):
            errors.append(f"artifact_integrity_metadata_missing:{artifact_id}")
            continue
        file_path = rel_path if rel_path.is_absolute() else ((base_path / rel_path) if base_path else (root / rel_path))
        if item.get("required", True) and not file_path.is_file():
            errors.append(f"missing_required_file:{artifact_id}:{rel_path.as_posix()}")
            continue
        if not file_path.exists():
            continue
        if item.get("size_bytes") is None or not item.get("sha256"):
            errors.append(f"artifact_integrity_metadata_missing:{artifact_id}:{rel_path.as_posix()}")
            continue
        if file_path.stat().st_size != int(item["size_bytes"]):
            errors.append(f"size_mismatch:{artifact_id}:{rel_path.as_posix()}")
            continue
        if sha256_file(file_path) != str(item["sha256"]).lower():
            errors.append(f"sha256_mismatch:{artifact_id}:{rel_path.as_posix()}")
    return errors


def _verify_directory_artifact(root: Path, artifact: dict[str, Any]) -> ArtifactVerification:
    artifact_id = str(artifact["id"])
    path = _existing_path(root, artifact)
    if not path or not path.is_dir():
        return ArtifactVerification(False, artifact_id, errors=[f"missing_directory:{artifact_id}"])
    if artifact.get("source_type") == "manual_copy":
        errors = _verify_declared_file_items(root, artifact, base_path=path)
        return ArtifactVerification(not errors, artifact_id, path if not errors else None, errors=errors)
    return ArtifactVerification(True, artifact_id, path)


def _verify_file_set_artifact(root: Path, artifact: dict[str, Any]) -> ArtifactVerification:
    artifact_id = str(artifact["id"])
    missing = [str(item) for item in artifact.get("paths", []) if not _resolve_root_path(root, item).is_file()]
    if missing:
        return ArtifactVerification(False, artifact_id, errors=[f"missing_file:{value}" for value in missing])
    if artifact.get("source_type") == "manual_copy":
        errors = _verify_declared_file_items(root, artifact)
        return ArtifactVerification(not errors, artifact_id, root if not errors else None, errors=errors)
    return ArtifactVerification(True, artifact_id, root)


def verify_artifact(
    artifact: dict[str, Any],
    *,
    root: Path | str | None = None,
    write_provenance: bool = False,
    candidate_path: Path | str | None = None,
) -> ArtifactVerification:
    kind = artifact.get("kind")
    if kind in {"hf_snapshot", "hf_snapshot_gated"}:
        return verify_hf_artifact(
            artifact,
            root=root,
            write_provenance=write_provenance,
            candidate_path=candidate_path,
        )
    root_path = repo_root(root)
    if kind in {"file", "file_with_manifest"}:
        return _verify_file_artifact(root_path, artifact)
    if kind == "directory":
        return _verify_directory_artifact(root_path, artifact)
    if kind == "file_set":
        return _verify_file_set_artifact(root_path, artifact)
    return ArtifactVerification(False, str(artifact.get("id", "unknown")), errors=[f"unsupported_kind:{kind}"])


def clear_model_artifact_health_cache() -> None:
    _HEALTH_VERIFICATION_CACHE.clear()


def _health_cache_key(
    root: Path,
    artifact: dict[str, Any],
    candidate_path: Path | str | None,
) -> tuple[str, str, str, str, str]:
    candidate_value = "" if candidate_path is None else _resolve_root_path(root, candidate_path).resolve().as_posix()
    return (
        str(artifact.get("id") or "unknown"),
        root.resolve().as_posix(),
        str(artifact.get("cache_root") or ""),
        str(artifact.get("revision") or ""),
        candidate_value,
    )


def verify_artifact_for_health(
    artifact: dict[str, Any],
    *,
    root: Path | str | None = None,
    candidate_path: Path | str | None = None,
    ttl_seconds: float = DEFAULT_HEALTH_CACHE_TTL_SECONDS,
) -> ArtifactVerification:
    root_path = repo_root(root)
    key = _health_cache_key(root_path, artifact, candidate_path)
    now = time.monotonic()
    cached = _HEALTH_VERIFICATION_CACHE.get(key)
    if cached is not None and now - float(cached["created_at"]) <= ttl_seconds:
        fingerprint = _artifact_health_fingerprint(
            root_path,
            artifact,
            cached["result"],
            candidate_path,
        )
        if fingerprint == cached["fingerprint"]:
            return _copy_verification(cached["result"])

    result = verify_artifact(artifact, root=root_path, candidate_path=candidate_path)
    fingerprint = _artifact_health_fingerprint(root_path, artifact, result, candidate_path)
    _HEALTH_VERIFICATION_CACHE[key] = {
        "created_at": now,
        "fingerprint": fingerprint,
        "result": _copy_verification(result),
    }
    return result


def verify_artifact_id(
    artifact_id: str,
    *,
    root: Path | str | None = None,
    manifest: Path | str | None = None,
    write_provenance: bool = False,
    candidate_path: Path | str | None = None,
    cache_root: str | Path | None = None,
) -> ArtifactVerification:
    manifest_data = load_manifest(root, manifest)
    artifact = artifacts_by_id(manifest_data).get(artifact_id)
    if artifact is None:
        return ArtifactVerification(False, artifact_id, errors=[f"missing_manifest_entry:{artifact_id}"])
    artifact = artifact_with_cache_root(artifact, cache_root)
    return verify_artifact(
        artifact,
        root=root,
        write_provenance=write_provenance,
        candidate_path=candidate_path,
    )


def verify_artifact_id_for_health(
    artifact_id: str,
    *,
    root: Path | str | None = None,
    manifest: Path | str | None = None,
    candidate_path: Path | str | None = None,
    cache_root: str | Path | None = None,
    ttl_seconds: float = DEFAULT_HEALTH_CACHE_TTL_SECONDS,
) -> ArtifactVerification:
    manifest_data = load_manifest(root, manifest)
    artifact = artifacts_by_id(manifest_data).get(artifact_id)
    if artifact is None:
        return ArtifactVerification(False, artifact_id, errors=[f"missing_manifest_entry:{artifact_id}"])
    artifact = artifact_with_cache_root(artifact, cache_root)
    return verify_artifact_for_health(
        artifact,
        root=root,
        candidate_path=candidate_path,
        ttl_seconds=ttl_seconds,
    )


def verify_profile(
    profile: str,
    *,
    root: Path | str | None = None,
    manifest: Path | str | None = None,
    include_optional: bool = False,
    write_provenance: bool = False,
) -> list[ArtifactVerification]:
    manifest_data = load_manifest(root, manifest)
    artifacts = artifacts_by_id(manifest_data)
    results: list[ArtifactVerification] = []
    for artifact_id in selected_artifact_ids(manifest_data, profile, include_optional):
        artifact = artifacts.get(artifact_id)
        if artifact is None:
            results.append(ArtifactVerification(False, artifact_id, errors=[f"missing_manifest_entry:{artifact_id}"]))
            continue
        results.append(verify_artifact(artifact, root=root, write_provenance=write_provenance))
    return results


def find_artifact_for_faster_whisper_model(
    model_name: str,
    *,
    root: Path | str | None = None,
    manifest: Path | str | None = None,
) -> dict[str, Any] | None:
    manifest_data = load_manifest(root, manifest)
    target = normalize_model_name(model_name)
    for artifact in manifest_data.get("artifacts", []):
        if artifact.get("source_type") not in {"public_hf", "gated_hf"}:
            continue
        repo_id = str(artifact.get("repo_id") or "")
        if "faster-whisper" not in repo_id.lower():
            continue
        aliases = {
            str(artifact.get("id") or ""),
            repo_id,
            repo_id.split("/")[-1],
            str((artifact.get("runtime_env") or {}).get("WHISPER_MODEL") or ""),
        }
        if target in {normalize_model_name(item) for item in aliases if item}:
            return artifact
    return None


def find_artifact_for_pyannote_model(
    model_id: str,
    *,
    root: Path | str | None = None,
    manifest: Path | str | None = None,
) -> dict[str, Any] | None:
    manifest_data = load_manifest(root, manifest)
    for artifact in manifest_data.get("artifacts", []):
        if artifact.get("source_type") != "gated_hf":
            continue
        if str(artifact.get("repo_id") or "") == model_id:
            return artifact
    return None


def verify_faster_whisper_runtime_health(
    model_name: str,
    *,
    root: Path | str | None = None,
    manifest: Path | str | None = None,
    cache_root: str | Path | None = None,
    ttl_seconds: float = DEFAULT_HEALTH_CACHE_TTL_SECONDS,
) -> ArtifactVerification:
    artifact = find_artifact_for_faster_whisper_model(model_name, root=root, manifest=manifest)
    if artifact is None:
        return ArtifactVerification(
            False,
            normalize_model_name(model_name) or model_name,
            errors=["model_artifact_not_manifested"],
        )
    artifact = artifact_with_cache_root(artifact, cache_root)
    result = verify_artifact_for_health(artifact, root=root, ttl_seconds=ttl_seconds)
    if result.ok:
        return result
    return ArtifactVerification(
        False,
        result.artifact_id,
        errors=["model_cache_missing_or_unverified"],
        warnings=result.errors + result.warnings,
    )


def require_faster_whisper_runtime_ready(
    model_name: str,
    *,
    root: Path | str | None = None,
    manifest: Path | str | None = None,
    cache_root: str | Path | None = None,
) -> Path:
    artifact = find_artifact_for_faster_whisper_model(model_name, root=root, manifest=manifest)
    if artifact is None:
        raise ModelArtifactError(
            "model_artifact_not_manifested",
            "Add a pinned artifact to docs/model_artifacts.required.json before using this model.",
        )
    artifact = artifact_with_cache_root(artifact, cache_root)
    result = verify_artifact(artifact, root=root)
    if not result.ok or result.resolved_path is None:
        raise ModelArtifactError(
            "model_cache_missing_or_unverified",
            "Run python scripts\\precache_lite_models.py --model small.",
        )
    return result.resolved_path


def require_pyannote_runtime_ready(
    model_id: str,
    *,
    root: Path | str | None = None,
    manifest: Path | str | None = None,
    cache_root: str | Path | None = None,
) -> Path:
    artifact = find_artifact_for_pyannote_model(model_id, root=root, manifest=manifest)
    if artifact is None:
        raise ModelArtifactError(
            "model_artifact_not_manifested",
            "Use a Pyannote model declared in docs/model_artifacts.required.json.",
        )
    artifact = artifact_with_cache_root(artifact, cache_root)
    result = verify_artifact(artifact, root=root)
    if not result.ok or result.resolved_path is None:
        raise ModelArtifactError(
            "model_cache_missing_or_unverified",
            "Run python download_pyannote_model.py after accepting the Hugging Face model terms.",
        )
    return result.resolved_path
