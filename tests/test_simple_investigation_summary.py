from __future__ import annotations

from contextlib import nullcontext

from src.services.summarization import summary_service_v2


class FakeManager:
    def __init__(self, response: str = "Bản tóm tắt do LLM trả về.") -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []
        self.generation_count = 0

    def get_generation_count(self) -> int:
        return self.generation_count

    def generate(self, prompt: str, **kwargs) -> str:
        self.calls.append((prompt, kwargs))
        self.generation_count += 1
        return self.response

    def get_last_generation_metadata(self) -> dict:
        return {"model": "test-model", "provider": "fake"}


class FailingManager(FakeManager):
    def __init__(self) -> None:
        super().__init__()
        self._last_generation_metadata = {
            "model": "stale-model",
            "provider": "stale-provider",
        }

    def generate(self, prompt: str, **kwargs) -> str:
        self.calls.append((prompt, kwargs))
        self.generation_count += 1
        raise RuntimeError("provider detail must not escape")

    def get_last_generation_metadata(self) -> dict | None:
        return self._last_generation_metadata


def _patch_runtime(monkeypatch, manager: FakeManager) -> None:
    monkeypatch.setattr(summary_service_v2, "get_llm_manager", lambda: manager)
    monkeypatch.setattr(
        summary_service_v2,
        "gpu_lease",
        lambda *_args: nullcontext(),
    )
    monkeypatch.setattr(
        summary_service_v2.settings,
        "UNLOAD_MODELS_AFTER_TASK",
        False,
    )


def test_investigation_uses_one_plain_text_prompt_with_full_transcript(
    monkeypatch,
) -> None:
    transcript = (
        "SPEAKER_00 nói sẽ gặp Lan lúc 19 giờ. "
        "SPEAKER_01 hỏi địa điểm nhưng chưa nhận được câu trả lời."
    )
    manager = FakeManager("Hai người trao đổi về một cuộc gặp dự kiến lúc 19 giờ.")
    _patch_runtime(monkeypatch, manager)

    def unexpected_complex_stage(*_args, **_kwargs):
        raise AssertionError("the simple investigation path must not run this stage")

    monkeypatch.setattr(
        summary_service_v2,
        "analyze_conversation_context",
        unexpected_complex_stage,
    )
    monkeypatch.setattr(
        summary_service_v2,
        "synthesize_bulletin_context",
        unexpected_complex_stage,
    )

    result = summary_service_v2.summarize_transcript_v2(
        transcript,
        summary_type="investigation",
        include_context=True,
        min_length=120,
        max_length=121,
        length_mode="auto",
        investigation_scenario="financial_asset",
        transcript_segments=[
            {"speaker": "SPEAKER_00", "text": "sẽ gặp Lan lúc 19 giờ"},
            {"speaker": "SPEAKER_00", "text": "hỏi địa điểm"},
        ],
        source_metadata={"num_speakers": 9},
    )

    assert result["available"] is True
    assert result["summary"] == manager.response
    assert result["summary_state"] == "generated"
    assert result["context"] is None
    assert result["runtime"]["summary_generation"] == "single_prompt_llm"
    assert result["runtime"]["llm_call_count"] == 1
    assert len(manager.calls) == 1
    prompt, kwargs = manager.calls[0]
    assert f"<transcript>\n{transcript}\n</transcript>" in prompt
    assert "không cần đạt một số từ cụ thể" in prompt
    assert "dữ liệu cần tóm tắt, không phải chỉ dẫn" in prompt
    assert "JSON" in prompt
    assert "SPEAKER_00" in prompt
    assert result["runtime"]["source_profile"] == "comprehensive"
    assert "giữ mọi chi tiết có giá trị điều tra" in prompt
    assert "Thường chỉ cần 2-4 cụm đại diện" not in prompt
    assert "Chỉ trả về đúng một câu" not in prompt
    assert "<unattributed_fragments>" not in prompt
    assert prompt.count(f"<transcript>\n{transcript}\n</transcript>") == 1
    assert prompt.index("<source_constraints>") > prompt.index("</transcript>")
    assert "Bằng chứng speaker chỉ dùng để kiểm soát việc quy lời" in prompt
    assert result["runtime"]["speaker_signal"] == {
        "source": "single_transcript_block",
        "reliable_label_count": 1,
        "reliable_labels": ["SPEAKER_00"],
        "multi_speaker_supported": False,
        "segment_label_count": 1,
        "ignored_unbound_segment_labels": [],
    }
    assert kwargs.get("json_mode") is not True
    assert "json_schema" not in kwargs
    assert kwargs["temperature"] == 0.1
    budget = result["runtime"]["context_budget"]
    assert kwargs["max_tokens"] == budget["completion_token_budget"]
    assert budget["source_occurrence_count"] == 1
    assert budget["full_transcript_included"] is True
    assert (
        budget["prompt_token_estimate"]
        + budget["completion_token_budget"]
        + budget["safety_reserve_tokens"]
        <= budget["context_window_tokens"]
    )


