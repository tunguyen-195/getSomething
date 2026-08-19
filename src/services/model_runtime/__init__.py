"""Offline model inventory and integrity verification."""

from .manifest import (
    BackendSpec,
    FileSpec,
    LicenseSpec,
    ManifestValidationError,
    ModelManifest,
    ModelSpec,
    SourceSpec,
    load_manifest,
)
from .store import (
    InventoryRecord,
    ModelStore,
    PreflightReport,
    VerificationIssue,
    VerificationResult,
)
from .gpu_lease import GpuLease, GpuLeaseSnapshot, GpuLeaseTimeout, gpu_lease
from .local_artifacts import resolve_huggingface_snapshot
from .offline_bundle import (
    BundleComponent,
    BundleFile,
    OfflineBundle,
    OfflineBundleValidationError,
    REQUIRED_BENCHMARK_ROLES,
    load_offline_bundle,
    verify_offline_bundle,
)

__all__ = [
    "BackendSpec",
    "BundleComponent",
    "BundleFile",
    "FileSpec",
    "GpuLease",
    "GpuLeaseSnapshot",
    "GpuLeaseTimeout",
    "InventoryRecord",
    "LicenseSpec",
    "ManifestValidationError",
    "ModelManifest",
    "ModelSpec",
    "ModelStore",
    "OfflineBundle",
    "OfflineBundleValidationError",
    "PreflightReport",
    "REQUIRED_BENCHMARK_ROLES",
    "SourceSpec",
    "VerificationIssue",
    "VerificationResult",
    "load_manifest",
    "load_offline_bundle",
    "gpu_lease",
    "resolve_huggingface_snapshot",
    "verify_offline_bundle",
]
