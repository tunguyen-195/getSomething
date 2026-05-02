"""Cherry Core ASR adapter exports.

Adapters are imported lazily so importing this package does not load Whisper,
Transformers, Torchaudio, or their native dependency stack.
"""

__all__ = ["WhisperV2Adapter", "PhoWhisperAdapter", "HallucinationFilter"]


def __getattr__(name):
    if name == "WhisperV2Adapter":
        from .whisperv2_adapter import WhisperV2Adapter
        return WhisperV2Adapter
    if name == "PhoWhisperAdapter":
        from .phowhisper_adapter import PhoWhisperAdapter
        return PhoWhisperAdapter
    if name == "HallucinationFilter":
        from .hallucination_filter import HallucinationFilter
        return HallucinationFilter
    raise AttributeError(name)
