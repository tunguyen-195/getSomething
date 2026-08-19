"""
Vietnamese Post-Processor for ASR Output.
Handles domain-specific corrections, phone numbers, and common ASR errors.
"""
import re
from typing import Dict


class VietnamesePostProcessor:
    """
    Vietnamese-specific post-processing for ASR output.
    
    Features:
    - Domain-specific term correction
    - Common ASR error patterns
    - Phone number formatting
    - Proper noun capitalization
    """
    
    # Hotel domain corrections (Most common ASR errors)
    HOTEL_CORRECTIONS = {
        # English terms misheard
        "đi lặn": "Deluxe",
        "đi lắc": "Deluxe",
        "đề lác": "Deluxe",
        "phòng đi lặn": "phòng Deluxe",
        "vòng x kế tiếp": "Executive",
        "x kế tiếp": "Executive",
        "ích sếch quy típ": "Executive",
        "phòng vòng x kế tiếp": "phòng Executive",
        
        # Vietnamese homophones (from comparison report)
        "điều trú": "lưu trú",
        "đi trú": "lưu trú",
        "cộng phận": "bộ phận",
        "căn cứ công dân": "căn cước công dân",
        "căn cướp công dân": "căn cước công dân",
        "căn cướp": "căn cước",
        "căn cứ": "căn cước",
        "quỷ trả": "hủy trả",
        "nghiêm tiếp": "niêm yết",
        "giá nhịp ít": "giá niêm yết",
        "nhịp ít": "niêm yết",
        "Xin ký chào": "Xin kính chào",
        "Xin ký": "Xin kính",
        "cái sạn": "khách sạn",
        "kẻ sạn": "khách sạn",
        "ở cái sạn": "ở khách sạn",
        
        # Common mishearings (from comparison report)
        "sức phòng": "giữ phòng",
        "một đêm tròng": "một đêm trọn",
        "một đêm tròng": "một đêm",
        "yêu đãi": "ưu đãi",
        "chương trình yêu đãi": "chương trình ưu đãi",
        "quên vui lòng": "vui lòng",  # Name "Quyên" misheard as "quên"
        "chị quên": "chị Quyên",  # Name correction
        "quyết định": "quy định",  # Context-based
        "theo quyết định": "theo quy định",
        "một xuất": "một suất",
        "nhựa đắt": "hơi đắt",
        "3 triệu hơi nhựa đắt": "3 triệu hơi đắt",
    }
    
    # General Vietnamese corrections
    GENERAL_CORRECTIONS = {
        # Sentence starters (capitalization)
        "dạ vâng ạ": "Dạ vâng ạ",
        "dạ dạ": "Dạ dạ",
        "ờ": "Ờ",
        "à": "À",
        "ừ": "Ừ",
    }
    
    # Proper nouns (hotel names, places)
    PROPER_NOUNS = [
        "JW Marriott",
        "Marriott",
        "G.W. Marriott",
        "Fitness Center",
        "Hà Nội",
        "Việt Nam",
        "Executive",
        "Deluxe",
    ]
    
    def __init__(self, domain: str = "general"):
        """
        Args:
            domain: "hotel", "legal", "medical", or "general"
        """
        self.domain = domain
        self._build_correction_map()
    
    def _build_correction_map(self):
        """Build combined correction map based on domain."""
        self.corrections = {}
        self.corrections.update(self.GENERAL_CORRECTIONS)
        
        if self.domain == "hotel":
            self.corrections.update(self.HOTEL_CORRECTIONS)
        # Add more domains as needed
    
    def process(self, text: str) -> str:
        """
        Apply all post-processing steps.
        
        Args:
            text: Raw ASR text
            
        Returns:
            Corrected text
        """
        if not text or not text.strip():
            return text
        
        # 1. Apply domain corrections
        text = self._apply_corrections(text)
        
        # 2. Format phone numbers
        text = self._format_phone_numbers(text)
        
        # 3. Capitalize proper nouns
        text = self._capitalize_proper_nouns(text)
        
        # 4. Clean whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def _apply_corrections(self, text: str) -> str:
        """Apply dictionary-based corrections."""
        for wrong, correct in self.corrections.items():
            # Case-insensitive word boundary replacement
            text = re.sub(
                rf'\b{re.escape(wrong)}\b',
                correct,
                text,
                flags=re.IGNORECASE
            )
        return text
    
    def _format_phone_numbers(self, text: str) -> str:
        """
        Format Vietnamese phone numbers.
        Patterns: 0978711253 -> 0978 711 253
        """
        # Pattern for 10-digit phone numbers
        text = re.sub(
            r'\b(\d{4})\s*(\d{3})\s*(\d{3})\b',
            r'\1 \2 \3',
            text
        )
        return text
    
    def _capitalize_proper_nouns(self, text: str) -> str:
        """Ensure proper nouns are correctly capitalized."""
        for noun in self.PROPER_NOUNS:
            text = re.sub(
                rf'\b{re.escape(noun)}\b',
                noun,
                text,
                flags=re.IGNORECASE
            )
        return text
    
    def add_domain_corrections(self, corrections: Dict[str, str]):
        """
        Add custom corrections at runtime.
        
        Args:
            corrections: Dict mapping wrong -> correct
        """
        self.corrections.update(corrections)


# Convenience function
def postprocess_vietnamese(text: str, domain: str = "hotel") -> str:
    """
    Convenience function for quick post-processing.
    
    Args:
        text: Raw ASR text
        domain: Domain for corrections ("hotel", "general")
        
    Returns:
        Corrected text
    """
    processor = VietnamesePostProcessor(domain=domain)
    return processor.process(text)
