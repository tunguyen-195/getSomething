from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
import torch
from typing import Optional, Union, List
import logging
from pathlib import Path
from transformers import T5ForConditionalGeneration, T5Tokenizer
import re
import unicodedata
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Summarizer:
    def __init__(self, model_name: str = "google/mt5-base"):
        """
        Initialize summarizer with T5/BART model
        Args:
            model_name: Name of model to use
        """
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        # Chọn model path đúng
        if "bart" in model_name:
            model_path = Path("models") / "bart-large-cnn"
        elif "t5" in model_name or "mt5" in model_name:
            model_path = Path("models") / "t5-base"
        else:
            model_path = None
        # Ưu tiên load local nếu có, nếu không thì tải về
        if model_path and model_path.exists():
            logger.info(f"Loading model from {model_path}")
            if "bart" in model_name:
                from transformers import BartForConditionalGeneration, BartTokenizer
                self.model = BartForConditionalGeneration.from_pretrained(str(model_path))
                self.tokenizer = BartTokenizer.from_pretrained(str(model_path))
            else:
                self.model = T5ForConditionalGeneration.from_pretrained(str(model_path))
                self.tokenizer = T5Tokenizer.from_pretrained(str(model_path))
        else:
            logger.info(f"Downloading model: {model_name}")
            if "bart" in model_name:
                from transformers import BartForConditionalGeneration, BartTokenizer
                self.model = BartForConditionalGeneration.from_pretrained(model_name)
                self.tokenizer = BartTokenizer.from_pretrained(model_name)
            else:
                self.model = T5ForConditionalGeneration.from_pretrained(model_name)
                self.tokenizer = T5Tokenizer.from_pretrained(model_name)
            # Save model locally nếu là model phổ biến
            if model_path:
                model_path.mkdir(parents=True, exist_ok=True)
                self.model.save_pretrained(str(model_path))
                self.tokenizer.save_pretrained(str(model_path))
                logger.info(f"Saved model to {model_path}")
        self.model.to(self.device)
        
    def normalize_text(self, text: str) -> str:
        """
        Normalize text by removing extra spaces, standardizing punctuation
        and fixing basic spelling errors
        
        Args:
            text: Input text
            
        Returns:
            Normalized text
        """
        # Remove extra spaces
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Standardize punctuation
        text = re.sub(r'([.,!?])\s*', r'\1 ', text)
        text = re.sub(r'\s+([.,!?])', r'\1', text)
        
        # Fix common Vietnamese spelling errors
        text = text.replace('không', 'không')
        text = text.replace('được', 'được')
        
        return text
        
    def improve_structure(self, text: str) -> str:
        """
        Improve text structure by ensuring complete sentences
        and logical flow
        
        Args:
            text: Input text
            
        Returns:
            Improved text
        """
        # Split into sentences
        sentences = re.split(r'([.!?])\s+', text)
        
        # Process each sentence
        improved_sentences = []
        for i in range(0, len(sentences), 2):
            if i + 1 < len(sentences):
                sentence = sentences[i] + sentences[i+1]
            else:
                sentence = sentences[i]
                
            # Add connecting words if needed
            if i > 0 and not any(sentence.startswith(w) for w in ['Vì', 'Do', 'Tuy', 'Mặc dù']):
                sentence = 'Ngoài ra, ' + sentence
                
            improved_sentences.append(sentence)
            
        return ' '.join(improved_sentences)
        
    def optimize_context(self, text: str) -> str:
        """
        Optimize context by handling references and ensuring consistency
        
        Args:
            text: Input text
            
        Returns:
            Context-optimized text
        """
        # Replace ambiguous pronouns
        text = re.sub(r'\b(họ|hắn|cô ấy|anh ấy)\b', 'người đó', text)
        
        # Remove redundant information
        sentences = text.split('. ')
        unique_sentences = []
        for sentence in sentences:
            if not any(similar(sentence, s) for s in unique_sentences):
                unique_sentences.append(sentence)
                
        return '. '.join(unique_sentences)
        
    def summarize(self, text: str, context: dict = None, max_length: int = 150, min_length: int = 50) -> str:
        """
        Summarize text using T5 model with post-processing and context
        Args:
            text: Text to summarize
            context: Context analysis dict (from transcriber)
            max_length: Maximum length of summary
            min_length: Minimum length of summary
        Returns:
            Summarized text
        """
        try:
            # Build context-rich prompt if context is provided
            if context:
                prompt = f"Tóm tắt nội dung hội thoại dưới đây, tập trung vào các thông tin quan trọng, các thực thể, mối quan hệ, mức độ nhạy cảm và ngữ cảnh.\n"
                if 'summary' in context:
                    prompt += f"\nTóm tắt ngữ cảnh: {context['summary']}"
                if 'key_points' in context and context['key_points']:
                    prompt += f"\nCác điểm chính: {', '.join(context['key_points'])}"
                if 'entities' in context and context['entities']:
                    prompt += f"\nThực thể: {json.dumps(context['entities'], ensure_ascii=False)}"
                if 'privacy_summary' in context:
                    prompt += f"\nThông tin nhạy cảm: {context['privacy_summary']}"
                prompt += f"\nNội dung hội thoại: {text}"
                input_text = prompt
            else:
                input_text = f"summarize: {text}"
            inputs = self.tokenizer.encode(
                input_text,
                max_length=1024,
                truncation=True,
                return_tensors="pt"
            ).to(self.device)
            
            # Generate summary
            summary_ids = self.model.generate(
                inputs,
                max_length=max_length,
                min_length=min_length,
                num_beams=4,
                length_penalty=2.0,
                early_stopping=True,
                no_repeat_ngram_size=3
            )
            
            # Decode summary
            summary = self.tokenizer.decode(summary_ids[0], skip_special_tokens=True)
            
            # Remove <extra_id_*> tokens if present
            summary = re.sub(r'<extra_id_\d+>', '', summary)
            
            # Apply post-processing
            summary = self.normalize_text(summary)
            summary = self.improve_structure(summary)
            summary = self.optimize_context(summary)
            
            return summary
            
        except Exception as e:
            logger.error(f"Error generating summary: {str(e)}")
            return text  # Return original text if summarization fails
    
    def summarize_segments(self,
                          segments: List[str],
                          max_length: Optional[int] = None,
                          min_length: Optional[int] = None,
                          **kwargs) -> List[str]:
        """
        Generate summaries for multiple text segments
        
        Args:
            segments: List of text segments to summarize
            max_length: Maximum length of each summary
            min_length: Minimum length of each summary
            **kwargs: Additional arguments for model generation
            
        Returns:
            List of generated summaries
        """
        summaries = []
        for segment in segments:
            summary = self.summarize(
                segment,
                max_length=max_length,
                min_length=min_length,
                **kwargs
            )
            summaries.append(summary)
        return summaries
    
    def save_model(self, path: Union[str, Path]):
        """
        Save model and tokenizer to specified path
        
        Args:
            path: Path to save model and tokenizer
        """
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        
        self.model.save_pretrained(path)
        self.tokenizer.save_pretrained(path)
        logger.info(f"Model saved to {path}")
    
    @classmethod
    def from_pretrained(cls,
                       path: Union[str, Path],
                       device: str = "cuda",
                       **kwargs) -> 'Summarizer':
        """
        Load model from pretrained path
        
        Args:
            path: Path to pretrained model
            device: Device to run model on
            **kwargs: Additional arguments for model initialization
            
        Returns:
            Initialized Summarizer instance
        """
        path = Path(path)
        if not path.exists():
            raise ValueError(f"Model path does not exist: {path}")
            
        return cls(
            model_name=str(path),
            device=device,
            **kwargs
        ) 