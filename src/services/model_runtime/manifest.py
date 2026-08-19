"""Strict parser for versioned, repository-local model manifests."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_FLOATING_REVISIONS = {"head", "latest", "main", "master", "stable", "trunk"}


class ManifestValidationError(ValueError):
    """Raised when a model manifest does not satisfy the v1 contract."""


@dataclass(frozen=True)
class SourceSpec:
    provider: str
    repository: str
    revision: str


@dataclass(frozen=True)
class LicenseSpec:
    spdx: str
    name: str
    url: str


@dataclass(frozen=True)
class BackendSpec:
    engine: str
    format: str
    quantization: str | None


@dataclass(frozen=True)
class FileSpec:
    path: str
    size_bytes: int
    sha256: str
    required: bool


@dataclass(frozen=True)
class ModelSpec:
    id: str
    version: str
    relative_path: str
    tasks: tuple[str, ...]
    profiles: tuple[str, ...]
    artifact_size_bytes: int
    source: SourceSpec
    license: LicenseSpec
    backend: BackendSpec
    files: tuple[FileSpec, ...]


@dataclass(frozen=True)
class ModelManifest:
    schema_version: int
    manifest_version: str
    model: ModelSpec
    manifest_path: Path | None = None


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestValidationError(f"{field} must be an object")
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
        raise ManifestValidationError(f"{field} is missing fields: {', '.join(missing)}")
    if unexpected:
        raise ManifestValidationError(
            f"{field} contains unsupported fields: {', '.join(unexpected)}"
        )


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ManifestValidationError(f"{field} must be a non-negative integer")
    return value


def _identifier(value: Any, field: str) -> str:
    identifier = _string(value, field)
    if not _IDENTIFIER_RE.fullmatch(identifier):
        raise ManifestValidationError(
            f"{field} must use lowercase letters, digits, dot, dash, or underscore"
        )
    return identifier


def _identifier_list(value: Any, field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise ManifestValidationError(f"{field} must be a non-empty array")
    result = tuple(_identifier(item, f"{field}[]") for item in value)
    if len(result) != len(set(result)):
        raise ManifestValidationError(f"{field} must not contain duplicates")
    return result


def _relative_path(value: Any, field: str) -> str:
    raw = _string(value, field)
    if "\\" in raw:
        raise ManifestValidationError(f"{field} must use forward slashes")
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ManifestValidationError(f"{field} must be a normalized relative path")
    if ":" in path.parts[0]:
        raise ManifestValidationError(f"{field} must not contain a drive prefix")
    return path.as_posix()


def _parse_source(value: Any) -> SourceSpec:
    source = _mapping(value, "model.source")
    _check_keys(source, "model.source", {"provider", "repository", "revision"})
    revision = _string(source["revision"], "model.source.revision")
    if revision.lower() in _FLOATING_REVISIONS:
        raise ManifestValidationError("model.source.revision must be immutable, not a floating ref")
    return SourceSpec(
        provider=_identifier(source["provider"], "model.source.provider"),
        repository=_string(source["repository"], "model.source.repository"),
        revision=revision,
    )


def _parse_license(value: Any) -> LicenseSpec:
    license_data = _mapping(value, "model.license")
    _check_keys(license_data, "model.license", {"spdx", "name", "url"})
    return LicenseSpec(
        spdx=_string(license_data["spdx"], "model.license.spdx"),
        name=_string(license_data["name"], "model.license.name"),
        url=_string(license_data["url"], "model.license.url"),
    )


def _parse_backend(value: Any) -> BackendSpec:
    backend = _mapping(value, "model.backend")
    _check_keys(
        backend,
        "model.backend",
        {"engine", "format", "quantization"},
    )
    quantization_value = backend["quantization"]
    if quantization_value is not None:
        quantization_value = _string(quantization_value, "model.backend.quantization")
    return BackendSpec(
        engine=_identifier(backend["engine"], "model.backend.engine"),
        format=_identifier(backend["format"], "model.backend.format"),
        quantization=quantization_value,
    )


def _parse_file(value: Any, index: int) -> FileSpec:
    field = f"model.files[{index}]"
    file_data = _mapping(value, field)
    _check_keys(file_data, field, {"path", "size_bytes", "sha256"}, {"required"})
    sha256 = _string(file_data["sha256"], f"{field}.sha256").lower()
    if not _SHA256_RE.fullmatch(sha256):
        raise ManifestValidationError(f"{field}.sha256 must be a 64-character SHA-256")
    required = file_data.get("required", True)
    if not isinstance(required, bool):
        raise ManifestValidationError(f"{field}.required must be a boolean")
    return FileSpec(
        path=_relative_path(file_data["path"], f"{field}.path"),
        size_bytes=_integer(file_data["size_bytes"], f"{field}.size_bytes"),
        sha256=sha256,
        required=required,
    )


def parse_manifest(data: Mapping[str, Any], manifest_path: Path | None = None) -> ModelManifest:
    """Parse and validate a v1 manifest without accessing model artifacts."""
    root = _mapping(data, "manifest")
    _check_keys(root, "manifest", {"schema_version", "manifest_version", "model"})

    schema_version = _integer(root["schema_version"], "schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ManifestValidationError(
            f"Unsupported schema_version {schema_version}; expected {SCHEMA_VERSION}"
        )
    manifest_version = _string(root["manifest_version"], "manifest_version")
    if not _SEMVER_RE.fullmatch(manifest_version):
        raise ManifestValidationError("manifest_version must use semantic versioning")

    model = _mapping(root["model"], "model")
    _check_keys(
        model,
        "model",
        {
            "id",
            "version",
            "relative_path",
            "tasks",
            "profiles",
            "artifact_size_bytes",
            "source",
            "license",
            "backend",
            "files",
        },
    )
    files_value = model["files"]
    if (
        isinstance(files_value, (str, bytes))
        or not isinstance(files_value, Sequence)
        or not files_value
    ):
        raise ManifestValidationError("model.files must be a non-empty array")
    files = tuple(_parse_file(item, index) for index, item in enumerate(files_value))
    file_paths = [file.path for file in files]
    if len(file_paths) != len(set(file_paths)):
        raise ManifestValidationError("model.files must not contain duplicate paths")

    artifact_size = _integer(model["artifact_size_bytes"], "model.artifact_size_bytes")
    calculated_size = sum(file.size_bytes for file in files)
    if artifact_size != calculated_size:
        raise ManifestValidationError(
            "model.artifact_size_bytes must equal the sum of model.files size_bytes"
        )

    return ModelManifest(
        schema_version=schema_version,
        manifest_version=manifest_version,
        model=ModelSpec(
            id=_identifier(model["id"], "model.id"),
            version=_string(model["version"], "model.version"),
            relative_path=_relative_path(model["relative_path"], "model.relative_path"),
            tasks=_identifier_list(model["tasks"], "model.tasks"),
            profiles=_identifier_list(model["profiles"], "model.profiles"),
            artifact_size_bytes=artifact_size,
            source=_parse_source(model["source"]),
            license=_parse_license(model["license"]),
            backend=_parse_backend(model["backend"]),
            files=files,
        ),
        manifest_path=manifest_path.resolve() if manifest_path is not None else None,
    )


def load_manifest(path: Path) -> ModelManifest:
    """Load a manifest from disk; this function never resolves remote sources."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestValidationError(f"Cannot read manifest {path}: {exc}") from exc
    return parse_manifest(data, manifest_path=path)
