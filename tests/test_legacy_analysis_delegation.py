from types import SimpleNamespace

import numpy as np

from src.speech_to_text.transcriber import AudioSegment, OllamaProcessor, Transcriber


def test_legacy_analysis_delegates_to_v13_service(monkeypatch):
    captured = {}
    expected = {
        "analysis_status": "success",
        "analysis_text": "Phân tích trực tiếp.",
    }

    def analyze(transcript, **kwargs):
        captured["transcript"] = transcript
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(
        "src.services.summarization.context_service.analyze_conversation_context",
        analyze,
    )

    result = OllamaProcessor(model_name="llama3.2:3b").analyze_context(
        "Nội dung nguồn."
    )

    assert result is expected
    assert captured == {
        "transcript": "Nội dung nguồn.",
        "model_name": "llama3.2:3b",
    }


def test_legacy_analysis_defaults_to_production_auto_selection(monkeypatch):
    captured = {}

    def analyze(_transcript, **kwargs):
        captured.update(kwargs)
        return {"analysis_status": "success", "analysis_text": "Kết quả."}

    monkeypatch.setattr(
        "src.services.summarization.context_service.analyze_conversation_context",
        analyze,
    )

    OllamaProcessor().analyze_context("Nội dung nguồn.")

    assert captured["model_name"] is None


def test_legacy_visualization_reuses_analysis_without_second_generation(monkeypatch):
    processor = OllamaProcessor(model_name="llama3.2:3b")
    calls = []

    def analyze(text):
        calls.append(text)
        return {
            "analysis_status": "success",
            "analysis_text": "Nội dung phân tích.",
            "events": [],
            "entities": [],
            "relationships": [],
            "actions": [],
        }

    monkeypatch.setattr(processor, "analyze_context", analyze)

    result = processor.visualize_context("Nội dung nguồn.")

    assert calls == ["Nội dung nguồn."]
    assert result == {
        "analysis_status": "success",
        "analysis_text": "Nội dung phân tích.",
        "timeline": [],
        "nodes": [],
        "edges": [],
        "actions": [],
    }


def test_legacy_transcribe_preserves_v13_analysis_payload_identity():
    expected = {
        "analysis_status": "success",
        "analysis_text": "Phân tích trực tiếp, không chèn schema cũ.",
    }
    transcriber = Transcriber.__new__(Transcriber)
    transcriber.device = "cpu"
    transcriber.batch_size = 1
    transcriber.audio_processor = SimpleNamespace(enhance_speech_llase=lambda audio: audio)
    transcriber.llm_processor = SimpleNamespace(
        analyze_context=lambda _text: expected,
    )
    transcriber._load_audio = lambda _path: (
        np.array([0.1, -0.1] * 16000, dtype=np.float32),
        16000,
    )
    transcriber._segment_audio = lambda audio, _sr: [
        AudioSegment(audio, 0.0, 2.0),
    ]
    transcriber._process_segment = lambda _segment: (
        "Nội dung hội thoại đủ dài để kiểm tra Analysis V13."
    )
    transcriber._post_process_text = lambda text: text
    transcriber._generate_caption = lambda _audio, _sr: ""
    transcriber._is_noisy = lambda _audio: False

    result = transcriber.transcribe("unused.wav")

    assert result["analysis"] is expected
    assert set(result["analysis"]) == {"analysis_status", "analysis_text"}


def test_legacy_diarization_preserves_v13_analysis_payload_identity():
    expected = {
        "analysis_status": "success",
        "analysis_text": "Phân tích trực tiếp, không parse JSON.",
    }
    transcriber = Transcriber.__new__(Transcriber)
    transcriber.vad_adapter = None
    transcriber.beam_size = 1
    transcriber.model = SimpleNamespace(
        transcribe=lambda *_args, **_kwargs: (
            [SimpleNamespace(start=0.0, end=2.0, text="Nội dung nguồn.")],
            SimpleNamespace(duration=2.0),
        )
    )
    transcriber.llm_processor = SimpleNamespace(
        analyze_context=lambda _text: expected,
    )

    result = transcriber.transcribe_with_diarization(
        "unused.wav",
        enable_diarization=False,
    )

    assert result["analysis"] is expected
    assert set(result["analysis"]) == {"analysis_status", "analysis_text"}
