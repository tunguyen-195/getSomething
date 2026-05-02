"""Cherry Core diarization adapter exports.

Exports are lazy to keep package import independent from optional model stacks.
"""

__all__ = ["PyannoteAdapter"]


def __getattr__(name):
    if name == "PyannoteAdapter":
        from .pyannote_adapter import PyannoteAdapter
        return PyannoteAdapter
    raise AttributeError(name)
