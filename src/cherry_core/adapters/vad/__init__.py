"""Cherry Core VAD adapter exports."""

__all__ = ["SileroVADAdapter"]


def __getattr__(name):
    if name == "SileroVADAdapter":
        from .silero_adapter import SileroVADAdapter
        return SileroVADAdapter
    raise AttributeError(name)
