"""
Intelligent Transcript Post-Processor
Fixes common errors using LLM + domain knowledge
"""

import re
import requests
from typing import Dict, List
from difflib import SequenceMatcher
from .hotel_vocabulary import get_all_hotels, PHONETIC_CORRECTIONS
import logging

logger = logging.getLogger(__name__)


class TranscriptCorrector:
    def __init__(self, ollama_model: str = "gemma2:9b"):
        self.model = ollama_model
        self.ollama_url = "http://localhost:11434/api/generate"
        self.hotels = get_all_hotels()

    def correct_transcript(self, text: str, context: str = "hotel") -> Dict[str, any]:
        """
        Correct transcript với multi-stage approach
        Returns: {
            'original': str,
            'corrected': str,
            'changes': List[Dict],
            'confidence': float
        }
        """
        changes = []
        corrected = text

        # Stage 1: Normalize elongated words
        corrected, word_changes = self._normalize_elongated_words(corrected)
        changes.extend(word_changes)

        # Stage 2: Fix hotel names (critical)
        corrected, hotel_changes = self._correct_hotel_names(corrected)
        changes.extend(hotel_changes)

        # Stage 3: LLM-based subtle corrections
        if context:
            corrected, llm_changes = self._llm_correct(corrected, context)
            changes.extend(llm_changes)

        # Stage 4: Consistency checks
        corrected = self._ensure_consistency(corrected, changes)

        return {
            'original': text,
            'corrected': corrected,
            'changes': changes,
            'confidence': self._calculate_confidence(changes)
        }

    def _normalize_elongated_words(self, text: str) -> tuple:
        """Fix elongated words like 'đúnggg' → 'đúng'"""
        changes = []

        # Pattern: 3+ repeated characters
        pattern = r'(\w)(\1{2,})'

        def replace_func(match):
            original = match.group(0)
            char = match.group(1)
            # Keep max 2 repetitions (for emphasis like 'ôiii')
            replacement = char * min(2, len(original))

            if len(original) > 3:  # Only log significant changes
                changes.append({
                    'type': 'elongation',
                    'from': original,
                    'to': replacement,
                    'position': match.start()
                })

            return replacement

        corrected = re.sub(pattern, replace_func, text)
        return corrected, changes

    def _correct_hotel_names(self, text: str) -> tuple:
        """Correct hotel names using fuzzy matching"""
        changes = []
        corrected = text

        # Check for known phonetic confusions
        for wrong, candidates in PHONETIC_CORRECTIONS.items():
            if wrong.lower() in text.lower():
                # Find best match from candidates
                best_match = self._find_best_hotel_match(wrong, candidates)

                if best_match:
                    # Case-insensitive replacement
                    pattern = re.compile(re.escape(wrong), re.IGNORECASE)
                    corrected = pattern.sub(best_match, corrected)

                    changes.append({
                        'type': 'hotel_name',
                        'from': wrong,
                        'to': best_match,
                        'confidence': 0.8,
                        'method': 'phonetic_correction'
                    })

        # Fuzzy match against full hotel database
        words = corrected.split()
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"

            # Check if looks like hotel name (capitalized or Hotel/Khách sạn)
            if (words[i][0].isupper() or
                'hotel' in bigram.lower() or
                'khách sạn' in bigram.lower()):

                match = self._fuzzy_match_hotel(bigram)
                if match and match != bigram:
                    corrected = corrected.replace(bigram, match)
                    changes.append({
                        'type': 'hotel_name',
                        'from': bigram,
                        'to': match,
                        'confidence': 0.7,
                        'method': 'fuzzy_match'
                    })

        return corrected, changes

    def _find_best_hotel_match(self, query: str, candidates: List[str]) -> str:
        """Find best matching hotel name from candidates"""
        best_match = None
        best_score = 0

        for candidate in candidates:
            # Check if candidate exists in our database
            for hotel in self.hotels:
                if candidate.lower() in hotel.lower():
                    score = SequenceMatcher(None, query.lower(), candidate.lower()).ratio()
                    if score > best_score:
                        best_score = score
                        best_match = hotel

        return best_match if best_score > 0.6 else None

    def _fuzzy_match_hotel(self, query: str) -> str:
        """Fuzzy match query against hotel database"""
        best_match = query
        best_score = 0.85  # High threshold to avoid false positives

        query_lower = query.lower()

        for hotel in self.hotels:
            hotel_lower = hotel.lower()

            # Exact substring match
            if query_lower in hotel_lower or hotel_lower in query_lower:
                return hotel

            # Fuzzy match
            score = SequenceMatcher(None, query_lower, hotel_lower).ratio()
            if score > best_score:
                best_score = score
                best_match = hotel

        return best_match

    def _llm_correct(self, text: str, context: str) -> tuple:
        """Use LLM for subtle corrections (optional)"""
        changes = []

        # Only use LLM if there are obvious issues
        if self._needs_llm_correction(text):
            prompt = f"""Bạn là chuyên gia sửa lỗi transcript tiếng Việt.
Context: {context} conversation (hotel booking, customer service, etc.)

Transcript gốc:
{text}

Nhiệm vụ: Sửa CHỈ những lỗi RÕ RÀNG như:
- Tên riêng sai (hotel names, person names)
- Typos rõ ràng
- Homophones (ví dụ: "nói" vs "nói")

KHÔNG SỬA:
- Grammar đúng
- Dấu câu đúng
- Tone markers (ạ, em, chị)
- Colloquial speech

Trả về transcript đã sửa (chỉ text, không giải thích):
"""

            try:
                response = requests.post(
                    self.ollama_url,
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.1,  # Very conservative
                            "top_p": 0.9,
                            "num_ctx": 2048
                        }
                    },
                    timeout=30
                )

                if response.status_code == 200:
                    corrected = response.json().get("response", text).strip()

                    # Only use if changes are minimal
                    similarity = SequenceMatcher(None, text, corrected).ratio()
                    if similarity > 0.95:  # Max 5% change
                        changes.append({
                            'type': 'llm_correction',
                            'method': 'ollama',
                            'model': self.model,
                            'similarity': similarity
                        })
                        return corrected, changes

            except Exception as e:
                logger.warning(f"LLM correction failed: {e}")

        return text, changes

    def _needs_llm_correction(self, text: str) -> bool:
        """Check if text needs LLM correction"""
        # Check for common error patterns
        indicators = [
            r'(\w)\1{3,}',   # Repeated characters (4+)
            r'[a-z][A-Z]',   # Weird capitalization
            r'\d{10,}',      # Very long numbers (might be phone without spaces)
        ]

        for pattern in indicators:
            try:
                if re.search(pattern, text):
                    return True
            except re.error:
                continue

        return False

    def _ensure_consistency(self, text: str, changes: List[Dict]) -> str:
        """Ensure consistent formatting throughout text"""
        # Consistent proper noun capitalization
        text = self._capitalize_proper_nouns(text)

        # Consistent number formatting
        text = self._format_numbers(text)

        return text

    def _capitalize_proper_nouns(self, text: str) -> str:
        """Ensure proper nouns are consistently capitalized"""
        # Names (chị/anh + Name)
        text = re.sub(
            r'(chị|anh)\s+([a-z])',
            lambda m: f"{m.group(1)} {m.group(2).upper()}",
            text,
            flags=re.IGNORECASE
        )

        # Hotel/Khách sạn
        text = re.sub(
            r'(hotel|khách sạn)\s+([a-z])',
            lambda m: f"{m.group(1)} {m.group(2).upper()}",
            text,
            flags=re.IGNORECASE
        )

        return text

    def _format_numbers(self, text: str) -> str:
        """Format numbers consistently"""
        # Phone numbers: add spaces every 3 digits
        # Example: "0978711253" → "097 871 1253"
        text = re.sub(
            r'\b(0\d{9})\b',
            lambda m: ' '.join([m.group(1)[i:i+3] for i in range(0, len(m.group(1)), 3)]),
            text
        )

        return text

    def _calculate_confidence(self, changes: List[Dict]) -> float:
        """Calculate overall confidence score"""
        if not changes:
            return 1.0

        total_confidence = 0
        for change in changes:
            conf = change.get('confidence', 0.5)
            total_confidence += conf

        return total_confidence / len(changes)


def test_corrector():
    """Test the corrector"""
    corrector = TranscriptCorrector()

    test_cases = [
        "Khách sạn Shilla Prius Hotel Hà Nội",
        "đúnggg mục đích của chị rồi",
        "chị tên là quyên em ạ",
    ]

    for test in test_cases:
        result = corrector.correct_transcript(test, context="hotel")
        print(f"\nOriginal: {result['original']}")
        print(f"Corrected: {result['corrected']}")
        print(f"Changes: {result['changes']}")
        print(f"Confidence: {result['confidence']:.2f}")


if __name__ == "__main__":
    test_corrector()
