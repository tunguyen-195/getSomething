"""Transcription service exports.

Keep package import lightweight so utility submodules can be imported without
loading ASR backends.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["transcribe_audio"]


def __getattr__(name: str) -> Any:
    if name == "transcribe_audio":
        return import_module(".transcribe_service", __name__).transcribe_audio
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted([*globals(), *__all__])
