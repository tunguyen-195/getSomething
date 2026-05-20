"""
Bag of Hallucinations (BoH) + Delooping Filter.
Ported from Cherry Core V2.
Based on: "Investigation of Whisper ASR Hallucinations Induced by Non-Speech Audio"
(Barański et al., arXiv:2501.11378, January 2025)

Results: 67% reduction in erroneous outputs when combined with VAD.
"""
import re
from typing import Any, Set
import logging

logger = logging.getLogger(__name__)


class HallucinationFilter:
    """
    Post-processing filter to remove Whisper hallucinations.

    Research findings (arXiv:2501.11378):
    - ~35% of hallucinations are just 2 phrases
    - >50% come from top 10 common outputs
    - 9.1% involve looping patterns
    - 67% reduction when combined with VAD preprocessing
    """

    # Top hallucinations from research (English)
    ENGLISH_BOH: Set[str] = {
        "thanks for watching",
        "thank you for watching",
        "please subscribe",
        "like and subscribe",
        "subtitles by the amara.org community",
        "transcript emily beynon",
        "don't forget to subscribe",
        "see you next time",
        "bye bye",
        "goodbye",
        "[music]",
        "[applause]",
        "[silence]",
        "[inaudible]",
        "...",
        "you",  # Common single-word hallucination in silence
    }

    # Vietnamese hallucinations (observed in practice + adapted from English)
    VIETNAMESE_BOH: Set[str] = {
        "cảm ơn đã xem",
        "đăng ký kênh",
        "nhớ like và subscribe",
        "hẹn gặp lại",
        "tạm biệt",  # When no one is speaking
        "xin chào",  # When no one is actually greeting
        "[âm nhạc]",
        "[tiếng vỗ tay]",
        "[im lặng]",
        "...",
        "ờ",  # Single filler when actually silence
        "à",
        "ừ",
        "ờ ờ",
        "ừ ừ",
        "à à",
        "hả",
        "hử",
        "ơ",
        # Common YouTube hallucinations in Vietnamese
        "cảm ơn các bạn đã theo dõi",
        "đừng quên đăng ký kênh",
        "nhấn like và subscribe",
        "hẹn gặp lại các bạn",
    }

    # These can be real user utterances. Only discard them when ASR metadata also
    # says the segment is probably silence/low-confidence output.
    CONTEXTUAL_VIETNAMESE_BOH: Set[str] = {
        "xin chào",
        "tạm biệt",
        "ờ",
        "à",
        "ừ",
        "ờ ờ",
        "ừ ừ",
        "à à",
        "hả",
        "hử",
        "ơ",
    }

    CONTEXTUAL_ENGLISH_BOH: Set[str] = {
        "you",
        "bye bye",
        "goodbye",
    }

    # Word-level loop pattern
    WORD_LOOP_PATTERN = re.compile(
        r'(\b[\w\u00C0-\u1EF9]+\b)(\s*[.,!?]?\s*\1){2,}',
        re.IGNORECASE
    )
    THAI_SCRIPT_PATTERN = re.compile(r"[\u0E00-\u0E7F]")
    LETTER_PATTERN = re.compile(r"[A-Za-z\u00C0-\u1EF9]")

    @classmethod
    def _strict_boh(cls, language: str) -> Set[str]:
        if language == "vi":
            return cls.VIETNAMESE_BOH - cls.CONTEXTUAL_VIETNAMESE_BOH
        return cls.ENGLISH_BOH - cls.CONTEXTUAL_ENGLISH_BOH

    @classmethod
    def _contextual_boh(cls, language: str) -> Set[str]:
        if language == "vi":
            return cls.CONTEXTUAL_VIETNAMESE_BOH
        return cls.CONTEXTUAL_ENGLISH_BOH

    @staticmethod
    def _float_metric(segment: dict[str, Any] | None, *keys: str) -> float | None:
        if not segment:
            return None
        for key in keys:
            value = segment.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    @classmethod
    def _is_low_quality_segment(
        cls,
        segment: dict[str, Any] | None,
        *,
        min_avg_logprob: float = -1.25,
        max_no_speech_prob: float = 0.75,
        max_compression_ratio: float = 2.6,
    ) -> bool:
        avg_logprob = cls._float_metric(segment, "avg_logprob", "confidence")
        no_speech_prob = cls._float_metric(segment, "no_speech_prob")
        compression_ratio = cls._float_metric(segment, "compression_ratio")
        avg_word_probability = cls._float_metric(segment, "avg_word_probability")

        if no_speech_prob is not None and no_speech_prob >= max_no_speech_prob:
            return True
        if avg_logprob is not None and avg_logprob <= min_avg_logprob:
            return True
        if compression_ratio is not None and compression_ratio >= max_compression_ratio:
            return True
        if avg_word_probability is not None and avg_word_probability < 0.25:
            return True
        return False

    @classmethod
    def _thai_script_ratio(cls, text: str) -> float:
        letters = cls.LETTER_PATTERN.findall(text) + cls.THAI_SCRIPT_PATTERN.findall(text)
        if not letters:
            return 0.0
        return len(cls.THAI_SCRIPT_PATTERN.findall(text)) / len(letters)

    @classmethod
    def _is_script_mismatch(cls, text: str, language: str) -> bool:
        if language != "vi":
            return False
        return cls._thai_script_ratio(text) >= 0.25

    @classmethod
    def deloop(cls, text: str) -> str:
        """
        Remove looping patterns (9.1% of hallucinations).

        Examples:
        - "Quyên. Quyên. Quyên." → "Quyên."
        - "xin chào xin chào xin chào" → "xin chào"
        """
        if not text:
            return text

        # Word-level delooping
        text = cls.WORD_LOOP_PATTERN.sub(r'\1', text)

        # Phrase-level delooping (2-5 words repeated)
        for n in range(5, 1, -1):
            phrase_pattern = re.compile(
                rf'((?:\b[\w\u00C0-\u1EF9]+\b\s*){{1,{n}}})((?:\s*\1){{1,}})',
                re.IGNORECASE
            )
            text = phrase_pattern.sub(r'\1', text)

        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    @classmethod
    def remove_boh(cls, text: str, language: str = "vi") -> str:
        """
        Remove known hallucinations from Bag of Hallucinations.

        Args:
            text: Input text
            language: "vi" or "en"

        Returns:
            Cleaned text with hallucinations removed
        """
        if not text:
            return text

        boh = cls._strict_boh(language)

        for hallucination in boh:
            # Case-insensitive removal with boundary handling
            pattern = re.compile(
                rf'\s*{re.escape(hallucination)}\s*[.,!?]?\s*',
                re.IGNORECASE
            )
            text = pattern.sub(' ', text)

        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    @classmethod
    def is_likely_hallucination(
        cls,
        text: str,
        language: str = "vi",
        segment: dict[str, Any] | None = None,
        *,
        min_avg_logprob: float = -1.25,
        max_no_speech_prob: float = 0.75,
        max_compression_ratio: float = 2.6,
    ) -> bool:
        """
        Check if entire segment is likely a hallucination.

        Args:
            text: Segment text
            language: "vi" or "en"

        Returns:
            True if segment should be discarded entirely
        """
        if not text:
            return True

        text_lower = text.strip().lower()

        if cls._is_script_mismatch(text, language):
            return True

        # Check full match against BoH. Contextual short phrases are only
        # removed when Whisper metadata also indicates low-confidence/silence.
        for hallucination in cls._strict_boh(language):
            if text_lower == hallucination.lower():
                return True

        for hallucination in cls._contextual_boh(language):
            if text_lower == hallucination.lower():
                return cls._is_low_quality_segment(
                    segment,
                    min_avg_logprob=min_avg_logprob,
                    max_no_speech_prob=max_no_speech_prob,
                    max_compression_ratio=max_compression_ratio,
                )

        # Check if mostly punctuation or too short
        alphanumeric = re.sub(r'[^\w]', '', text)
        if len(alphanumeric) < 2:
            return True

        return False

    @classmethod
    def filter(cls, text: str, language: str = "vi") -> str:
        """
        Full hallucination filtering pipeline.

        Order: Deloop → BoH Removal → Cleanup

        Args:
            text: Raw ASR output
            language: "vi" or "en"

        Returns:
            Cleaned text
        """
        if not text:
            return text

        original_length = len(text)

        # Step 1: Remove looping patterns first (catches repeated hallucinations)
        text = cls.deloop(text)

        # Step 2: Remove known hallucinations
        text = cls.remove_boh(text, language)

        # Step 3: Final cleanup
        text = re.sub(r'\s+', ' ', text).strip()

        # Log if significant changes were made
        if len(text) < original_length * 0.9:
            logger.info(f"[HallucinationFilter] Removed {original_length - len(text)} chars of hallucinations")

        return text

    @classmethod
    def filter_segments(
        cls,
        segments: list,
        language: str = "vi",
        *,
        min_avg_logprob: float = -1.25,
        max_no_speech_prob: float = 0.75,
        max_compression_ratio: float = 2.6,
    ) -> list:
        """
        Filter hallucinations from transcript segments.

        Args:
            segments: List of segment dicts with 'text' key
            language: "vi" or "en"

        Returns:
            Filtered segments (removes entirely hallucinated segments)
        """
        filtered = []
        removed_count = 0

        for seg in segments:
            text = seg.get('text', '')

            # Skip entirely hallucinated segments
            if cls.is_likely_hallucination(
                text,
                language,
                seg,
                min_avg_logprob=min_avg_logprob,
                max_no_speech_prob=max_no_speech_prob,
                max_compression_ratio=max_compression_ratio,
            ):
                removed_count += 1
                continue

            # Filter partial hallucinations
            cleaned_text = cls.filter(text, language)

            if cleaned_text:
                filtered.append({
                    **seg,
                    'text': cleaned_text
                })

        if removed_count > 0:
            logger.info(f"[HallucinationFilter] Removed {removed_count} hallucinated segments")

        return filtered

    @classmethod
    def guard_segments(
        cls,
        segments: list[dict[str, Any]],
        language: str = "vi",
        *,
        min_avg_logprob: float = -1.25,
        max_no_speech_prob: float = 0.75,
        max_compression_ratio: float = 2.6,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []

        for index, seg in enumerate(segments):
            text = str(seg.get("text", "")).strip()
            reasons: list[str] = []
            if not text:
                reasons.append("empty_text")
            if text and cls._is_script_mismatch(text, language):
                reasons.append("script_mismatch")
            if text and cls.is_likely_hallucination(
                text,
                language,
                seg,
                min_avg_logprob=min_avg_logprob,
                max_no_speech_prob=max_no_speech_prob,
                max_compression_ratio=max_compression_ratio,
            ):
                reasons.append("known_or_low_quality_hallucination")

            cleaned_text = "" if reasons else cls.filter(text, language)
            if cleaned_text:
                guarded = {**seg, "text": cleaned_text}
                if reasons:
                    guarded["guard_flags"] = reasons
                filtered.append(guarded)
            else:
                removed.append(
                    {
                        "index": index,
                        "start": seg.get("start"),
                        "end": seg.get("end"),
                        "reasons": reasons or ["empty_after_filter"],
                    }
                )

        report = {
            "enabled": True,
            "removed_segments": len(removed),
            "removed": removed[:20],
        }
        if removed:
            logger.info("[HallucinationFilter] Guard removed %s segment(s)", len(removed))
        return filtered, report

    @classmethod
    def add_vietnamese_hallucination(cls, phrase: str):
        """Add a new hallucination to Vietnamese BoH at runtime."""
        cls.VIETNAMESE_BOH.add(phrase.lower())

    @classmethod
    def add_english_hallucination(cls, phrase: str):
        """Add a new hallucination to English BoH at runtime."""
        cls.ENGLISH_BOH.add(phrase.lower())


# Convenience function
def filter_hallucinations(text: str, language: str = "vi") -> str:
    """
    Convenience function for hallucination filtering.

    Args:
        text: Raw ASR output
        language: "vi" or "en"

    Returns:
        Cleaned text
    """
    return HallucinationFilter.filter(text, language)


def filter_transcript_segments(segments: list, language: str = "vi") -> list:
    """
    Convenience function for filtering transcript segments.

    Args:
        segments: List of segment dicts with 'text' key
        language: "vi" or "en"

    Returns:
        Filtered segments
    """
    return HallucinationFilter.filter_segments(segments, language)


def guard_transcript_segments(
    segments: list[dict[str, Any]],
    language: str = "vi",
    *,
    min_avg_logprob: float = -1.25,
    max_no_speech_prob: float = 0.75,
    max_compression_ratio: float = 2.6,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return HallucinationFilter.guard_segments(
        segments,
        language,
        min_avg_logprob=min_avg_logprob,
        max_no_speech_prob=max_no_speech_prob,
        max_compression_ratio=max_compression_ratio,
    )
