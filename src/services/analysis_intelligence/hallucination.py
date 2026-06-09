from __future__ import annotations

import json
import re
from typing import Any

from src.core.config import settings
from src.services.hallucination_filter import HallucinationFilter
from src.services.summarization.models.llm_manager import get_llm_manager, llm_provider_configured

from .schemas import HallucinationAnalysis, HallucinationSpan, stable_id


REASON_VI = {
    "script_mismatch": "Đoạn này lệch script/ngôn ngữ mục tiêu, thường là tín hiệu ASR nhận sai.",
    "known_or_low_quality_hallucination": "Guard đã loại vì khớp BoH hoặc tín hiệu chất lượng thấp.",
    "empty_after_filter": "Đoạn bị lọc sạch sau hậu xử lý.",
    "partial_filter": "Đoạn được làm sạch một phần sau hậu xử lý.",
    "boh_phrase": "Cụm này nằm trong Bag of Hallucinations của Cherry2/PhoGuard.",
    "contextual_boh": "Cụm ngắn có thể là hallucination trong ngữ cảnh im lặng hoặc no-speech.",
    "looping_pattern": "Mẫu lặp từ/cụm bất thường, thuộc nhóm looping hallucination.",
    "low_word_probability": "Từ có xác suất thấp, cần nghe lại.",
    "low_avg_logprob": "Độ tin cậy trung bình của đoạn thấp.",
    "high_no_speech_prob": "Mô hình nghi đoạn này không phải lời nói thật.",
    "high_compression_ratio": "Đầu ra bị nén bất thường, thường là hallucination.",
    "llm_flagged": "LLM đánh dấu đây là đoạn nghi ảo giác hoặc sai ngữ cảnh.",
    "llm_clean": "LLM cho rằng đoạn này có thể là ngữ cảnh hợp lệ, cần xem lại thủ công.",
}


def _coerce_segments(segments: Any) -> list[dict[str, Any]]:
    if not isinstance(segments, list):
        return []
    output: list[dict[str, Any]] = []
    for segment in segments:
        if isinstance(segment, dict):
            output.append(segment)
            continue
        if hasattr(segment, "model_dump"):
            try:
                dumped = segment.model_dump(mode="json")
            except Exception:
                continue
            if isinstance(dumped, dict):
                output.append(dumped)
    return output


def _segment_text(segments: list[dict[str, Any]]) -> str:
    return " ".join(
        str(segment.get("text", "")).strip()
        for segment in segments
        if str(segment.get("text", "")).strip()
    ).strip()


def _segment_offsets(segments: list[dict[str, Any]]) -> list[tuple[int, int]]:
    offsets: list[tuple[int, int]] = []
    cursor = 0
    for segment in segments:
        text = str(segment.get("text", "")).strip()
        start = cursor
        end = start + len(text)
        offsets.append((start, end))
        cursor = end + 1
    return offsets


def _reason_vi(reason_codes: list[str], default: str = "Đoạn nghi ảo giác cần review.") -> str:
    reasons = [REASON_VI.get(code, code) for code in reason_codes if code]
    if not reasons:
        return default
    return "; ".join(dict.fromkeys(reasons))


def _append_span(spans: list[HallucinationSpan], span: HallucinationSpan) -> None:
    if any(existing.id == span.id for existing in spans):
        return
    spans.append(span)


def _extract_json_payload(text: str) -> Any:
    clean = (text or "").strip()
    if not clean:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", clean, re.DOTALL | re.IGNORECASE)
    if fenced:
        clean = fenced.group(1).strip()
    for candidate in (clean, re.search(r"\[[\s\S]*\]", clean), re.search(r"\{[\s\S]*\}", clean)):
        if candidate is None:
            continue
        try:
            payload = candidate if isinstance(candidate, str) else candidate.group(0)
            return json.loads(payload)
        except Exception:
            continue
    return None


def _build_candidate_prompt(
    *,
    raw_transcript: str,
    filtered_transcript: str,
    spans: list[HallucinationSpan],
) -> str:
    span_payload = [
        {
            "id": span.id,
            "status": span.status,
            "source": span.source,
            "text": span.text,
            "filtered_text": span.filtered_text,
            "reason_codes": span.reason_codes,
            "reason_vi": span.reason_vi,
            "start_time": span.start_time,
            "end_time": span.end_time,
        }
        for span in spans[:8]
    ]
    return f"""
BẠN LÀ BỘ LỌC ẢO GIÁC ASR.
Nhiệm vụ: đánh giá từng span dưới đây xem nó là hallucination, likely_hallucination, uncertain hay clean_context.
Chỉ trả về JSON array hợp lệ, không thêm giải thích ngoài JSON.

Schema mỗi phần tử:
{{
  "id": "span id",
  "verdict": "hallucination|likely_hallucination|uncertain|clean_context",
  "reason_vi": "lý do ngắn bằng tiếng Việt",
  "suggested_filtered_text": "chuỗi rút gọn nếu nên lọc, hoặc giữ nguyên nếu không cần",
  "confidence": 0.0
}}

Transcript gốc:
{raw_transcript}

Transcript sau lọc:
{filtered_transcript}

Candidate spans:
{json.dumps(span_payload, ensure_ascii=False, indent=2)}
""".strip()


