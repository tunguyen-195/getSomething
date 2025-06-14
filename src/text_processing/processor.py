import re
from typing import List, Optional
import logging
from pathlib import Path
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TextProcessor:
    def __init__(self, custom_dict_path: Optional[str] = None):
        """
        Initialize text processor
        
        Args:
            custom_dict_path: Path to custom dictionary for text normalization
        """
        self.custom_dict = {}
        if custom_dict_path:
            self.load_custom_dict(custom_dict_path)
    
    def load_custom_dict(self, dict_path: str):
        """
        Load custom dictionary for text normalization
        
        Args:
            dict_path: Path to dictionary file (JSON format)
        """
        try:
            with open(dict_path, 'r', encoding='utf-8') as f:
                self.custom_dict = json.load(f)
            logger.info(f"Loaded custom dictionary from {dict_path}")
        except Exception as e:
            logger.error(f"Error loading custom dictionary: {str(e)}")
    
    def normalize_text(self, text: str) -> str:
        """
        Normalize text by:
        - Removing extra whitespace
        - Normalizing punctuation
        - Applying custom dictionary replacements
        
        Args:
            text: Input text
            
        Returns:
            Normalized text
        """
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Normalize punctuation
        text = re.sub(r'([.,!?])\s*', r'\1 ', text)  # Add space after punctuation
        text = re.sub(r'\s+([.,!?])', r'\1', text)   # Remove space before punctuation
        
        # Apply custom dictionary replacements
        for pattern, replacement in self.custom_dict.items():
            text = text.replace(pattern, replacement)
        
        return text
    
    def split_into_sentences(self, text: str) -> List[str]:
        """
        Split text into sentences
        
        Args:
            text: Input text
            
        Returns:
            List of sentences
        """
        # Split by common sentence endings
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]
    
    def remove_special_chars(self, text: str, keep_punctuation: bool = True) -> str:
        """
        Remove special characters from text
        
        Args:
            text: Input text
            keep_punctuation: Whether to keep punctuation marks
            
        Returns:
            Cleaned text
        """
        if keep_punctuation:
            # Keep letters, numbers, and common punctuation
            pattern = r'[^a-zA-Z0-9\s.,!?;:\'"-]'
        else:
            # Keep only letters, numbers, and spaces
            pattern = r'[^a-zA-Z0-9\s]'
        
        return re.sub(pattern, '', text)
    
    def process_transcription(self, 
                            text: str,
                            remove_special_chars: bool = True,
                            keep_punctuation: bool = True) -> str:
        """
        Process transcription text with all normalizations
        
        Args:
            text: Input transcription text
            remove_special_chars: Whether to remove special characters
            keep_punctuation: Whether to keep punctuation when removing special chars
            
        Returns:
            Processed text
        """
        # Normalize text
        text = self.normalize_text(text)
        
        # Remove special characters if requested
        if remove_special_chars:
            text = self.remove_special_chars(text, keep_punctuation)
        
        return text
    
    def extract_keywords(self, text: str, min_length: int = 3) -> List[str]:
        """
        Extract potential keywords from text
        
        Args:
            text: Input text
            min_length: Minimum word length to consider as keyword
            
        Returns:
            List of potential keywords
        """
        # Remove punctuation and convert to lowercase
        text = self.remove_special_chars(text, keep_punctuation=False).lower()
        
        # Split into words and filter
        words = text.split()
        keywords = [w for w in words if len(w) >= min_length]
        
        # Count word frequencies
        word_freq = {}
        for word in keywords:
            word_freq[word] = word_freq.get(word, 0) + 1
        
        # Sort by frequency
        sorted_keywords = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        
        return [word for word, _ in sorted_keywords]
    
    def save_custom_dict(self, dict_path: str):
        """
        Save custom dictionary to file
        
        Args:
            dict_path: Path to save dictionary file
        """
        try:
            with open(dict_path, 'w', encoding='utf-8') as f:
                json.dump(self.custom_dict, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved custom dictionary to {dict_path}")
        except Exception as e:
            logger.error(f"Error saving custom dictionary: {str(e)}")

    def process_text(self, text: str) -> str:
        """
        Process the transcribed text to clean and normalize it
        """
        try:
            # Remove extra whitespace
            text = re.sub(r'\s+', ' ', text)
            
            # Remove filler words and sounds
            fillers = ['ừ', 'à', 'ờ', 'ơ', 'ừm', 'à ừm']
            for filler in fillers:
                text = text.replace(filler, '')
            
            # Remove repeated words
            text = re.sub(r'\b(\w+)(\s+\1\b)+', r'\1', text)
            
            # Capitalize first letter of sentences
            text = re.sub(r'(^|[.!?]\s+)([a-z])', lambda m: m.group(1) + m.group(2).upper(), text)
            
            # Remove leading/trailing whitespace
            text = text.strip()
            
            return text
            
        except Exception as e:
            logger.error(f"Error processing text: {str(e)}")
            return text 