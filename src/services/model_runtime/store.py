"""Repository-local model store with deterministic offline preflight checks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Sequence

from .manifest import ManifestValidationError, ModelManifest, load_manifest

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class VerificationIssue:
    code: str
    severity: Severity
    path: str
    message: str


@dataclass(frozen=True)
class VerificationResult:
    model_id: str
    version: str
    model_path: Path
    expected_size_bytes: int
    verified_size_bytes: int
    issues: tuple[VerificationIssue, ...]

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def status(self) -> str:
        return "verified" if self.valid else "invalid"


@dataclass(frozen=True)
class InventoryRecord:
    model_id: str
    version: str
    relative_path: str
    tasks: tuple[str, ...]
    profiles: tuple[str, ...]
    backend: str
    format: str
    quantization: str | None
    expected_size_bytes: int
    observed_size_bytes: int
    status: str


@dataclass(frozen=True)
class PreflightReport:
    results: tuple[VerificationResult, ...]
    manifests_found: int

    @property
    def valid(self) -> bool:
        return self.manifests_found > 0 and all(result.valid for result in self.results)


class ModelStore:
    """Resolve and verify model artifacts contained by a repository model root."""

    def __init__(self, store_root: Path, manifest_dir: Path):
        self.store_root = store_root.resolve()
        self.manifest_dir = manifest_dir.resolve()

    @classmethod
    def from_repository(cls, repo_root: Path | None = None) -> "ModelStore":
        root = (repo_root or Path(__file__).resolve().parents[3]).resolve()
        return cls(store_root=root / "models", manifest_dir=root / "config" / "models")

    def load_manifests(self) -> tuple[ModelManifest, ...]:
        if not self.manifest_dir.exists():
            return ()
        manifests = tuple(
            load_manifest(path)
            for path in self._model_manifest_paths()
        )
        seen: dict[str, Path | None] = {}
        for manifest in manifests:
            model_id = manifest.model.id
            if model_id in seen:
                raise ManifestValidationError(
                    f"Duplicate model id {model_id!r} in {seen[model_id]} and "
                    f"{manifest.manifest_path}"
                )
            seen[model_id] = manifest.manifest_path
        return manifests

    def _model_manifest_paths(self) -> tuple[Path, ...]:
        """Route only model manifests while keeping malformed candidates fail-closed."""

        paths: list[Path] = []
        for path in sorted(self.manifest_dir.rglob("*.manifest.json")):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, json.JSONDecodeError):
                # Let the strict loader produce the canonical validation error.
                paths.append(path)
                continue

            if (
                isinstance(payload, dict)
                and "artifact_id" in payload
                and "manifest_version" not in payload
                and "model" not in payload
            ):
                continue
            paths.append(path)
        return tuple(paths)

    def select(
        self,
        manifests: Sequence[ModelManifest],
        model_ids: Iterable[str] = (),
        tasks: Iterable[str] = (),
        profiles: Iterable[str] = (),
    ) -> tuple[ModelManifest, ...]:
        requested_ids = set(model_ids)
        requested_tasks = set(tasks)
        requested_profiles = set(profiles)
        available_ids = {manifest.model.id for manifest in manifests}
        unknown_ids = sorted(requested_ids - available_ids)
        if unknown_ids:
            raise ManifestValidationError(
                f"Unknown model id(s): {', '.join(unknown_ids)}"
            )
        return tuple(
            manifest
            for manifest in manifests
            if (not requested_ids or manifest.model.id in requested_ids)
            and (not requested_tasks or requested_tasks.intersection(manifest.model.tasks))
            and (not requested_profiles or requested_profiles.intersection(manifest.model.profiles))
        )

    def inventory(
        self,
        manifests: Sequence[ModelManifest] | None = None,
    ) -> tuple[InventoryRecord, ...]:
        records = []
        for manifest in manifests if manifests is not None else self.load_manifests():
            model = manifest.model
            model_path = self._inside(self.store_root, model.relative_path)
            observed_size = 0
            missing_required = False
            invalid_paths = False
            for file_spec in model.files:
                try:
                    file_path = self._inside(model_path, file_spec.path)
                except ManifestValidationError:
                    invalid_paths = True
                    continue
                if file_path.is_file():
                    observed_size += file_path.stat().st_size
                elif file_spec.required:
                    missing_required = True
            if invalid_paths:
                status = "unsafe"
            elif not model_path.is_dir():
                status = "missing"
            elif missing_required:
                status = "incomplete"
            else:
                status = "present_unverified"
            records.append(
                InventoryRecord(
                    model_id=model.id,
                    version=model.version,
                    relative_path=model.relative_path,
                    tasks=model.tasks,
                    profiles=model.profiles,
                    backend=model.backend.engine,
                    format=model.backend.format,
                    quantization=model.backend.quantization,
                    expected_size_bytes=model.artifact_size_bytes,
                    observed_size_bytes=observed_size,
                    status=status,
                )
            )
        return tuple(records)

    def verify(
        self,
        manifest: ModelManifest,
        *,
        verify_checksums: bool = True,
    ) -> VerificationResult:
        model = manifest.model
        issues: list[VerificationIssue] = []
        verified_size = 0
        try:
            model_path = self._inside(self.store_root, model.relative_path)
        except ManifestValidationError as exc:
            return VerificationResult(
                model_id=model.id,
                version=model.version,
                model_path=self.store_root,
                expected_size_bytes=model.artifact_size_bytes,
                verified_size_bytes=0,
                issues=(
                    VerificationIssue(
                        code="unsafe_model_path",
                        severity="error",
                        path=model.relative_path,
                        message=str(exc),
                    ),
                ),
            )

        if not model_path.is_dir():
            issues.append(
                VerificationIssue(
                    code="missing_model_directory",
                    severity="error",
                    path=model.relative_path,
                    message="Model directory does not exist",
                )
            )

        for file_spec in model.files:
            try:
                file_path = self._inside(model_path, file_spec.path)
            except ManifestValidationError as exc:
                issues.append(
                    VerificationIssue(
                        code="unsafe_file_path",
                        severity="error",
                        path=file_spec.path,
                        message=str(exc),
                    )
                )
                continue
            if not file_path.is_file():
                issues.append(
                    VerificationIssue(
                        code="missing_file",
                        severity="error" if file_spec.required else "warning",
                        path=file_spec.path,
                        message=(
                            "Required file is missing"
                            if file_spec.required
                            else "Optional file is missing"
                        ),
                    )
                )
                continue

            actual_size = file_path.stat().st_size
            verified_size += actual_size
            if actual_size != file_spec.size_bytes:
                issues.append(
                    VerificationIssue(
                        code="size_mismatch",
                        severity="error",
                        path=file_spec.path,
                        message=f"Expected {file_spec.size_bytes} bytes, found {actual_size}",
                    )
                )
                continue
            if verify_checksums:
                actual_sha256 = self._sha256(file_path)
                if actual_sha256 != file_spec.sha256:
                    issues.append(
                        VerificationIssue(
                            code="checksum_mismatch",
                            severity="error",
                            path=file_spec.path,
                            message=f"Expected {file_spec.sha256}, found {actual_sha256}",
                        )
                    )

        return VerificationResult(
            model_id=model.id,
            version=model.version,
            model_path=model_path,
            expected_size_bytes=model.artifact_size_bytes,
            verified_size_bytes=verified_size,
            issues=tuple(issues),
        )

    def preflight(
        self,
        manifests: Sequence[ModelManifest] | None = None,
    ) -> PreflightReport:
        selected = tuple(manifests) if manifests is not None else self.load_manifests()
        results = tuple(self.verify(manifest) for manifest in selected)
        return PreflightReport(results=results, manifests_found=len(selected))

    @staticmethod
    def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _inside(root: Path, relative_path: str) -> Path:
        root = root.resolve()
        candidate = (root / Path(*relative_path.split("/"))).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ManifestValidationError(
                f"Resolved path escapes the model store: {relative_path}"
            ) from exc
        return candidate