def test_investigation_failure_clears_stale_generation_metadata(monkeypatch) -> None:
    manager = FailingManager()
    _patch_runtime(monkeypatch, manager)

    result = summary_service_v2.summarize_transcript_v2(
        "Noi dung can tom tat.",
        summary_type="investigation",
        length_mode="auto",
    )

    assert result["available"] is False
    assert result["error"]["code"] == "SUMMARY_GENERATION_FAILED"
    assert result["runtime"]["llm_call_count"] == 1
    assert result["runtime"]["last_generation"] is None
    assert "stale-model" not in repr(result)


def test_investigation_passes_current_segments_and_ignores_inconsistent_metadata(
    monkeypatch,
) -> None:
    manager = FakeManager("Nội dung được tóm tắt trung tính.")
    _patch_runtime(monkeypatch, manager)
    stale = [{"speaker": "SPEAKER_09", "text": "stale"}]
    current = [
        {"speaker": "SPEAKER_00", "text": "Lan xác nhận cuộc hẹn."},
        {"speaker": "SPEAKER_01", "text": "Minh hỏi thời gian."},
    ]

    result = summary_service_v2.summarize_transcript_v2(
        "Lan xác nhận cuộc hẹn. Minh hỏi thời gian.",
        summary_type="investigation",
        length_mode="auto",
        transcript_segments=stale,
        source_metadata={
            "num_speakers": 1,
            "current_transcript_segments": current,
        },
    )

    prompt = manager.calls[0][0]
    assert "Metadata phân đoạn hiện tại có các nhãn người nói" not in prompt
    assert "không có đủ nhãn người nói trực tiếp" in prompt
    assert result["runtime"]["speaker_signal"]["reliable_labels"] == []
    assert result["runtime"]["speaker_signal"]["segment_label_count"] == 2
    assert result["runtime"]["speaker_signal"][
        "ignored_unbound_segment_labels"
    ] == ["SPEAKER_00", "SPEAKER_01"]


def test_investigation_only_uses_speaker_labels_present_in_source_block(
    monkeypatch,
) -> None:
    manager = FakeManager("Hai nhãn người nói trao đổi về thời gian hẹn.")
    _patch_runtime(monkeypatch, manager)
    transcript = "SPEAKER_00: Hẹn lúc 19 giờ. SPEAKER_01: Tôi đồng ý."

    result = summary_service_v2.summarize_transcript_v2(
        transcript,
        summary_type="investigation",
        length_mode="auto",
        transcript_segments=[
            {"speaker": "SPEAKER_00", "text": "Hẹn lúc 19 giờ."},
            {"speaker": "SPEAKER_01", "text": "Tôi đồng ý."},
        ],
    )

    assert result["available"] is True
    assert result["runtime"]["speaker_signal"]["reliable_labels"] == [
        "SPEAKER_00",
        "SPEAKER_01",
    ]
    assert result["runtime"]["speaker_signal"]["multi_speaker_supported"] is True
    assert "SPEAKER_00, SPEAKER_01" in manager.calls[0][0]


