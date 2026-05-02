"""
Bag of Hallucinations (BoH) + Delooping Filter.
Ported from Cherry Core V2.
Based on: "Investigation of Whisper ASR Hallucinations Induced by Non-Speech Audio"
(Barański et al., arXiv:2501.11378, January 2025)

Results: 67% reduction in erroneous outputs when combined with VAD.
"""
import re
from typing import Set
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

    # Word-level loop pattern
    WORD_LOOP_PATTERN = re.compile(
        r'(\b[\w\u00C0-\u1EF9]+\b)(\s*[.,!?]?\s*\1){2,}',
        re.IGNORECASE
    )

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

        boh = cls.VIETNAMESE_BOH if language == "vi" else cls.ENGLISH_BOH

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
    def is_likely_hallucination(cls, text: str, language: str = "vi") -> bool:
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

        # Check full match against BoH
        boh = cls.VIETNAMESE_BOH if language == "vi" else cls.ENGLISH_BOH

        for hallucination in boh:
            if text_lower == hallucination.lower():
                return True

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
    def filter_segments(cls, segments: list, language: str = "vi") -> list:
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
            if cls.is_likely_hallucination(text, language):
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
