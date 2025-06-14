import os
import logging
import numpy as np
from pathlib import Path
from faster_whisper import WhisperModel
import torch
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union
import json
import time
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
import gc
import requests
import librosa

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('transcriber.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class AudioSegment:
    """Class for storing audio segment information"""
    data: np.ndarray
    start_time: float
    end_time: float
    context: Optional[np.ndarray] = None

class OllamaProcessor:
    def __init__(self, model_name: str = "gemma2:9b"):
        """Initialize Ollama processor for context-aware analysis"""
        self.available_models = {
            "gemma2:9b": "Gemma 2 9B - Model mạnh nhất, phù hợp cho phân tích phức tạp",
            "deepseek-r1:7b": "DeepSeek R1 7B - Model tốt cho phân tích ngôn ngữ",
            "mistral:7b-instruct": "Mistral 7B Instruct - Model cân bằng giữa hiệu suất và tốc độ",
            "llama3.2:3b": "Llama 3.2 3B - Model nhẹ, phù hợp cho xử lý nhanh"
        }
        
        if model_name not in self.available_models:
            logger.warning(f"Model {model_name} không có sẵn. Sử dụng model mặc định: gemma2:9b")
            model_name = "gemma2:9b"
            
        self.model_name = model_name
        self.api_url = "http://localhost:11434/api/generate"
        logger.info(f"Initialized Ollama processor with model: {model_name}")
        
    def get_available_models(self) -> dict:
        """Get list of available models and their descriptions"""
        return self.available_models
        
    def set_model(self, model_name: str) -> bool:
        """Set the model to use for analysis"""
        if model_name in self.available_models:
            self.model_name = model_name
            logger.info(f"Changed model to: {model_name}")
            return True
        logger.warning(f"Model {model_name} không có sẵn")
        return False
        
    def ensure_analysis_fields(self, result: dict) -> dict:
        # Danh sách các trường chính cần có
        fields = [
            'entities', 'relationships', 'actions', 'offers', 'decisions',
            'risk', 'insight', 'notes', 'slang_detected', 'hidden_relationships',
            'sentiment', 'key_points', 'summary', 'context', 'details', 'privacy_summary'
        ]
        for field in fields:
            if field not in result or result[field] is None:
                # Mặc định: mảng rỗng cho các trường dạng list, chuỗi rỗng cho string
                if field in ['notes', 'slang_detected', 'sentiment', 'summary', 'privacy_summary']:
                    result[field] = ''
                else:
                    result[field] = []
        # Nếu tất cả trường chính đều rỗng, thêm insight mặc định
        if all(not result[f] for f in ['entities', 'relationships', 'actions', 'risk', 'insight']):
            result['insight'] = ['Không phát hiện thông tin đáng chú ý.']
        return result

    def analyze_context(self, text: str) -> dict:
        """Analyze conversation context using Ollama. Luôn phân tích sâu nghiệp vụ, insight, mối quan hệ, hành động, quyết định, dấu hiệu bất thường, nguy cơ, hành vi nghi vấn..."""
        try:
            # Lấy danh sách model tốt nhất đang chạy trên Ollama
            import subprocess
            try:
                proc = subprocess.run(["ollama", "list"], capture_output=True, text=True)
                models = [line.split()[0] for line in proc.stdout.splitlines() if line.strip() and not line.startswith("NAME")]
            except Exception:
                models = []
            priority = ["gemma2:9b", "deepseek-r1:7b", "mistral:7b-instruct", "llama3.2:3b"]
            model_name = next((m for m in priority if m in models), "gemma2:9b")
            self.model_name = model_name

            # Prompt mặc định: tổng quát + nghiệp vụ công an + hướng dẫn cho trường hợp không insight, tiếng lóng, mật ngữ
            prompt = f"""
Bạn là một trợ lý AI chuyên phân tích, trích xuất và trực quan hóa thông tin sâu từ hội thoại (phục vụ cả nghiệp vụ công an lẫn phân tích tổng quát). Hãy phân tích hội thoại sau và trích xuất các thông tin một cách chi tiết, chính xác, tập trung vào:
- Thực thể: người, tổ chức, địa điểm, thời gian, phương tiện, số điện thoại, email, CCCD, tài sản, đối tượng liên quan...
- Mối quan hệ giữa các thực thể (ai làm gì với ai, ai liên quan ai, ai nhận ưu đãi, ai ra quyết định, ai thực hiện hành động...)
- Sự kiện, hành động, quyết định, ưu đãi, cảm xúc, thông tin nhạy cảm
- Ngữ cảnh nghiệp vụ: mục đích, động cơ, dấu hiệu bất thường, hành vi nghi vấn, rủi ro, vi phạm, dấu hiệu phạm tội...
- Insight nghiệp vụ: các điểm then chốt, bất thường, nguy cơ, mối liên hệ ẩn, chuỗi sự kiện quan trọng

{text}

Hãy trả về kết quả dưới dạng JSON với cấu trúc sau:
{{
  "summary": "Tóm tắt ngắn gọn cuộc hội thoại, tập trung vào thông tin quan trọng nhất và mối quan hệ giữa các thông tin",
  "key_points": [
    "Các điểm chính được đề cập trong cuộc hội thoại",
    "Các thông tin quan trọng về yêu cầu, mục đích hoặc vấn đề",
    "Các quyết định hoặc thỏa thuận quan trọng"
  ],
  "entities": {{
    "people": [{{
      "name": "Tên đầy đủ của người được đề cập",
      "role": "Vai trò hoặc mối quan hệ trong cuộc hội thoại",
      "is_sensitive": "Đánh dấu nếu là thông tin nhạy cảm (true/false)",
      "sensitivity_reason": "Lý do nếu là thông tin nhạy cảm",
      "context": "Ngữ cảnh xuất hiện của người này trong cuộc hội thoại"
    }}],
    "locations": [{{
      "name": "Tên địa điểm",
      "type": "Loại địa điểm (nhà riêng/công ty/cơ quan...)",
      "address": "Địa chỉ chi tiết nếu có",
      "is_sensitive": "Đánh dấu nếu là địa điểm nhạy cảm (true/false)",
      "sensitivity_reason": "Lý do nếu là địa điểm nhạy cảm",
      "context": "Ngữ cảnh xuất hiện của địa điểm này trong cuộc hội thoại"
    }}],
    "time": [{{
      "value": "Thời gian cụ thể",
      "type": "Loại thời gian (hẹn/lịch trình/deadline...)",
      "is_sensitive": "Đánh dấu nếu là thời gian nhạy cảm (true/false)",
      "sensitivity_reason": "Lý do nếu là thời gian nhạy cảm",
      "context": "Ngữ cảnh xuất hiện của thời gian này trong cuộc hội thoại"
    }}],
    "contact": {{
      "phone": {{
        "value": "Số điện thoại nếu có",
        "is_sensitive": "Đánh dấu nếu là số điện thoại nhạy cảm (true/false)",
        "sensitivity_reason": "Lý do nếu là số điện thoại nhạy cảm",
        "context": "Ngữ cảnh xuất hiện của số điện thoại này trong cuộc hội thoại"
      }},
      "email": {{
        "value": "Email nếu có",
        "is_sensitive": "Đánh dấu nếu là email nhạy cảm (true/false)",
        "sensitivity_reason": "Lý do nếu là email nhạy cảm",
        "context": "Ngữ cảnh xuất hiện của email này trong cuộc hội thoại"
      }},
      "id": {{
        "value": "Số định danh nếu có",
        "type": "Loại định danh (CCCD/CMND/hộ chiếu...)",
        "is_sensitive": "Đánh dấu nếu là định danh nhạy cảm (true/false)",
        "sensitivity_reason": "Lý do nếu là định danh nhạy cảm",
        "context": "Ngữ cảnh xuất hiện của định danh này trong cuộc hội thoại"
      }}
    }}
  }},
  "context": {{
    "topic": "Chủ đề chính của cuộc hội thoại",
    "purpose": "Mục đích của cuộc hội thoại",
    "tone": "Giọng điệu của cuộc hội thoại (formal/informal/business/casual)",
    "domain": "Lĩnh vực liên quan (nếu có thể xác định)",
    "privacy_level": "Mức độ bảo mật của cuộc hội thoại (public/private/confidential)",
    "relationships": "Mối quan hệ giữa các thông tin trong cuộc hội thoại"
  }},
  "details": {{
    "requirements": [{{
      "content": "Nội dung yêu cầu",
      "is_sensitive": "Đánh dấu nếu là yêu cầu nhạy cảm (true/false)",
      "sensitivity_reason": "Lý do nếu là yêu cầu nhạy cảm",
      "context": "Ngữ cảnh xuất hiện của yêu cầu này trong cuộc hội thoại"
    }}],
    "decisions": [{{
      "content": "Nội dung quyết định",
      "is_sensitive": "Đánh dấu nếu là quyết định nhạy cảm (true/false)",
      "sensitivity_reason": "Lý do nếu là quyết định nhạy cảm",
      "context": "Ngữ cảnh xuất hiện của quyết định này trong cuộc hội thoại"
    }}],
    "actions": [{{
      "content": "Nội dung hành động",
      "is_sensitive": "Đánh dấu nếu là hành động nhạy cảm (true/false)",
      "sensitivity_reason": "Lý do nếu là hành động nhạy cảm",
      "context": "Ngữ cảnh xuất hiện của hành động này trong cuộc hội thoại"
    }}]
  }},
  "sentiment": "Cảm xúc chung của cuộc hội thoại (positive/negative/neutral)",
  "notes": "Các ghi chú đặc biệt hoặc thông tin bổ sung quan trọng",
  "privacy_summary": "Tóm tắt về các thông tin nhạy cảm được đề cập và mức độ bảo mật cần thiết"
}}

Lưu ý:
- Nếu hội thoại không có insight, các trường liên quan để trống hoặc ghi rõ "không có".
- Nếu phát hiện hội thoại dùng tiếng lóng, mật ngữ, hoặc có dấu hiệu bất thường, hãy đánh dấu rõ, giải thích hoặc cảnh báo trong các trường thích hợp (notes, key_points, risk, ...).
- Luôn phân tích sâu, kể cả khi hội thoại tưởng như bình thường.
- Chỉ trả về JSON, không thêm text khác.
"""

            response = requests.post(
                self.api_url,
                json={
                    "model": self.model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.2,
                        "top_p": 0.9,
                        "top_k": 40,
                        "num_ctx": 4096
                    }
                }
            )
            if response.status_code == 200:
                result = response.json()
                try:
                    analysis = json.loads(result["response"])
                    analysis = self.ensure_analysis_fields(analysis)
                    return analysis
                except json.JSONDecodeError:
                    return {"summary": result["response"], "error": "JSON parse error"}
            else:
                raise Exception(f"Ollama API error: {response.status_code}")
        except Exception as e:
            logger.error(f"Error analyzing context with Ollama: {str(e)}")
            return {"summary": "Không thể phân tích ngữ cảnh", "error": str(e)}

