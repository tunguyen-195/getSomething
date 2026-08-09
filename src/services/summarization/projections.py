"""Fail-closed compatibility shim for the retired S1 visualization path."""

from __future__ import annotations

from src.services.visualization_service import generate_visualization


def project_visualization(value: object) -> dict[str, object]:
    """Accept only a typed released InvestigationRun; raw mappings are rejected."""

    return generate_visualization(value)  # type: ignore[arg-type]


__all__ = ["project_visualization"]
