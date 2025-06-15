import logging
# Configure logging sớm để logger luôn có sẵn
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('transcriber.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

import os
import numpy as np
from pathlib import Path
from faster_whisper import WhisperModel, BatchedInferencePipeline
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
from src.audio_processing.processor import AudioProcessor

# Thêm import đúng cho pipeline diarization
try:
    from pyannote.audio import Pipeline
except ImportError:
    Pipeline = None

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
        fields = [
            'entities', 'relationships', 'actions', 'offers', 'decisions',
            'risk', 'insight', 'notes', 'slang_detected', 'hidden_relationships',
            'sentiment', 'key_points', 'summary', 'context', 'details', 'privacy_summary'
        ]
        for field in fields:
            if field not in result or result[field] is None:
                if field in ['notes', 'slang_detected', 'sentiment', 'summary', 'privacy_summary']:
                    result[field] = ''
                else:
                    result[field] = []
        # Fallback insight nếu không có insight
        if not result['insight']:
            result['insight'] = [
                'Không phát hiện thông tin đáng chú ý. Lý do: hội thoại thiếu dữ liệu, nội dung không rõ ràng, hoặc chất lượng âm thanh thấp. Đề xuất: thu thập thêm dữ liệu hoặc kiểm tra lại bản ghi.'
            ]
        # Giải thích lý do nếu các trường chính rỗng
        if not result['entities']:
            result['entities_reason'] = 'Không phát hiện thực thể do hội thoại không đề cập cụ thể hoặc chất lượng âm thanh thấp.'
        if not result['relationships']:
            result['relationships_reason'] = 'Không phát hiện mối quan hệ do hội thoại không có thông tin liên kết rõ ràng.'
        if not result['actions']:
            result['actions_reason'] = 'Không phát hiện hành động cụ thể trong hội thoại.'
        # Nếu tất cả trường chính đều rỗng, insight mặc định
        if all(not result[f] for f in ['entities', 'relationships', 'actions', 'risk', 'insight']):
            result['insight'] = ['Không phát hiện thông tin đáng chú ý. Lý do: hội thoại thiếu dữ liệu, nội dung không rõ ràng, hoặc chất lượng âm thanh thấp. Đề xuất: thu thập thêm dữ liệu hoặc kiểm tra lại bản ghi.']
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
            return {}

    def visualize_context(self, text: str) -> dict:
        """Phân tích hội thoại để trả về dữ liệu phù hợp cho trực quan hóa (graph, timeline, entity map...)."""
        import re
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

            prompt = f"""
Bạn là AI chuyên trực quan hóa hội thoại. Hãy trích xuất các thành phần sau từ hội thoại:
- nodes: danh sách thực thể (người, tổ chức, địa điểm, sự kiện, ...)
- edges: mối quan hệ giữa các thực thể (ai liên hệ ai, ai thực hiện hành động gì với ai, ...)
- timeline: các mốc thời gian, sự kiện chính
- entity_types: loại thực thể (person, org, location, event, ...)
- main_events: danh sách sự kiện chính

Chỉ trả về object JSON với các trường trên, không bọc trong markdown, không thêm ```json.

Hội thoại:
{text}
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
                except json.JSONDecodeError:
                    match = re.search(r"```(?:json)?\\n([\s\S]*?)```", result["response"], re.DOTALL)
                    if match:
                        json_str = match.group(1)
                        try:
                            analysis = json.loads(json_str)
                        except Exception:
                            analysis = {"error": "JSON parse error", "raw": result["response"]}
                    else:
                        analysis = {"error": "JSON parse error", "raw": result["response"]}
                # --- Bắt đầu enrich kết quả cho trực quan hóa ---
                # timeline
                if "timeline" not in analysis or not isinstance(analysis["timeline"], list):
                    timeline = []
                    if "events" in analysis and isinstance(analysis["events"], list):
                        for ev in analysis["events"]:
                            timeline.append({"time": ev.get("time"), "description": ev.get("description") or ev.get("action") or ev.get("event")})
                    elif "entities" in analysis and isinstance(analysis["entities"], dict) and "time" in analysis["entities"]:
                        for t in analysis["entities"]["time"]:
                            timeline.append({"time": t.get("value"), "description": t.get("context")})
                    analysis["timeline"] = timeline
                # nodes
                if "nodes" not in analysis or not isinstance(analysis["nodes"], list):
                    nodes = []
                    ents = analysis.get("entities", {})
                    if "people" in ents:
                        for p in ents["people"]:
                            nodes.append({"id": p.get("name"), "type": "person", "label": p.get("name"), "context": p.get("context"), "is_sensitive": p.get("is_sensitive")})
                    if "locations" in ents:
                        for l in ents["locations"]:
                            nodes.append({"id": l.get("name"), "type": "location", "label": l.get("name"), "context": l.get("context"), "is_sensitive": l.get("is_sensitive")})
                    if "time" in ents:
                        for t in ents["time"]:
                            nodes.append({"id": t.get("value"), "type": "time", "label": t.get("value"), "context": t.get("context"), "is_sensitive": t.get("is_sensitive")})
                    if "contact" in ents:
                        for k in ["phone", "email", "id"]:
                            c = ents["contact"].get(k)
                            if c and c.get("value"):
                                nodes.append({"id": c["value"], "type": k, "label": c["value"], "context": c.get("context"), "is_sensitive": c.get("is_sensitive")})
                    # events as nodes
                    if "events" in analysis and isinstance(analysis["events"], list):
                        for ev in analysis["events"]:
                            nodes.append({"id": ev.get("description") or ev.get("event"), "type": "event", "label": ev.get("description") or ev.get("event"), "context": ev.get("time")})
                    analysis["nodes"] = nodes
                # edges
                if "edges" not in analysis or not isinstance(analysis["edges"], list):
                    edges = []
                    if "relationships" in analysis and isinstance(analysis["relationships"], list):
                        for r in analysis["relationships"]:
                            edges.append({"source": r.get("source"), "target": r.get("target"), "label": r.get("label") or r.get("type"), "context": r.get("context")})
                    analysis["edges"] = edges
                # entity_types
                if "entity_types" not in analysis or not isinstance(analysis["entity_types"], list):
                    types = set()
                    for n in analysis.get("nodes", []):
                        if n.get("type"): types.add(n["type"])
                    analysis["entity_types"] = list(types)
                # main_events
                if "main_events" not in analysis or not isinstance(analysis["main_events"], list):
                    main_events = []
                    if "events" in analysis and isinstance(analysis["events"], list):
                        for ev in analysis["events"]:
                            main_events.append(ev.get("description") or ev.get("event"))
                    elif "timeline" in analysis:
                        for t in analysis["timeline"]:
                            main_events.append(t.get("description"))
                    analysis["main_events"] = main_events
                # Đảm bảo luôn trả về đủ các trường
                for k in ["timeline", "nodes", "edges", "entity_types", "main_events"]:
                    if k not in analysis:
                        analysis[k] = []
                logger.info(f"[visualize_context] Final analysis: {analysis}")
                return analysis
            else:
                raise Exception(f"Ollama API error: {response.status_code}")
        except Exception as e:
            logger.error(f"Error visualizing context with Ollama: {str(e)}")
            return {}

class Transcriber:
    def __init__(self, model_name: str = "large", device: str = None, compute_type: str = None, batch_size: int = None, beam_size: int = None,
                 min_segment_length: int = None, max_segment_length: int = None, context_window: int = None, overlap: float = None, silence_thresh: float = None, min_silence_len: int = None):
        # Lấy config từ biến môi trường hoặc config file nếu không truyền vào
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if compute_type is None:
            if device == "cuda":
                compute_type = "float16"
            else:
                compute_type = "int8"
        if device == "cpu" and torch.cuda.is_available():
            import logging
            logging.warning("Có GPU nhưng pipeline vẫn chạy trên CPU! Kiểm tra lại config hoặc biến môi trường.")
        if batch_size is None:
            batch_size = int(os.environ.get("WHISPER_BATCH_SIZE", "8" if device=="cuda" else "4"))
        if beam_size is None:
            beam_size = int(os.environ.get("WHISPER_BEAM_SIZE", "5"))
        self.device = device
        self.compute_type = compute_type
        self.batch_size = batch_size
        self.beam_size = beam_size
        logger.info(f"Init WhisperModel with device={device}, compute_type={compute_type}, batch_size={batch_size}, beam_size={beam_size}")
        self.asr_priority = [
            ("large-v2", "models/models--guillaumekln--faster-whisper-large-v2/snapshots/"),
            ("large-v3", "models/models--guillaumekln--faster-whisper-large-v3/snapshots/"),
            ("medium", "models/models--guillaumekln--faster-whisper-medium-v2/snapshots/"),
            ("small", "models/models--guillaumekln--faster-whisper-small-v2/snapshots/"),
            ("tiny", "models/models--guillaumekln--faster-whisper-tiny-v2/snapshots/")
        ]
        self.model = None
        self.model_name = None
        for name, path_prefix in self.asr_priority:
            model_dir = Path(path_prefix)
            if model_dir.exists() and any(model_dir.iterdir()):
                hash_dirs = [d for d in model_dir.iterdir() if d.is_dir() and len(d.name) == 40]
                model_path = None
                for d in hash_dirs:
                    if (d / "model.bin").exists():
                        model_path = d
                        break
                if model_path:
                    try:
                        from faster_whisper import WhisperModel
                        self.model = WhisperModel(str(model_path), device=device, compute_type=compute_type)
                        self.model_name = name
                        logger.info(f"ASR: Sử dụng model offline {name} tại {model_path}")
                        break
                    except Exception as e:
                        logger.warning(f"Không load được model offline {name} tại {model_path}: {e}")
                        continue
        if self.model is None:
            logger.error("Không tìm thấy bất kỳ model ASR offline nào! Vui lòng tải model về thư mục models trước khi chạy.")
            raise RuntimeError("Không tìm thấy model ASR offline.")
        
        # Gán mặc định cho các biến segment instance nếu None, ép kiểu an toàn
        self.min_segment_length = int(min_segment_length) if min_segment_length is not None else 10
        self.max_segment_length = int(max_segment_length) if max_segment_length is not None else 30
        self.context_window = int(context_window) if context_window is not None else 5
        self.overlap = float(overlap) if overlap is not None else 0.5
        # Sau đó mới gọi _set_segmentation_params để đồng bộ lại
        self._set_segmentation_params(self.min_segment_length, self.max_segment_length, self.context_window, self.overlap)
        
        # Audio processing parameters
        self.min_silence_len = min_silence_len if min_silence_len is not None else 1000  # ms
        self.silence_thresh = silence_thresh if silence_thresh is not None else -40.0
        self.keep_silence = 100  # ms
        
        # Initialize LLM processor
        self.llm_processor = OllamaProcessor()
        
        self.speaker_pipeline = None
        if Pipeline is not None:
            try:
                hf_token = os.getenv('HUGGINGFACE_TOKEN', '')
                if not hf_token:
                    logger.warning('Chưa cấu hình biến môi trường HUGGINGFACE_TOKEN. Pyannote sẽ không thể tải pipeline từ HuggingFace. Vui lòng tạo token tại https://huggingface.co/settings/tokens và export HUGGINGFACE_TOKEN trước khi chạy.')
                self.speaker_pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization@2.1", use_auth_token=hf_token)
            except Exception as e:
                logger.warning(f'Không thể khởi tạo pyannote speaker pipeline: {e}. Nếu gặp lỗi 401 Unauthorized, hãy kiểm tra lại biến môi trường HUGGINGFACE_TOKEN. Xem hướng dẫn tại https://huggingface.co/pyannote/speaker-diarization.')
                self.speaker_pipeline = None
        
        if self.batch_size > 1:
            self.pipeline = BatchedInferencePipeline(model=self.model)
            logger.info(f"Dùng BatchedInferencePipeline với batch_size={self.batch_size}")
        else:
            self.pipeline = self.model
        
        self.audio_processor = AudioProcessor()
        
        logger.info(f"Model loaded successfully on device={self.device}, compute_type={self.compute_type}, batch_size={self.batch_size}, beam_size={self.beam_size}")
        
    def _set_segmentation_params(self, min_segment_length, max_segment_length, context_window, overlap):
        # Ưu tiên giá trị truyền vào, nếu None thì lấy từ instance, nếu vẫn None thì lấy mặc định, ép kiểu an toàn
        self.context_window = int(context_window) if context_window is not None else getattr(self, 'context_window', 5) or 5
        self.min_segment_length = int(min_segment_length) if min_segment_length is not None else getattr(self, 'min_segment_length', 10) or 10
        self.max_segment_length = int(max_segment_length) if max_segment_length is not None else getattr(self, 'max_segment_length', 30) or 30
        self.overlap = float(overlap) if overlap is not None else getattr(self, 'overlap', 0.5) or 0.5
        logger.info(f"Segmentation params: min_segment_length={self.min_segment_length}, max_segment_length={self.max_segment_length}, context_window={self.context_window}, overlap={self.overlap}")

    def _reload_model(self, model_path, device=None, compute_type=None):
        from faster_whisper import WhisperModel
        device = device or self.device
        compute_type = compute_type or self.compute_type
        self.model = WhisperModel(str(model_path), device=device, compute_type=compute_type)
        # Luôn gán lại segmentation params từ giá trị hiện tại của instance
        self._set_segmentation_params(
            self.min_segment_length,
            self.max_segment_length,
            self.context_window,
            self.overlap
        )
        if self.batch_size > 1:
            self.pipeline = BatchedInferencePipeline(model=self.model)
            logger.info(f"Dùng BatchedInferencePipeline với batch_size={self.batch_size}")
        else:
            self.pipeline = self.model
        logger.info(f"Reloaded model successfully on device={self.device}, compute_type={self.compute_type}, batch_size={self.batch_size}, beam_size={self.beam_size}")

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
            import logging
            logging.info(f"[SILENCE-THRESH] self.silence_thresh={self.silence_thresh}, self.min_silence_len={self.min_silence_len}")
            if self.silence_thresh is None:
                self.silence_thresh = -40.0
                logging.warning("self.silence_thresh bị None, gán mặc định -40.0")
            if self.min_silence_len is None:
                self.min_silence_len = 1000
                logging.warning("self.min_silence_len bị None, gán mặc định 1000")
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
        """Segment audio: truyền toàn bộ audio vào model, không tách đoạn theo silence. Nếu audio > 30 phút thì chia đều."""
        try:
            audio_len = len(audio) / sr
            max_segment_sec = 1800  # 30 phút
            segments = []
            if audio_len <= max_segment_sec:
                # Truyền toàn bộ audio vào model, không tách đoạn
                segments.append(AudioSegment(
                    data=audio,
                    start_time=0.0,
                    end_time=audio_len,
                    context=None
                ))
                logger.info(f"[SEGMENT-LOG] start=0.00s, end={audio_len:.2f}s (full audio, no split)")
            else:
                # Nếu quá lớn, chia đều thành các đoạn 30 phút
                samples_per_segment = int(max_segment_sec * sr)
                i = 0
                while i < len(audio):
                    end = min(i + samples_per_segment, len(audio))
                    segments.append(AudioSegment(
                        data=audio[i:end],
                        start_time=i/sr,
                        end_time=end/sr,
                        context=None
                    ))
                    logger.info(f"[SEGMENT-LOG] start={i/sr:.2f}s, end={end/sr:.2f}s (split 30min)")
                    i += samples_per_segment
            return segments
        except Exception as e:
            logger.error(f"Error segmenting audio: {str(e)}")
            return []
    
    def _process_segment(self, segment: AudioSegment) -> str:
        """Process a single audio segment"""
        try:
            if segment.data is None:
                logger.error(f"Lỗi segment: segment.data=None, segment={segment}")
                return ""
            if segment.context is not None and not isinstance(segment.context, np.ndarray):
                logger.warning(f"segment.context không phải ndarray: {type(segment.context)}")
            if segment.context is not None:
                audio = np.concatenate([segment.context, segment.data])
            else:
                audio = segment.data
            # Dùng pipeline.transcribe (có thể là batch hoặc single)
            segments, info = self.pipeline.transcribe(
                audio,
                language="vi",
                beam_size=self.beam_size,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                    speech_pad_ms=100
                )
            )
            if segments is None or info is None:
                logger.error(f"pipeline.transcribe trả về None: segments={segments}, info={info}")
                raise Exception(f"pipeline.transcribe trả về None: segments={segments}, info={info}")
            text = " ".join([s.text for s in segments if hasattr(s, 'text') and s.text])
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
    
    def _is_noisy(self, audio: np.ndarray) -> bool:
        """Phát hiện audio nhiễu (placeholder, cần tích hợp model thực tế)"""
        # TODO: Tích hợp model phát hiện nhiễu
        return False
    
    def transcribe(self, audio_path: str, batch_size: int = None) -> dict:
        """Transcribe audio file to text with parallel processing and context analysis"""
        try:
            start_time = time.time()
            
            asr_tried = []
            text = ""
            for name, path_prefix in self.asr_priority:
                try:
                    if self.model_name != name:
                        # Nếu chưa load model này, thử load
                        model_path = None
                        for p in Path(path_prefix).parent.glob(f"{path_prefix.split('/')[-2]}*"):
                            if p.is_dir():
                                model_path = p / "snapshots" / next(p.glob("snapshots/*"), None).name if any(p.glob("snapshots/*")) else None
                                break
                        if model_path and model_path.exists():
                            self._reload_model(
                                model_path,
                                device=self.device,
                                compute_type=self.compute_type
                            )
                            self.model_name = name
                            logger.info(f"ASR fallback: Sử dụng model {name} tại {model_path}")
                    # Load audio và nhận diện
                    audio, sr = self._load_audio(audio_path)
                    # Tự động enhance nếu phát hiện nhiễu hoặc tiếng lóng (placeholder)
                    if self._is_noisy(audio):
                        audio = self.audio_processor.enhance_speech_llase(audio)
                    # Segment audio
                    segments = self._segment_audio(audio, sr)
                    with ThreadPoolExecutor(max_workers=min(batch_size, 8)) as executor:
                        futures = []
                        for segment in segments:
                            future = executor.submit(self._process_segment, segment)
                            futures.append(future)
                    results = []
                    for future in futures:
                        result = future.result()
                        if result:
                            results.append(result)
                    text = " ".join(results)
                    text = self._post_process_text(text)
                    logger.info(f"ASR thành công với model {name}")
                    break
                except (ImportError, FileNotFoundError, RuntimeError) as e:
                    logger.warning(f"ASR lỗi khi load model {name}: {e}")
                    asr_tried.append(name)
                    continue
                except Exception as e:
                    logger.error(f"ASR lỗi nghiêm trọng với model {name}: {e}")
                    raise  # Không fallback nữa, raise luôn lỗi
            if not text:
                logger.error(f"Tất cả model ASR đều lỗi: {asr_tried}")
                return {"error": f"Không nhận diện được âm thanh. Đã thử các model: {asr_tried}"}
            
            # Phân tích ngữ cảnh bằng Ollama
            context_analysis = self.llm_processor.analyze_context(text)
            if not isinstance(context_analysis, dict):
                context_analysis = {}  # Luôn đảm bảo là dict
            
            # Tóm tắt nội dung (nếu có summarizer)
            summary = ""
            if hasattr(self, "summarizer") and self.summarizer:
                try:
                    summary = self.summarizer.summarize(text, context=context_analysis)
                except Exception as e:
                    logger.error(f"Error summarizing: {e}")
                    summary = ""
            
            # Calculate confidence (simple heuristic)
            audio, sr = self._load_audio(audio_path)
            duration = len(audio) / sr
            confidence = min(1.0, len(text) / (duration * 10))  # Assume 10 chars per second is good
            
            # Clean up
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            # Sau khi có transcript
            # emotion_result = self.analyze_emotion_sentiment_stress(text)
            
            # Trả về đúng schema chuẩn
            result = {
                "transcription": text,
                "analysis": context_analysis,
                "summary": summary,
                "confidence": confidence,
                "duration": duration,
                "language": "vi",
                "processing_time": time.time() - start_time
            }
            return result
            
        except Exception as e:
            logger.error(f"Error transcribing audio: {str(e)}")
            raise 