class Transcriber:
    def __init__(self, model_name: str = "large"):
        """Initialize transcriber with specified model"""
        try:
            # Use the correct model path in snapshots directory
            model_path = Path("models") / "models--guillaumekln--faster-whisper-large-v2" / "snapshots" / "f541c54c566e32dc1fbce16f98df699208837e8b"
            logger.info(f"Loading Whisper model from {model_path}")
            if not model_path.exists():
                raise RuntimeError(f"Model directory not found: {model_path}")
                
            self.model = WhisperModel(
                str(model_path),
                device="cpu",
                compute_type="int8"
            )
            
            # Initialize parameters
            self.device = "cpu"
            self.context_window = 5  # seconds of context
            self.min_segment_length = 10  # minimum segment length in seconds
            self.max_segment_length = 30  # maximum segment length in seconds
            self.overlap = 0.5  # overlap between segments (0-1)
            
            # Audio processing parameters
            self.min_silence_len = 1000  # ms
            self.silence_thresh = -40  # dB
            self.keep_silence = 100  # ms
            
            # Initialize LLM processor
            self.llm_processor = OllamaProcessor()
            
            logger.info("Model loaded successfully")
            
        except Exception as e:
            logger.error(f"Error initializing transcriber: {str(e)}")
            raise RuntimeError(f"Failed to load model: {str(e)}")
    
    def _load_audio(self, audio_path: str) -> Tuple[np.ndarray, int]:
        """Load and preprocess audio file"""
        try:
            audio, sr = librosa.load(audio_path, sr=16000)
            return audio, sr
        except Exception as e:
            logger.error(f"Error loading audio: {str(e)}")
            raise
    
    def _detect_silence(self, audio: np.ndarray, sr: int = 16000) -> List[Tuple[float, float]]:
        """Detect silence segments in audio"""
        try:
            # Calculate RMS energy
            rms = librosa.feature.rms(y=audio)[0]
            # Convert to dB
            db = 20 * np.log10(rms + 1e-10)
            
            # Find silence segments
            is_silence = db < self.silence_thresh
            silence_segments = []
            
            start = None
            for i, silent in enumerate(is_silence):
                if silent and start is None:
                    start = i
                elif not silent and start is not None:
                    end = i
                    duration = (end - start) * 512 / sr  # Convert frames to seconds
                    if duration >= self.min_silence_len / 1000:
                        silence_segments.append((start * 512 / sr, end * 512 / sr))
                    start = None
            
            return silence_segments
            
        except Exception as e:
            logger.error(f"Error detecting silence: {str(e)}")
            return []
    
    def _segment_audio(self, audio: np.ndarray, sr: int = 16000) -> List[AudioSegment]:
        """Segment audio into chunks based on silence detection and context"""
        try:
            silence_segments = self._detect_silence(audio, sr)
            segments = []
            
            if not silence_segments:
                # If no silence detected, split into fixed-length segments
                segment_length = self.max_segment_length * sr
                for i in range(0, len(audio), int(segment_length * (1 - self.overlap))):
                    end = min(i + segment_length, len(audio))
                    if end - i >= self.min_segment_length * sr:
                        # Add context from previous segment
                        context = None
                        if segments:
                            prev_segment = segments[-1]
                            context_start = max(0, int((prev_segment.end_time - self.context_window) * sr))
                            context = audio[context_start:i]
                        
                        segments.append(AudioSegment(
                            data=audio[i:end],
                            start_time=i/sr,
                            end_time=end/sr,
                            context=context
                        ))
            else:
                # Use silence segments to split audio
                start = 0
                for silence_start, silence_end in silence_segments:
                    if silence_start - start >= self.min_segment_length:
                        # Add context from previous segment
                        context = None
                        if segments:
                            prev_segment = segments[-1]
                            context_start = max(0, int((prev_segment.end_time - self.context_window) * sr))
                            context = audio[context_start:int(start*sr)]
                        
                        segments.append(AudioSegment(
                            data=audio[int(start*sr):int(silence_start*sr)],
                            start_time=start,
                            end_time=silence_start,
                            context=context
                        ))
                    start = silence_end
                
                # Add remaining audio
                if start < len(audio)/sr:
                    segments.append(AudioSegment(
                        data=audio[int(start*sr):],
                        start_time=start,
                        end_time=len(audio)/sr
                    ))
            
            return segments
            
        except Exception as e:
            logger.error(f"Error segmenting audio: {str(e)}")
            return []
    
    def _process_segment(self, segment: AudioSegment) -> str:
        """Process a single audio segment"""
        try:
            # Combine context and segment if available
            if segment.context is not None:
                audio = np.concatenate([segment.context, segment.data])
            else:
                audio = segment.data
            
            # Transcribe segment
            segments, info = self.model.transcribe(
                audio,
                language="vi",
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                    speech_pad_ms=100
                )
            )
            
            # Combine segment results
            text = " ".join([s.text for s in segments])
            
            return text
            
        except Exception as e:
            logger.error(f"Error processing segment: {str(e)}")
            return ""
    
    def _post_process_text(self, text: str) -> str:
        """Post-process transcribed text"""
        try:
            # Remove extra whitespace
            text = " ".join(text.split())
            
            # Remove multiple spaces
            text = " ".join(text.split())
            
            return text
            
        except Exception as e:
            logger.error(f"Error post-processing text: {str(e)}")
            return text
    
    def transcribe(self, audio_path: str, batch_size: int = 4) -> dict:
        """Transcribe audio file to text with parallel processing and context analysis"""
        try:
            start_time = time.time()
            
            # Load audio
            audio, sr = self._load_audio(audio_path)
            duration = len(audio) / sr
            
            # Segment audio
            segments = self._segment_audio(audio, sr)
            
            # Process segments in parallel
            with ThreadPoolExecutor(max_workers=min(batch_size, 8)) as executor:
                futures = []
                for segment in segments:
                    future = executor.submit(self._process_segment, segment)
                    futures.append(future)
            
            # Collect results
            results = []
            for future in futures:
                result = future.result()
                if result:
                    results.append(result)
            
            # Combine results
            text = " ".join(results)
            
            # Post-process text
            text = self._post_process_text(text)
            
            # Phân tích ngữ cảnh bằng Ollama
            context_analysis = self.llm_processor.analyze_context(text)
            
            # Tóm tắt nội dung (nếu có summarizer)
            summary = ""
            if hasattr(self, "summarizer") and self.summarizer:
                try:
                    summary = self.summarizer.summarize(text, context=context_analysis)
                except Exception as e:
                    logger.error(f"Error summarizing: {e}")
                    summary = ""
            
            # Calculate confidence (simple heuristic)
            confidence = min(1.0, len(text) / (duration * 10))  # Assume 10 chars per second is good
            
            # Clean up
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            # Trả về đúng schema chuẩn
            return {
                "transcription": text,
                "summary": summary,
                "context_analysis": context_analysis,
                "confidence": confidence,
                "duration": duration,
                "language": "vi",
                "processing_time": time.time() - start_time
            }
            
        except Exception as e:
            logger.error(f"Error transcribing audio: {str(e)}")
            raise 