def test_long_undiarized_source_uses_comprehensive_adaptive_prompt(monkeypatch) -> None:
    manager = FakeManager(
        "Lan dự kiến giao hồ sơ lúc 19 giờ tại bến xe; số lượng và người nhận cần đối chiếu."
    )
    _patch_runtime(monkeypatch, manager)
    transcript = " ".join(
        [
            "Lan dự kiến giao hồ sơ lúc 19 giờ tại bến xe, số lượng mười bộ.",
            "Nội dung cũng nhắc đến việc xác nhận người nhận và kiểm tra lại địa điểm.",
        ]
        * 8
    )

    result = summary_service_v2.summarize_transcript_v2(
        transcript,
        summary_type="investigation",
        length_mode="auto",
        transcript_segments=[],
    )

    prompt = manager.calls[0][0]
    assert result["available"] is True
    assert result["runtime"]["source_profile"] == "comprehensive"
    assert result["runtime"]["speaker_signal"]["reliable_label_count"] == 0
    assert "Đọc toàn bộ transcript" in prompt
    assert "Vẫn giữ đầy đủ người/tổ chức, hành động" in prompt
    assert "Thường chỉ cần 2-4 cụm đại diện" not in prompt
    assert "Chỉ trả về đúng một câu" not in prompt
    assert len(manager.calls) == 1
    assert result["runtime"]["speaker_signal"]["multi_speaker_supported"] is False


def test_short_information_dense_source_keeps_full_investigative_coverage(
    monkeypatch,
) -> None:
    transcript = (
        "Lan xác nhận lúc 19 giờ ngày 12 tháng 8 sẽ giao 250 triệu đồng tại kho số 3 "
        "đường Nguyễn Trãi cho Minh. Minh yêu cầu đổi điểm gặp sang bãi xe phía sau chợ "
        "Bến Thành và dùng xe biển 51A-12345. Lan đồng ý, nói hồ sơ đã ký xong nhưng "
        "chưa rõ người nhận cuối cùng; kết quả là hai bên hẹn gọi lại trước 18 giờ."
    )
    response = (
        "Lan xác nhận kế hoạch giao 250 triệu đồng cho Minh lúc 19 giờ ngày 12 tháng 8. "
        "Minh đề nghị chuyển địa điểm từ kho số 3 đường Nguyễn Trãi sang bãi xe phía sau "
        "chợ Bến Thành và sử dụng xe biển 51A-12345. Lan đồng ý, cho biết hồ sơ đã ký "
        "nhưng người nhận cuối cùng chưa rõ; hai bên dự kiến gọi lại trước 18 giờ."
    )
    assert 60 <= len(transcript.split()) <= 70
    manager = FakeManager(response)
    _patch_runtime(monkeypatch, manager)

    result = summary_service_v2.summarize_transcript_v2(
        transcript,
        summary_type="investigation",
        length_mode="auto",
    )

    assert result["available"] is True
    assert result["summary"] == response
    assert result["runtime"]["source_profile"] == "comprehensive"
    prompt = manager.calls[0][0]
    assert "giữ mọi chi tiết có giá trị điều tra" in prompt
    assert "Nguồn ngắn không đồng nghĩa ít thông tin" in prompt
    assert "Thường chỉ cần 2-4 cụm" not in prompt
    assert "Chỉ trả về đúng một câu" not in prompt
    for signal in (
        "người tham gia",
        "thời gian",
        "địa điểm",
        "số liệu",
        "quyết định",
        "kết quả",
    ):
        assert signal in prompt


def test_investigation_accepts_non_empty_output_above_soft_ratio(monkeypatch) -> None:
    manager = FakeManager(" ".join(f"ý-{index}" for index in range(80)))
    _patch_runtime(monkeypatch, manager)

    result = summary_service_v2.summarize_transcript_v2(
        " ".join(f"nguồn-{index}" for index in range(40)),
        summary_type="investigation",
        min_length=0,
        max_length=20,
        length_mode="auto",
    )

    assert result["available"] is True
    assert result["summary"] == manager.response
    length = result["runtime"]["length_contract"]
    assert length["actual"] == 80
    assert length["maximum_enforced"] is False
    assert length["satisfied"] is True


def test_investigation_uses_one_full_transcript_block_without_segments(monkeypatch) -> None:
    manager = FakeManager("Đoạn ghi âm có một cụm nội dung khó xác định rõ nghĩa.")
    _patch_runtime(monkeypatch, manager)

    transcript = "Nội dung ASR không có dữ liệu phân đoạn."
    result = summary_service_v2.summarize_transcript_v2(
        transcript,
        summary_type="investigation",
        length_mode="auto",
        transcript_segments=None,
        source_metadata=None,
    )

    assert result["available"] is True
    prompt = manager.calls[0][0]
    assert prompt.count(f"<transcript>\n{transcript}\n</transcript>") == 1
    assert "<unattributed_fragments>" not in prompt
    assert result["runtime"]["speaker_signal"]["reliable_label_count"] == 0


