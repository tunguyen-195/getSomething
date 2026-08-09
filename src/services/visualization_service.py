"""Compatibility entrypoint for release-authorized visualization projection."""

from __future__ import annotations

from src.services.investigation.run_contracts import InvestigationRun
from src.services.visualization import (
    InvestigationVisualization,
    VisualizationProjectionError,
    project_released_investigation_run,
)


def generate_visualization(
    released_run: InvestigationRun,
    visualization_type: str = "all",
) -> dict[str, object]:
    """Return one complete deterministic artifact; legacy task IDs fail closed."""

    if visualization_type != "all":
        raise VisualizationProjectionError(
            "VISUALIZATION_TYPE_UNSUPPORTED",
            "partial legacy visualization types are disabled for released runs",
        )
    artifact: InvestigationVisualization = project_released_investigation_run(
        released_run
    )
    return artifact.model_dump(mode="json", exclude_none=True)


__all__ = [
    "InvestigationVisualization",
    "VisualizationProjectionError",
    "generate_visualization",
    "project_released_investigation_run",
]
