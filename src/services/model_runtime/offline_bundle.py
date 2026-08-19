"""Fail-closed verification for benchmark-candidate offline bundles."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .manifest import ManifestValidationError, load_manifest
from .store import ModelStore


PROTOCOL_VERSION = "offline-bundle-verification-v1"
SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_FLOATING_REVISIONS = {"head", "latest", "main", "master", "stable", "trunk"}
_COMPONENT_KINDS = {"file_set", "model_manifest", "runtime_manifest"}
_ROLE_KIND_REQUIREMENTS = {
    "app-source-bundle": "file_set",
    "asr-model": "model_manifest",
    "database-runtime": "runtime_manifest",
    "diarization-model": "model_manifest",
    "ffmpeg-runtime": "runtime_manifest",
    "frontend-package-cache": "file_set",
    "license-bundle": "file_set",
    "llm-model": "model_manifest",
    "llm-runtime": "runtime_manifest",
    "node-runtime": "runtime_manifest",
    "os-prerequisites": "file_set",
    "prompt-schema-bundle": "file_set",
    "python-runtime": "runtime_manifest",
    "python-wheelhouse": "file_set",
    "queue-runtime": "runtime_manifest",
    "startup-profile": "file_set",
}
REQUIRED_BENCHMARK_ROLES = tuple(sorted(_ROLE_KIND_REQUIREMENTS))
_MODEL_ROLE_TASKS = {
    "asr-model": frozenset({"transcription"}),
    "diarization-model": frozenset({"diarization"}),
    "llm-model": frozenset({"analysis", "summary"}),
}
_FILE_SET_REQUIRED_PATHS = {
    "app-source-bundle": frozenset({"config/release/app-source.manifest.json"}),
    "frontend-package-cache": frozenset(
        {"frontend/offline-cache/manifest.json"}
    ),
    "license-bundle": frozenset(
        {"THIRD_PARTY_NOTICES.md", "config/release/third-party-components.json"}
    ),
    "os-prerequisites": frozenset(
        {"config/release/os-prerequisites.manifest.json"}
    ),
    "prompt-schema-bundle": frozenset(
        {"config/release/prompt-schema-bundle.manifest.json"}
    ),
    "python-wheelhouse": frozenset({"wheelhouse/manifest.json"}),
    "startup-profile": frozenset({"config/release/offline-startup-profile.json"}),
}


class OfflineBundleValidationError(ValueError):
    """Raised when an offline bundle manifest is ambiguous or unsafe."""


@dataclass(frozen=True)
class BundleFile:
    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class BundleComponent:
    id: str
    role: str
    kind: str
    subject_id: str | None
    files: tuple[BundleFile, ...]


@dataclass(frozen=True)
class OfflineBundle:
    id: str
    version: str
    state: str
    target_profile: str
    required_roles: tuple[str, ...]
    components: tuple[BundleComponent, ...]
    manifest_path: Path | None = None


def _object_without_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise OfflineBundleValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OfflineBundleValidationError(f"{field} must be an object")
    return value


def _check_keys(
    value: Mapping[str, Any],
    field: str,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    missing = sorted(required - value.keys())
    unexpected = sorted(value.keys() - required - optional)
    if missing:
        raise OfflineBundleValidationError(
            f"{field} is missing fields: {', '.join(missing)}"
        )
    if unexpected:
        raise OfflineBundleValidationError(
            f"{field} contains unsupported fields: {', '.join(unexpected)}"
        )


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineBundleValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _identifier(value: Any, field: str) -> str:
    identifier = _string(value, field)
    if not _IDENTIFIER_RE.fullmatch(identifier):
        raise OfflineBundleValidationError(
            f"{field} must use lowercase letters, digits, dot, dash, or underscore"
        )
    return identifier


def _identifier_list(value: Any, field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise OfflineBundleValidationError(f"{field} must be a non-empty array")
    result = tuple(_identifier(item, f"{field}[]") for item in value)
    if len(result) != len(set(result)):
        raise OfflineBundleValidationError(f"{field} must not contain duplicates")
    return result


def _relative_path(value: Any, field: str) -> str:
    raw = _string(value, field)
    if "\\" in raw:
        raise OfflineBundleValidationError(f"{field} must use forward slashes")
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise OfflineBundleValidationError(
            f"{field} must be a normalized relative path"
        )
    if ":" in path.parts[0]:
        raise OfflineBundleValidationError(f"{field} must not contain a drive prefix")
    return path.as_posix()


def _parse_file(value: Any, field: str) -> BundleFile:
    row = _mapping(value, field)
    _check_keys(row, field, {"path", "size_bytes", "sha256"})
    size = row["size_bytes"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise OfflineBundleValidationError(
            f"{field}.size_bytes must be a non-negative integer"
        )
    digest = _string(row["sha256"], f"{field}.sha256").casefold()
    if not _SHA256_RE.fullmatch(digest):
        raise OfflineBundleValidationError(f"{field}.sha256 must be lowercase SHA-256")
    return BundleFile(
        path=_relative_path(row["path"], f"{field}.path"),
        size_bytes=size,
        sha256=digest,
    )


def _parse_component(value: Any, index: int) -> BundleComponent:
    field = f"bundle.components[{index}]"
    row = _mapping(value, field)
    _check_keys(
        row,
        field,
        {"id", "role", "kind", "files"},
        {"subject_id"},
    )
    kind = _identifier(row["kind"], f"{field}.kind")
    if kind not in _COMPONENT_KINDS:
        raise OfflineBundleValidationError(
            f"{field}.kind must be one of {sorted(_COMPONENT_KINDS)}"
        )
    role = _identifier(row["role"], f"{field}.role")
    expected_kind = _ROLE_KIND_REQUIREMENTS.get(role)
    if expected_kind is None:
        raise OfflineBundleValidationError(f"{field}.role is not supported by v1")
    if kind != expected_kind:
        raise OfflineBundleValidationError(
            f"{field}.kind must be {expected_kind!r} for role {role!r}"
        )
    files_value = row["files"]
    if (
        isinstance(files_value, (str, bytes))
        or not isinstance(files_value, Sequence)
        or not files_value
    ):
        raise OfflineBundleValidationError(f"{field}.files must be a non-empty array")
    files = tuple(
        _parse_file(item, f"{field}.files[{file_index}]")
        for file_index, item in enumerate(files_value)
    )
    paths = [item.path for item in files]
    if len(paths) != len(set(paths)):
        raise OfflineBundleValidationError(f"{field}.files contains duplicate paths")
    subject_id = row.get("subject_id")
    if kind in {"model_manifest", "runtime_manifest"}:
        if len(files) != 1:
            raise OfflineBundleValidationError(
                f"{field} must reference exactly one nested manifest"
            )
        subject_id = _identifier(subject_id, f"{field}.subject_id")
    elif subject_id is not None:
        raise OfflineBundleValidationError(
            f"{field}.subject_id is only valid for nested manifests"
        )
    return BundleComponent(
        id=_identifier(row["id"], f"{field}.id"),
        role=role,
        kind=kind,
        subject_id=subject_id,
        files=files,
    )


def load_offline_bundle(path: Path) -> OfflineBundle:
    """Parse one candidate bundle and reject duplicate or permissive fields."""

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
        )
    except OfflineBundleValidationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OfflineBundleValidationError(f"cannot read offline bundle: {exc}") from exc
    root = _mapping(payload, "root")
    _check_keys(root, "root", {"schema_version", "bundle"})
    if root["schema_version"] != SCHEMA_VERSION:
        raise OfflineBundleValidationError(
            f"schema_version must be {SCHEMA_VERSION}"
        )
    bundle = _mapping(root["bundle"], "bundle")
    _check_keys(
        bundle,
        "bundle",
        {
            "id",
            "version",
            "state",
            "target_profile",
            "required_roles",
            "components",
        },
    )
    version = _string(bundle["version"], "bundle.version")
    if not _SEMVER_RE.fullmatch(version):
        raise OfflineBundleValidationError("bundle.version must use semantic versioning")
    if bundle["state"] != "benchmark_candidate":
        raise OfflineBundleValidationError(
            "v1 verifies benchmark candidates only; production requires signed R9 authority"
        )
    components_value = bundle["components"]
    if isinstance(components_value, (str, bytes)) or not isinstance(
        components_value, Sequence
    ):
        raise OfflineBundleValidationError("bundle.components must be an array")
    components = tuple(
        _parse_component(item, index)
        for index, item in enumerate(components_value)
    )
    component_ids = [component.id for component in components]
    if len(component_ids) != len(set(component_ids)):
        raise OfflineBundleValidationError("bundle.components contains duplicate ids")
    required_roles = _identifier_list(
        bundle["required_roles"], "bundle.required_roles"
    )
    unknown_roles = sorted(set(required_roles) - _ROLE_KIND_REQUIREMENTS.keys())
    if unknown_roles:
        raise OfflineBundleValidationError(
            f"bundle.required_roles contains unsupported roles: {', '.join(unknown_roles)}"
        )
    missing_roles = sorted(set(REQUIRED_BENCHMARK_ROLES) - set(required_roles))
    if missing_roles:
        raise OfflineBundleValidationError(
            "bundle.required_roles cannot weaken benchmark closure; missing: "
            + ", ".join(missing_roles)
        )
    return OfflineBundle(
        id=_identifier(bundle["id"], "bundle.id"),
        version=version,
        state="benchmark_candidate",
        target_profile=_identifier(bundle["target_profile"], "bundle.target_profile"),
        required_roles=required_roles,
        components=components,
        manifest_path=path.resolve(),
    )


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_file_set(root: Path) -> tuple[set[str], list[str]]:
    """Return exact files and reject symlinks/case collisions in a release tree."""

    files: set[str] = set()
    issues: list[str] = []
    folded: dict[str, str] = {}
    if not root.is_dir():
        return files, issues
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            issues.append(f"symlink_not_allowed:{relative}")
            continue
        if not path.is_file():
            continue
        key = relative.casefold()
        previous = folded.get(key)
        if previous is not None and previous != relative:
            issues.append(f"case_collision:{previous}:{relative}")
        folded[key] = relative
        files.add(relative)
    return files, issues


def _inside(root: Path, relative_path: str) -> Path:
    root = root.resolve()
    candidate = (root / Path(*relative_path.split("/"))).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise OfflineBundleValidationError(
            f"resolved path escapes repository: {relative_path}"
        ) from exc
    return candidate


def _verify_declared_files(
    component: BundleComponent,
    repo_root: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    files: list[dict[str, Any]] = []
    issues: list[str] = []
    for spec in component.files:
        try:
            path = _inside(repo_root, spec.path)
        except OfflineBundleValidationError as exc:
            files.append({**asdict(spec), "valid": False})
            issues.append(f"unsafe_path:{spec.path}:{exc}")
            continue
        result: dict[str, Any] = {
            **asdict(spec),
            "resolved_path": str(path),
            "valid": False,
        }
        if not path.is_file():
            result["issue"] = "missing_file"
            issues.append(f"missing_file:{spec.path}")
        else:
            observed_size = path.stat().st_size
            result["observed_size_bytes"] = observed_size
            if observed_size != spec.size_bytes:
                result["issue"] = "size_mismatch"
                issues.append(f"size_mismatch:{spec.path}")
            else:
                observed_hash = _sha256(path)
                result["observed_sha256"] = observed_hash
                if observed_hash != spec.sha256:
                    result["issue"] = "checksum_mismatch"
                    issues.append(f"checksum_mismatch:{spec.path}")
                else:
                    result["valid"] = True
        files.append(result)
    return files, issues


def _load_json_without_duplicates(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
        )
    except OfflineBundleValidationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OfflineBundleValidationError(f"cannot read nested manifest: {exc}") from exc
    return _mapping(payload, "nested manifest")


def _verify_model_manifest(
    component: BundleComponent,
    repo_root: Path,
) -> dict[str, Any]:
    manifest_path = _inside(repo_root, component.files[0].path)
    _load_json_without_duplicates(manifest_path)
    try:
        manifest = load_manifest(manifest_path)
        if manifest.model.id != component.subject_id:
            return {
                "valid": False,
                "issues": [
                    f"subject_id_mismatch:{component.subject_id}:{manifest.model.id}"
                ],
            }
        if "offline" not in manifest.model.profiles:
            return {
                "valid": False,
                "issues": ["model_manifest_missing_offline_profile"],
            }
        required_tasks = _MODEL_ROLE_TASKS[component.role]
        missing_tasks = sorted(required_tasks - set(manifest.model.tasks))
        if missing_tasks:
            return {
                "valid": False,
                "issues": [
                    "model_manifest_role_task_mismatch:"
                    + component.role
                    + ":"
                    + ",".join(missing_tasks)
                ],
            }
        result = ModelStore(
            store_root=repo_root / "models",
            manifest_dir=manifest_path.parent,
        ).verify(manifest)
    except ManifestValidationError as exc:
        return {"valid": False, "issues": [f"model_manifest_invalid:{exc}"]}
    actual_files, closure_issues = _directory_file_set(result.model_path)
    declared_files = {file_spec.path for file_spec in manifest.model.files}
    unexpected_files = sorted(actual_files - declared_files)
    missing_declared_files = sorted(declared_files - actual_files)
    for path in unexpected_files:
        closure_issues.append(f"unexpected_model_file:{path}")
    for path in missing_declared_files:
        closure_issues.append(f"missing_declared_model_file:{path}")
    return {
        "valid": result.valid and not closure_issues,
        "model_id": result.model_id,
        "version": result.version,
        "model_path": str(result.model_path),
        "expected_size_bytes": result.expected_size_bytes,
        "verified_size_bytes": result.verified_size_bytes,
        "issues": [asdict(issue) for issue in result.issues] + closure_issues,
    }


def _runtime_path(value: Any, field: str) -> str:
    try:
        return _relative_path(value, field)
    except OfflineBundleValidationError as exc:
        raise OfflineBundleValidationError(f"runtime manifest {exc}") from exc


def _verify_runtime_manifest(
    component: BundleComponent,
    repo_root: Path,
) -> dict[str, Any]:
    manifest_path = _inside(repo_root, component.files[0].path)
    try:
        payload = _load_json_without_duplicates(manifest_path)
        _check_keys(payload, "runtime root", {"schema_version", "manifest_version", "runtime"})
        if payload["schema_version"] != 1:
            raise OfflineBundleValidationError("runtime schema_version must be 1")
        runtime = _mapping(payload["runtime"], "runtime")
        _check_keys(
            runtime,
            "runtime",
            {
                "id",
                "version",
                "commit",
                "relative_path",
                "platform",
                "architecture",
                "accelerator",
                "source",
                "license",
                "probe",
                "files",
            },
        )
        runtime_id = _identifier(runtime["id"], "runtime.id")
        if runtime_id != component.subject_id:
            return {
                "valid": False,
                "issues": [
                    f"subject_id_mismatch:{component.subject_id}:{runtime_id}"
                ],
            }
        commit = _string(runtime["commit"], "runtime.commit")
        if commit.casefold() in _FLOATING_REVISIONS or not re.fullmatch(
            r"[0-9a-f]{40}", commit.casefold()
        ):
            raise OfflineBundleValidationError(
                "runtime.commit must be a full lowercase 40-hex Git commit"
            )
        source = _mapping(runtime["source"], "runtime.source")
        license_data = _mapping(runtime["license"], "runtime.license")
        for field_name in ("provider", "repository", "release_url"):
            _string(source.get(field_name), f"runtime.source.{field_name}")
        for field_name in ("spdx", "name", "url"):
            _string(license_data.get(field_name), f"runtime.license.{field_name}")
        runtime_root = _inside(
            repo_root,
            _runtime_path(runtime["relative_path"], "runtime.relative_path"),
        )
        rows = runtime["files"]
        if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence) or not rows:
            raise OfflineBundleValidationError("runtime.files must be a non-empty array")
        seen: set[str] = set()
        issues: list[dict[str, Any]] = []
        verified_count = 0
        for index, value in enumerate(rows):
            row = _mapping(value, f"runtime.files[{index}]")
            _check_keys(
                row,
                f"runtime.files[{index}]",
                {"path", "size_bytes", "sha256"},
            )
            spec = _parse_file(row, f"runtime.files[{index}]")
            if spec.path in seen:
                raise OfflineBundleValidationError(
                    f"runtime.files contains duplicate path: {spec.path}"
                )
            seen.add(spec.path)
            path = _inside(runtime_root, spec.path)
            if not path.is_file():
                issues.append({"code": "missing_file", "path": spec.path})
                continue
            observed_size = path.stat().st_size
            if observed_size != spec.size_bytes:
                issues.append(
                    {
                        "code": "size_mismatch",
                        "path": spec.path,
                        "expected": spec.size_bytes,
                        "observed": observed_size,
                    }
                )
                continue
            observed_hash = _sha256(path)
            if observed_hash != spec.sha256:
                issues.append(
                    {
                        "code": "checksum_mismatch",
                        "path": spec.path,
                        "expected": spec.sha256,
                        "observed": observed_hash,
                    }
                )
                continue
            verified_count += 1
        actual_files, closure_issues = _directory_file_set(runtime_root)
        declared_files = set(seen)
        for path in sorted(actual_files - declared_files):
            closure_issues.append(f"unexpected_runtime_file:{path}")
        for path in sorted(declared_files - actual_files):
            closure_issues.append(f"missing_declared_runtime_file:{path}")
        return {
            "valid": not issues and not closure_issues,
            "runtime_id": runtime_id,
            "version": runtime["version"],
            "commit": commit,
            "runtime_root": str(runtime_root),
            "verified_file_count": verified_count,
            "issues": issues + closure_issues,
        }
    except OfflineBundleValidationError as exc:
        return {"valid": False, "issues": [f"runtime_manifest_invalid:{exc}"]}


def verify_offline_bundle(bundle: OfflineBundle, repo_root: Path) -> dict[str, Any]:
    """Verify declared bytes and nested model/runtime manifests without network I/O."""

    root = repo_root.resolve()
    required_role_set = set(REQUIRED_BENCHMARK_ROLES)
    role_contract_issues: list[str] = []
    if set(bundle.required_roles) != required_role_set:
        role_contract_issues.append("required_roles_do_not_match_locked_v1_contract")
    component_reports: list[dict[str, Any]] = []
    satisfied_roles: set[str] = set()
    for component in bundle.components:
        files, file_issues = _verify_declared_files(component, root)
        nested: dict[str, Any] | None = None
        if not file_issues and component.kind == "file_set":
            required_paths = _FILE_SET_REQUIRED_PATHS.get(component.role, frozenset())
            missing_paths = sorted(
                required_paths - {file_spec.path for file_spec in component.files}
            )
            if missing_paths:
                file_issues.extend(
                    f"role_required_file_missing:{path}" for path in missing_paths
                )
        if not file_issues and component.kind == "model_manifest":
            nested = _verify_model_manifest(component, root)
        elif not file_issues and component.kind == "runtime_manifest":
            nested = _verify_runtime_manifest(component, root)
        component_valid = not file_issues and (nested is None or nested.get("valid") is True)
        if component_valid:
            satisfied_roles.add(component.role)
        component_reports.append(
            {
                "id": component.id,
                "role": component.role,
                "kind": component.kind,
                "subject_id": component.subject_id,
                "valid": component_valid,
                "files": files,
                "file_issues": file_issues,
                "nested_verification": nested,
            }
        )
    missing_roles = sorted(required_role_set - satisfied_roles)
    valid = not role_contract_issues and not missing_roles and all(
        report["valid"] for report in component_reports
    )
    manifest_hash = (
        _sha256(bundle.manifest_path)
        if bundle.manifest_path is not None and bundle.manifest_path.is_file()
        else None
    )
    return {
        "protocol_version": PROTOCOL_VERSION,
        "offline": True,
        "bundle_id": bundle.id,
        "bundle_version": bundle.version,
        "bundle_state": bundle.state,
        "target_profile": bundle.target_profile,
        "bundle_manifest_sha256": manifest_hash,
        "required_roles": list(REQUIRED_BENCHMARK_ROLES),
        "role_contract_issues": role_contract_issues,
        "satisfied_roles": sorted(satisfied_roles),
        "missing_roles": missing_roles,
        "components": component_reports,
        "candidate_complete": valid,
        "release_ready": False,
        "status": "PASS_CANDIDATE_COMPLETE" if valid else "BLOCKED",
        "valid": valid,
        "limitations": [
            "Production release requires the signed R9 release manifest and authority.",
            "A complete candidate bundle does not establish model quality.",
        ],
    }


__all__ = [
    "BundleComponent",
    "BundleFile",
    "OfflineBundle",
    "OfflineBundleValidationError",
    "PROTOCOL_VERSION",
    "REQUIRED_BENCHMARK_ROLES",
    "load_offline_bundle",
    "verify_offline_bundle",
]