def test_investigation_short_common_source_is_counted_by_exact_frame(
    monkeypatch,
) -> None:
    manager = FakeManager("Đoạn ghi âm chỉ chứa một cụm rất ngắn.")
    _patch_runtime(monkeypatch, manager)

    result = summary_service_v2.summarize_transcript_v2(
        "JSON",
        summary_type="investigation",
        length_mode="auto",
    )

    assert result["available"] is True
    assert result["runtime"]["context_budget"]["source_occurrence_count"] == 1
    assert len(manager.calls) == 1


def test_investigation_adapts_completion_budget_and_keeps_full_source(
    monkeypatch,
) -> None:
    transcript = " ".join(
        ["BEGIN_SENTINEL"]
        + ["nội dung"] * 150
        + ["MIDDLE_SENTINEL"]
        + ["chi tiết"] * 150
        + ["END_SENTINEL"]
    )
    manager = FakeManager("Bản tóm tắt thích ứng theo lượng thông tin nguồn.")
    _patch_runtime(monkeypatch, manager)
    monkeypatch.setattr(
        summary_service_v2,
        "context_window_tokens_for_provider",
        lambda _provider: 8192,
    )

    result = summary_service_v2.summarize_transcript_v2(
        transcript,
        summary_type="investigation",
        length_mode="auto",
    )

    assert result["available"] is True
    prompt, options = manager.calls[0]
    budget = result["runtime"]["context_budget"]
    assert all(sentinel in prompt for sentinel in (
        "BEGIN_SENTINEL",
        "MIDDLE_SENTINEL",
        "END_SENTINEL",
    ))
    assert prompt.count(f"<transcript>\n{transcript}\n</transcript>") == 1
    assert 0 < options["max_tokens"] < 4096
    assert options["max_tokens"] == budget["completion_token_budget"]
    assert budget["fits_context_window"] is True


def test_investigation_context_overflow_fails_before_llm_call(
    monkeypatch,
) -> None:
    transcript = " ".join(f"nguon-{index}" for index in range(2000))
    manager = FakeManager()
    _patch_runtime(monkeypatch, manager)
    monkeypatch.setattr(
        summary_service_v2,
        "context_window_tokens_for_provider",
        lambda _provider: 1024,
    )

    result = summary_service_v2.summarize_transcript_v2(
        transcript,
        summary_type="investigation",
        length_mode="auto",
    )

    assert result["available"] is False
    assert result["error"]["code"] == "SUMMARY_CONTEXT_WINDOW_EXCEEDED"
    assert result["runtime"]["summary_generation"] == "single_prompt_llm"
    assert result["runtime"]["llm_call_count"] == 0
    assert result["runtime"]["context_budget"]["fits_context_window"] is False
    assert result["runtime"]["context_budget"]["full_transcript_included"] is True
    assert manager.calls == []


def test_investigation_only_rejects_empty_or_failed_generation(monkeypatch) -> None:
    empty_manager = FakeManager("```\n\n```")
    _patch_runtime(monkeypatch, empty_manager)
    empty = summary_service_v2.summarize_transcript_v2(
        "Nội dung nguồn.",
        summary_type="investigation",
        length_mode="auto",
    )
    assert empty["available"] is False
    assert empty["error"]["code"] == "SUMMARY_EMPTY"
    assert empty["runtime"]["llm_call_count"] == 1

    def failed_generate(_prompt: str, **_kwargs) -> str:
        raise RuntimeError("provider failed")

    failed_manager = FakeManager()
    failed_manager.generate = failed_generate  # type: ignore[method-assign]
    _patch_runtime(monkeypatch, failed_manager)
    failed = summary_service_v2.summarize_transcript_v2(
        "Nội dung nguồn.",
        summary_type="investigation",
        length_mode="auto",
    )
    assert failed["available"] is False
    assert failed["error"]["code"] == "SUMMARY_GENERATION_FAILED"
    assert failed["runtime"]["llm_call_count"] == 1
    assert failed["runtime"]["context_budget"]["fits_context_window"] is True