def _attach_llm_review(
    spans: list[HallucinationSpan],
    *,
    raw_transcript: str,
    filtered_transcript: str,
) -> str:
    if not spans:
        return "no_candidates"
    if not settings.ANALYSIS_INTELLIGENCE_LLM_ENABLED:
        return "disabled"
    if not llm_provider_configured():
        return "not_configured"

    try:
        llm = get_llm_manager()
        prompt = _build_candidate_prompt(
            raw_transcript=raw_transcript,
            filtered_transcript=filtered_transcript,
            spans=spans,
        )
        response = llm.generate(prompt, temperature=0.0, max_tokens=min(900, settings.ANALYSIS_LLM_MAX_OUTPUT_TOKENS))
        payload = _extract_json_payload(response)
        if not isinstance(payload, list):
            return "parse_failed"
        by_id = {str(item.get("id")): item for item in payload if isinstance(item, dict) and item.get("id")}
        for span in spans:
            review = by_id.get(span.id)
            if not review:
                continue
            span.llm_review = {
                "verdict": str(review.get("verdict") or "uncertain"),
                "reason_vi": str(review.get("reason_vi") or "").strip(),
                "suggested_filtered_text": review.get("suggested_filtered_text"),
                "confidence": review.get("confidence"),
            }
            if str(review.get("verdict") or "").lower() in {"hallucination", "likely_hallucination"} and span.status == "flagged":
                span.reason_vi = review.get("reason_vi") or span.reason_vi
        return "ok"
    except Exception:
        return "failed"


