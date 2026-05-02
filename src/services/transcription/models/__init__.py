"""Model manager exports for transcription.

The manager modules import optional heavy ML dependencies, so keep this package
initializer import-safe and resolve managers only when callers request them.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["WhisperManager", "PyannoteManager"]


def __getattr__(name: str) -> Any:
    if name == "WhisperManager":
        return import_module(".whisper_manager", __name__).WhisperManager
    if name == "PyannoteManager":
        return import_module(".pyannote_manager", __name__).PyannoteManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted([*globals(), *__all__])