def build_hallucination_analysis(
    result: dict[str, Any] | None,
    segments: list[dict[str, Any]] | None = None,
    *,
    transcript: str | None = None,
    language: str | None = None,
) -> HallucinationAnalysis:
    result = result if isinstance(result, dict) else {}
    raw_segments = _coerce_segments(result.get("raw_segments"))
    filtered_segments = _coerce_segments(segments or result.get("segments"))
    if not raw_segments:
        raw_segments = filtered_segments

    raw_transcript = str(
        result.get("raw_transcription")
        or result.get("raw_text")
        or transcript
        or _segment_text(raw_segments)
        or ""
    ).strip()
    filtered_transcript = str(
        result.get("filtered_transcription")
        or result.get("transcription")
        or result.get("filtered_text")
        or transcript
        or _segment_text(filtered_segments)
        or ""
    ).strip()

    guard = result.get("hallucination_report")
    if not isinstance(guard, dict):
        guard = result.get("phoguard") if isinstance(result.get("phoguard"), dict) else {}
    if not isinstance(guard, dict):
        guard = {}

    if not language:
        language = (
            str(result.get("language") or result.get("model_info", {}).get("requested_language") or settings.DEFAULT_LANGUAGE or "vi")
            .strip()
            .lower()
        )
    else:
        language = language.strip().lower()

    removed_lookup: dict[int, dict[str, Any]] = {}
    for item in guard.get("removed", []) or []:
        if isinstance(item, dict) and isinstance(item.get("index"), int):
            removed_lookup[int(item["index"])] = item

    changed_lookup: dict[int, dict[str, Any]] = {}
    for item in guard.get("changed", []) or []:
        if isinstance(item, dict) and isinstance(item.get("index"), int):
            changed_lookup[int(item["index"])] = item

    strict_phrases = sorted(HallucinationFilter._strict_boh(language), key=len, reverse=True)
    contextual_phrases = sorted(HallucinationFilter._contextual_boh(language), key=len, reverse=True)
    offsets = _segment_offsets(raw_segments)
    spans: list[HallucinationSpan] = []

    filtered_index = 0
    for raw_index, raw_segment in enumerate(raw_segments):
        segment_text = str(raw_segment.get("text", "")).strip()
        if not segment_text:
            continue
        start_time = raw_segment.get("start")
        end_time = raw_segment.get("end")
        segment_id = str(
            raw_segment.get("id")
            or raw_segment.get("segment_id")
            or stable_id("halluc_seg", raw_index, segment_text[:80], start_time, end_time)
        )
        segment_start, segment_end = offsets[raw_index] if raw_index < len(offsets) else (0, len(segment_text))
        filtered_segment = None
        if raw_index not in removed_lookup and filtered_index < len(filtered_segments):
            filtered_segment = filtered_segments[filtered_index]
            filtered_index += 1
        filtered_text = str(filtered_segment.get("text", "")).strip() if isinstance(filtered_segment, dict) else ""
        removed_item = removed_lookup.get(raw_index)
        changed_item = changed_lookup.get(raw_index)
        segment_low_quality = HallucinationFilter._is_low_quality_segment(
            raw_segment,
            min_avg_logprob=settings.ASR_GUARD_MIN_AVG_LOGPROB,
            max_no_speech_prob=settings.ASR_GUARD_MAX_NO_SPEECH_PROB,
            max_compression_ratio=settings.ASR_GUARD_MAX_COMPRESSION_RATIO,
        )

        if removed_item or changed_item or (filtered_text and filtered_text != segment_text):
            reason_codes = list((removed_item or changed_item or {}).get("reasons") or [])
            if not reason_codes:
                reason_codes = ["partial_filter"]
            _append_span(
                spans,
                HallucinationSpan(
                    id=stable_id("halluc_span", "segment", segment_id, "filtered"),
                    text=segment_text,
                    filtered_text=filtered_text or None,
                    status="filtered",
                    source="asr_guard",
                    reason_codes=reason_codes,
                    reason_vi=_reason_vi(reason_codes),
                    confidence=0.98,
                    start_time=float(start_time) if isinstance(start_time, (int, float)) else None,
                    end_time=float(end_time) if isinstance(end_time, (int, float)) else None,
                    segment_id=segment_id,
                    char_start=segment_start,
                    char_end=segment_end,
                ),
            )

        if removed_item:
            continue

        text_lower = segment_text.lower()
        phrase_hit = False
        for phrase in strict_phrases:
            for match in re.finditer(re.escape(phrase), segment_text, flags=re.IGNORECASE):
                phrase_hit = True
                reason_codes = ["boh_phrase"]
                matched_text = match.group(0)
                _append_span(
                    spans,
                    HallucinationSpan(
                        id=stable_id("halluc_span", segment_id, "strict", phrase, match.start(), match.end()),
                        text=matched_text,
                        filtered_text=filtered_text if filtered_text and filtered_text != segment_text else None,
                        status="filtered" if filtered_text and filtered_text != segment_text else "flagged",
                        source="boh_phrase",
                        reason_codes=reason_codes,
                        reason_vi=_reason_vi(reason_codes, "Cụm nằm trong Bag of Hallucinations."),
                        confidence=0.92,
                        start_time=float(start_time) if isinstance(start_time, (int, float)) else None,
                        end_time=float(end_time) if isinstance(end_time, (int, float)) else None,
                        segment_id=segment_id,
                        char_start=segment_start + match.start(),
                        char_end=segment_start + match.end(),
                    ),
                )
                break
            if phrase_hit:
                break

        if not phrase_hit and segment_low_quality:
            for phrase in contextual_phrases:
                if phrase.lower() not in text_lower:
                    continue
                match = re.search(re.escape(phrase), segment_text, flags=re.IGNORECASE)
                if not match:
                    continue
                reason_codes = ["contextual_boh"]
                _append_span(
                    spans,
                    HallucinationSpan(
                        id=stable_id("halluc_span", segment_id, "contextual", phrase, match.start(), match.end()),
                        text=match.group(0),
                        filtered_text=filtered_text if filtered_text and filtered_text != segment_text else None,
                        status="flagged",
                        source="contextual_boh",
                        reason_codes=reason_codes,
                        reason_vi=_reason_vi(reason_codes, "Cụm ngắn chỉ là hallucination khi ngữ cảnh rất yếu."),
                        confidence=0.72,
                        start_time=float(start_time) if isinstance(start_time, (int, float)) else None,
                        end_time=float(end_time) if isinstance(end_time, (int, float)) else None,
                        segment_id=segment_id,
                        char_start=segment_start + match.start(),
                        char_end=segment_start + match.end(),
                    ),
                )
                phrase_hit = True
                break

        if not phrase_hit:
            loop_match = HallucinationFilter.WORD_LOOP_PATTERN.search(segment_text)
            if loop_match:
                reason_codes = ["looping_pattern"]
                _append_span(
                    spans,
                    HallucinationSpan(
                        id=stable_id("halluc_span", segment_id, "loop", loop_match.start(), loop_match.end()),
                        text=loop_match.group(0).strip(),
                        filtered_text=HallucinationFilter.deloop(loop_match.group(0)).strip() or None,
                        status="flagged",
                        source="loop_pattern",
                        reason_codes=reason_codes,
                        reason_vi=_reason_vi(reason_codes),
                        confidence=0.8,
                        start_time=float(start_time) if isinstance(start_time, (int, float)) else None,
                        end_time=float(end_time) if isinstance(end_time, (int, float)) else None,
                        segment_id=segment_id,
                        char_start=segment_start + loop_match.start(),
                        char_end=segment_start + loop_match.end(),
                    ),
                )

        words = raw_segment.get("words") if isinstance(raw_segment.get("words"), list) else []
        for word_index, word in enumerate(words):
            if not isinstance(word, dict):
                continue
            word_text = str(word.get("word", "")).strip()
            if not word_text:
                continue
            probability = word.get("probability")
            try:
                probability_value = float(probability) if probability is not None else None
            except (TypeError, ValueError):
                probability_value = None
            if probability_value is None or probability_value >= 0.25:
                continue
            local_match = re.search(re.escape(word_text), segment_text, flags=re.IGNORECASE)
            local_start = local_match.start() if local_match else 0
            local_end = local_match.end() if local_match else min(len(segment_text), local_start + len(word_text))
            reason_codes = ["low_word_probability"]
            _append_span(
                spans,
                HallucinationSpan(
                    id=stable_id("halluc_span", segment_id, "word", word_index, word_text, local_start, local_end),
                    text=word_text,
                    filtered_text=None,
                    status="flagged",
                    source="word_probability",
                    reason_codes=reason_codes,
                    reason_vi=_reason_vi(reason_codes),
                    confidence=max(0.35, min(0.9, 1.0 - probability_value)),
                    start_time=float(word.get("start")) if isinstance(word.get("start"), (int, float)) else (
                        float(start_time) if isinstance(start_time, (int, float)) else None
                    ),
                    end_time=float(word.get("end")) if isinstance(word.get("end"), (int, float)) else (
                        float(end_time) if isinstance(end_time, (int, float)) else None
                    ),
                    segment_id=segment_id,
                    char_start=segment_start + local_start,
                    char_end=segment_start + local_end,
                    word_index=word_index,
                ),
            )

        if segment_low_quality and not any(span.segment_id == segment_id for span in spans):
            reason_codes = []
            if raw_segment.get("no_speech_prob") is not None and float(raw_segment.get("no_speech_prob") or 0.0) >= settings.ASR_GUARD_MAX_NO_SPEECH_PROB:
                reason_codes.append("high_no_speech_prob")
            if raw_segment.get("avg_logprob") is not None and float(raw_segment.get("avg_logprob") or 0.0) <= settings.ASR_GUARD_MIN_AVG_LOGPROB:
                reason_codes.append("low_avg_logprob")
            if raw_segment.get("compression_ratio") is not None and float(raw_segment.get("compression_ratio") or 0.0) >= settings.ASR_GUARD_MAX_COMPRESSION_RATIO:
                reason_codes.append("high_compression_ratio")
            if not reason_codes:
                reason_codes = ["known_or_low_quality_hallucination"]
            _append_span(
                spans,
                HallucinationSpan(
                    id=stable_id("halluc_span", segment_id, "review", segment_text[:60]),
                    text=segment_text,
                    filtered_text=filtered_text or None,
                    status="kept_for_review",
                    source="segment_quality",
                    reason_codes=reason_codes,
                    reason_vi=_reason_vi(reason_codes),
                    confidence=0.7,
                    start_time=float(start_time) if isinstance(start_time, (int, float)) else None,
                    end_time=float(end_time) if isinstance(end_time, (int, float)) else None,
                    segment_id=segment_id,
                    char_start=segment_start,
                    char_end=segment_end,
                ),
            )

    llm_status = _attach_llm_review(
        spans,
        raw_transcript=raw_transcript,
        filtered_transcript=filtered_transcript,
    )

    removed_count = sum(1 for span in spans if span.status == "filtered")
    flagged_count = sum(1 for span in spans if span.status in {"flagged", "kept_for_review"})
    review_required = bool(removed_count or flagged_count)

    summary_vi = (
        f"Phát hiện {removed_count} span đã lọc và {flagged_count} span cần review."
        if spans
        else "Chưa phát hiện span ảo giác rõ ràng, nhưng vẫn nên nghe lại khi ASR có cảnh báo chất lượng."
    )

    basis = [
        "BoH + delooping được port từ Cherry2/PhoGuard để bắt các cụm hay xuất hiện khi ASR gặp silence/no-speech.",
        "Các tín hiệu như avg_logprob, no_speech_prob, compression_ratio và xác suất từng từ chỉ là proxy, không phải kết luận tuyệt đối.",
        "Nếu bật LLM, hệ thống sẽ gắn nhãn lại các span nghi ngờ để người dùng thấy rõ phần nào đã bị lọc và phần nào cần nghe lại.",
    ]

    return HallucinationAnalysis(
        enabled=True,
        source="phoguard_boh_deloop",
        research_basis_vi=basis,
        raw_transcript=raw_transcript or None,
        filtered_transcript=filtered_transcript or None,
        removed_count=removed_count,
        flagged_count=flagged_count,
        review_required=review_required,
        spans=spans,
        llm_status=llm_status,
        summary_vi=summary_vi,
    )
