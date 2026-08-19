# Hướng Dẫn Nâng Cấp SpeechToInformation

So sánh với Cherry Core V2 và đề xuất cải tiến.

---

## Mục Lục

1. [Tổng Quan So Sánh](#1-tổng-quan-so-sánh)
2. [Kiến Trúc](#2-kiến-trúc)
3. [ASR (Speech-to-Text)](#3-asr-speech-to-text)
4. [Speaker Diarization](#4-speaker-diarization)
5. [Text Correction](#5-text-correction)
6. [LLM Integration](#6-llm-integration)
7. [Prompt Engineering](#7-prompt-engineering)
8. [Code Quality](#8-code-quality)
9. [Danh Sách Công Việc Ưu Tiên](#9-danh-sách-công-việc-ưu-tiên)

---

## 1. Tổng Quan So Sánh

| Tiêu chí | SpeechToInformation | Cherry Core V2 | Đánh giá |
|----------|---------------------|----------------|----------|
| **Kiến trúc** | Layered (Service-based) | Hexagonal (Ports & Adapters) | Cherry tốt hơn |
| **ASR Models** | faster-whisper (large-v3-turbo) | Whisper V2/V3, PhoWhisper | Cherry đa dạng hơn |
| **Anti-Hallucination** | Cơ bản | Toàn diện (BoH, Delooping) | Cherry tốt hơn |
| **Diarization** | pyannote, SimpleVAD | pyannote, SpeechBrain, VBx | Cherry tốt hơn |
| **Text Correction** | Không có | 3-stage (Phonetic + ProtonX + LLM) | Cherry tốt hơn |
| **Prompt Management** | Hardcoded strings | Jinja2 Templates + YAML | Cherry tốt hơn |
| **Frontend** | React + MUI (đầy đủ) | CLI only | SpeechToInfo tốt hơn |
| **API** | FastAPI + Celery | Không có API | SpeechToInfo tốt hơn |
| **Database** | PostgreSQL + SQLAlchemy | Không có | SpeechToInfo tốt hơn |
| **Offline Mode** | Có (với fallback) | Có (toàn bộ) | Tương đương |

---

## 2. Kiến Trúc

### Hiện Tại (SpeechToInformation)

```
src/
├── api/endpoints/      # FastAPI routes
├── services/           # Business logic (mixed)
├── speech_to_text/     # Transcription
├── audio_processing/   # Diarization
└── worker/tasks/       # Celery tasks
```

**Vấn đề:**
- Không có interface/port rõ ràng
- Khó swap implementation
- Coupling cao giữa các module

### Đề Xuất (Theo Cherry Core)

```
src/
├── core/
│   ├── domain/
│   │   └── entities.py           # Transcript, SpeakerSegment, Report
│   ├── ports/
│   │   ├── asr_port.py           # ITranscriber interface
│   │   ├── llm_port.py           # ILLMEngine interface
│   │   ├── diarization_port.py   # ISpeakerDiarizer interface
│   │   └── correction_port.py    # ITextCorrector interface
│   └── services/
│       ├── alignment_service.py
│       └── output_formatter.py
├── infrastructure/
│   ├── adapters/
│   │   ├── asr/
│   │   │   ├── faster_whisper_adapter.py
│   │   │   ├── phowhisper_adapter.py      # THÊM MỚI
│   │   │   └── hallucination_filter.py    # THÊM MỚI
│   │   ├── diarization/
│   │   │   ├── pyannote_adapter.py
│   │   │   ├── speechbrain_adapter.py     # THÊM MỚI
│   │   │   └── vbx_refiner.py             # THÊM MỚI
│   │   ├── llm/
│   │   │   ├── ollama_adapter.py
│   │   │   └── llamacpp_adapter.py
│   │   └── correction/
│   │       ├── phonetic_corrector.py      # THÊM MỚI
│   │       └── protonx_adapter.py         # THÊM MỚI
│   └── factories/
│       └── system_factory.py
├── application/
│   ├── use_cases/
│   │   ├── transcribe_audio.py
│   │   └── generate_report.py
│   └── services/
│       ├── transcription_service.py
│       └── analysis_service.py
├── api/                    # Giữ nguyên FastAPI
├── worker/                 # Giữ nguyên Celery
└── database/               # Giữ nguyên
```

### Code Mẫu: Port Interface

```python
# src/core/ports/asr_port.py
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from dataclasses import dataclass

@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    words: List[Dict[str, Any]] = None

@dataclass
class Transcript:
    text: str
    segments: List[TranscriptSegment]
    language: str
    metadata: Dict[str, Any] = None

class ITranscriber(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str, language: str = "vi") -> Transcript:
        """Transcribe audio file to text with timestamps."""
        pass
    
    @abstractmethod
    def load(self) -> bool:
        """Load model into memory."""
        pass
    
    @abstractmethod
    def unload(self) -> None:
        """Release model from memory."""
        pass
```

### Code Mẫu: System Factory

```python
# src/infrastructure/factories/system_factory.py
from src.core.ports.asr_port import ITranscriber
from src.core.ports.diarization_port import ISpeakerDiarizer
from src.core.ports.llm_port import ILLMEngine
from src.core.ports.correction_port import ITextCorrector

class SystemFactory:
    def __init__(self, config: Settings):
        self.config = config
    
    def create_transcriber(self, model: str = "faster-whisper") -> ITranscriber:
        if model == "faster-whisper":
            from src.infrastructure.adapters.asr.faster_whisper_adapter import FasterWhisperAdapter
            return FasterWhisperAdapter(self.config)
        elif model == "phowhisper":
            from src.infrastructure.adapters.asr.phowhisper_adapter import PhoWhisperAdapter
            return PhoWhisperAdapter(self.config)
        raise ValueError(f"Unknown ASR model: {model}")
    
    def create_diarizer(self, method: str = "pyannote") -> ISpeakerDiarizer:
        if method == "pyannote":
            from src.infrastructure.adapters.diarization.pyannote_adapter import PyannoteAdapter
            return PyannoteAdapter(self.config)
        elif method == "speechbrain":
            from src.infrastructure.adapters.diarization.speechbrain_adapter import SpeechBrainAdapter
            return SpeechBrainAdapter(self.config)
        raise ValueError(f"Unknown diarization method: {method}")
    
    def create_llm_engine(self) -> ILLMEngine:
        # Fallback pattern
        if self.config.USE_OLLAMA:
            from src.infrastructure.adapters.llm.ollama_adapter import OllamaAdapter
            adapter = OllamaAdapter(self.config)
            if adapter.load():
                return adapter
        # Fallback to llama.cpp
        from src.infrastructure.adapters.llm.llamacpp_adapter import LlamaCppAdapter
        return LlamaCppAdapter(self.config)
    
    def create_corrector(self) -> ITextCorrector:
        from src.infrastructure.adapters.correction.phonetic_corrector import PhoneticCorrector
        return PhoneticCorrector(self.config)
```

---

## 3. ASR (Speech-to-Text)

### Thiếu Sót Hiện Tại

1. **Không có PhoWhisper** - Model tối ưu cho tiếng Việt từ VinAI
2. **Anti-hallucination chưa đầy đủ** - Chỉ có cơ bản
3. **Không có Hallucination Filter** - Không lọc BoH (Bag of Hallucinations)

### Đề Xuất Thêm

#### 3.1. Thêm PhoWhisper Adapter

```python
# src/infrastructure/adapters/asr/phowhisper_adapter.py
from transformers import WhisperProcessor, WhisperForConditionalGeneration
import torch
import librosa

class PhoWhisperAdapter(ITranscriber):
    """VinAI PhoWhisper - Optimized for Vietnamese"""
    
    MODEL_ID = "vinai/PhoWhisper-large"
    
    def __init__(self, config):
        self.config = config
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self._model = None
        self._processor = None
    
    def load(self) -> bool:
        if self._model is None:
            self._processor = WhisperProcessor.from_pretrained(self.MODEL_ID)
            self._model = WhisperForConditionalGeneration.from_pretrained(
                self.MODEL_ID,
                torch_dtype=torch.float16 if self.device == "cuda" else torch.float32
            ).to(self.device)
        return True
    
    def transcribe(self, audio_path: str, language: str = "vi") -> Transcript:
        self.load()
        
        # Load audio
        audio, sr = librosa.load(audio_path, sr=16000)
        
        # Process
        inputs = self._processor(
            audio, 
            sampling_rate=16000, 
            return_tensors="pt"
        ).to(self.device)
        
        # Generate with anti-hallucination settings
        generated_ids = self._model.generate(
            inputs.input_features,
            max_length=448,
            num_beams=5,
            condition_on_prev_tokens=False,  # Anti-hallucination
            compression_ratio_threshold=2.0,
            no_speech_threshold=0.5,
        )
        
        text = self._processor.batch_decode(
            generated_ids, 
            skip_special_tokens=True
        )[0]
        
        return Transcript(text=text, segments=[], language="vi")
```

#### 3.2. Thêm Hallucination Filter

```python
# src/infrastructure/adapters/asr/hallucination_filter.py
import re
from typing import List

class HallucinationFilter:
    """Filter common ASR hallucinations for Vietnamese"""
    
    # Bag of Hallucinations (BoH) - Common hallucinated phrases
    BOH_PATTERNS = [
        r"Cảm ơn bạn đã xem video",
        r"Đăng ký kênh",
        r"Subscribe",
        r"Like và share",
        r"Hẹn gặp lại",
        r"Xin chào các bạn",
        r"Video này được tài trợ bởi",
        r"\.{3,}",  # Multiple dots
        r"(\w+\s*){1,3}\1{3,}",  # Repeated phrases
    ]
    
    # Delooping patterns
    LOOP_THRESHOLD = 3
    
    def __init__(self):
        self.boh_regex = [re.compile(p, re.IGNORECASE) for p in self.BOH_PATTERNS]
    
    def filter(self, text: str) -> str:
        """Remove hallucinations from transcribed text"""
        # Remove BoH patterns
        for pattern in self.boh_regex:
            text = pattern.sub("", text)
        
        # Deloop repeated phrases
        text = self._deloop(text)
        
        # Clean up extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def _deloop(self, text: str) -> str:
        """Remove repeated phrases (loops)"""
        words = text.split()
        if len(words) < 6:
            return text
        
        # Check for repeated n-grams (2-5 words)
        for n in range(2, 6):
            i = 0
            result = []
            while i < len(words):
                ngram = tuple(words[i:i+n])
                count = 1
                j = i + n
                while j + n <= len(words) and tuple(words[j:j+n]) == ngram:
                    count += 1
                    j += n
                
                if count >= self.LOOP_THRESHOLD:
                    # Keep only one instance
                    result.extend(ngram)
                    i = j
                else:
                    result.append(words[i])
                    i += 1
            words = result
        
        return ' '.join(words)
```

#### 3.3. Cập Nhật Transcriber Hiện Tại

Thêm vào `src/speech_to_text/transcriber.py`:

```python
# Thêm anti-hallucination config
WHISPER_CONFIG = {
    "condition_on_previous_text": False,  # QUAN TRỌNG: Ngăn cascading errors
    "compression_ratio_threshold": 2.0,
    "no_speech_threshold": 0.5,
    "logprob_threshold": -1.0,
    "temperature": 0.0,  # Deterministic
}

# Trong method transcribe()
segments, info = self.model.transcribe(
    audio,
    language=language,
    beam_size=beam_size,
    word_timestamps=True,
    **WHISPER_CONFIG  # Apply anti-hallucination settings
)
```

---

## 4. Speaker Diarization

### Thiếu Sót Hiện Tại

1. **Không có SpeechBrain** - Alternative offline diarization
2. **Không có VBx Refiner** - Viterbi-based smoothing
3. **Không có Alignment Service** - Word-to-speaker mapping chưa tối ưu

### Đề Xuất Thêm

#### 4.1. Thêm VBx Refiner (Viterbi Smoothing)

```python
# src/infrastructure/adapters/diarization/vbx_refiner.py
import numpy as np
from typing import List
from src.core.domain.entities import SpeakerSegment

class VBxRefiner:
    """Viterbi-based HMM for speaker label smoothing"""
    
    def __init__(self, loop_prob: float = 0.9):
        self.loop_prob = loop_prob
    
    def refine(
        self, 
        segments: List[SpeakerSegment], 
        embeddings: np.ndarray,
        speaker_ids: List[str]
    ) -> List[SpeakerSegment]:
        """
        Apply Viterbi decoding to smooth speaker labels.
        Reduces over-segmentation by encouraging speaker continuity.
        """
        if len(segments) < 2:
            return segments
        
        n_speakers = len(set(speaker_ids))
        n_segments = len(segments)
        
        # Compute speaker centroids
        centroids = self._compute_centroids(embeddings, speaker_ids)
        
        # Build transition matrix (encourage staying in same state)
        trans_prob = (1 - self.loop_prob) / (n_speakers - 1) if n_speakers > 1 else 0
        transition = np.full((n_speakers, n_speakers), trans_prob)
        np.fill_diagonal(transition, self.loop_prob)
        
        # Emission probabilities (cosine similarity to centroids)
        emissions = self._compute_emissions(embeddings, centroids)
        
        # Viterbi decoding
        path = self._viterbi(emissions, transition)
        
        # Update segment labels
        unique_speakers = sorted(set(speaker_ids))
        refined_segments = []
        for i, seg in enumerate(segments):
            new_speaker = unique_speakers[path[i]]
            refined_segments.append(SpeakerSegment(
                start_time=seg.start_time,
                end_time=seg.end_time,
                speaker_id=new_speaker,
                text=seg.text
            ))
        
        return self._merge_consecutive(refined_segments)
    
    def _compute_centroids(self, embeddings: np.ndarray, labels: List[str]) -> dict:
        """Compute mean embedding for each speaker"""
        centroids = {}
        unique_labels = set(labels)
        for label in unique_labels:
            mask = [l == label for l in labels]
            centroids[label] = embeddings[mask].mean(axis=0)
        return centroids
    
    def _compute_emissions(self, embeddings: np.ndarray, centroids: dict) -> np.ndarray:
        """Compute emission probabilities using cosine similarity"""
        speakers = sorted(centroids.keys())
        centroid_matrix = np.array([centroids[s] for s in speakers])
        
        # Cosine similarity
        embeddings_norm = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
        centroids_norm = centroid_matrix / np.linalg.norm(centroid_matrix, axis=1, keepdims=True)
        similarities = embeddings_norm @ centroids_norm.T
        
        # Convert to probabilities
        emissions = np.exp(similarities * 5)  # Temperature scaling
        emissions /= emissions.sum(axis=1, keepdims=True)
        
        return emissions
    
    def _viterbi(self, emissions: np.ndarray, transition: np.ndarray) -> List[int]:
        """Standard Viterbi algorithm"""
        T, K = emissions.shape
        
        # Initialize
        viterbi = np.zeros((T, K))
        backpointer = np.zeros((T, K), dtype=int)
        
        viterbi[0] = np.log(emissions[0] + 1e-10)
        
        # Forward pass
        for t in range(1, T):
            for k in range(K):
                probs = viterbi[t-1] + np.log(transition[:, k] + 1e-10)
                backpointer[t, k] = np.argmax(probs)
                viterbi[t, k] = probs[backpointer[t, k]] + np.log(emissions[t, k] + 1e-10)
        
        # Backtrack
        path = [np.argmax(viterbi[-1])]
        for t in range(T-1, 0, -1):
            path.append(backpointer[t, path[-1]])
        
        return path[::-1]
    
    def _merge_consecutive(self, segments: List[SpeakerSegment]) -> List[SpeakerSegment]:
        """Merge consecutive segments with same speaker"""
        if not segments:
            return segments
        
        merged = [segments[0]]
        for seg in segments[1:]:
            if seg.speaker_id == merged[-1].speaker_id:
                merged[-1] = SpeakerSegment(
                    start_time=merged[-1].start_time,
                    end_time=seg.end_time,
                    speaker_id=seg.speaker_id,
                    text=f"{merged[-1].text} {seg.text}".strip()
                )
            else:
                merged.append(seg)
        
        return merged
```

#### 4.2. Thêm Alignment Service (IntervalTree)

```python
# src/core/services/alignment_service.py
from intervaltree import IntervalTree
from typing import List, Dict, Any
from src.core.domain.entities import SpeakerSegment

class AlignmentService:
    """O(log n) word-to-speaker alignment using IntervalTree"""
    
    def __init__(self, fallback_window: float = 2.0):
        self.fallback_window = fallback_window
    
    def align_words_to_speakers(
        self,
        words: List[Dict[str, Any]],  # [{"word": "...", "start": 0.0, "end": 0.5}, ...]
        speaker_segments: List[SpeakerSegment]
    ) -> List[Dict[str, Any]]:
        """
        Align each word to its speaker using interval tree.
        
        Returns words with added 'speaker' field.
        """
        # Build interval tree
        tree = IntervalTree()
        for seg in speaker_segments:
            tree[seg.start_time:seg.end_time] = seg.speaker_id
        
        # Align each word
        aligned_words = []
        for word in words:
            word_start = word.get("start", 0)
            word_end = word.get("end", word_start + 0.1)
            word_mid = (word_start + word_end) / 2
            
            # Find overlapping speaker segments
            overlaps = tree[word_mid]
            
            if overlaps:
                # Use the speaker with most overlap
                speaker = max(overlaps, key=lambda x: min(x.end, word_end) - max(x.begin, word_start)).data
            else:
                # Fallback: find nearest speaker within window
                speaker = self._find_nearest_speaker(word_mid, speaker_segments)
            
            aligned_words.append({
                **word,
                "speaker": speaker
            })
        
        return aligned_words
    
    def _find_nearest_speaker(
        self, 
        timestamp: float, 
        segments: List[SpeakerSegment]
    ) -> str:
        """Find nearest speaker within fallback window"""
        best_speaker = "UNKNOWN"
        best_distance = float('inf')
        
        for seg in segments:
            # Distance to segment
            if timestamp < seg.start_time:
                distance = seg.start_time - timestamp
            elif timestamp > seg.end_time:
                distance = timestamp - seg.end_time
            else:
                distance = 0
            
            if distance < best_distance and distance <= self.fallback_window:
                best_distance = distance
                best_speaker = seg.speaker_id
        
        return best_speaker
```

---

## 5. Text Correction

### Thiếu Sót Hiện Tại

**Không có text correction pipeline** - Đây là điểm yếu lớn nhất.

### Đề Xuất Thêm

#### 5.1. Phonetic Corrector (Rule-based)

```python
# src/infrastructure/adapters/correction/phonetic_corrector.py
import json
import re
from pathlib import Path
from src.core.ports.correction_port import ITextCorrector

class PhoneticCorrector(ITextCorrector):
    """
    Rule-based Vietnamese phonetic error correction.
    Fast, deterministic, no model required.
    """
    
    def __init__(self, vocab_path: str = None):
        self.vocab_path = vocab_path or "assets/vocab/vietnamese_phonetic_errors.json"
        self._rules = None
    
    def _load_rules(self):
        if self._rules is None:
            if Path(self.vocab_path).exists():
                with open(self.vocab_path, 'r', encoding='utf-8') as f:
                    self._rules = json.load(f)
            else:
                self._rules = self._get_default_rules()
    
    def correct(self, text: str) -> str:
        """Apply phonetic correction rules"""
        self._load_rules()
        
        result = text
        
        # Apply word-level corrections
        for wrong, correct in self._rules.get("word_corrections", {}).items():
            result = re.sub(
                rf'\b{re.escape(wrong)}\b',
                correct,
                result,
                flags=re.IGNORECASE
            )
        
        # Apply pattern-based corrections
        for pattern, replacement in self._rules.get("patterns", {}).items():
            result = re.sub(pattern, replacement, result)
        
        return result
    
    def _get_default_rules(self) -> dict:
        """Default Vietnamese phonetic error patterns"""
        return {
            "word_corrections": {
                # Common ASR errors for Vietnamese
                "dạ": "vâng",
                "zậy": "vậy",
                "dzậy": "vậy",
                "giờ": "giờ",
                "zì": "gì",
                "dzì": "gì",
                "khoong": "không",
                "bít": "biết",
                "đc": "được",
                "dc": "được",
                "ko": "không",
                "k": "không",
                "nc": "nước",
                "trc": "trước",
                "ns": "nói",
                "ng": "người",
                "ntn": "như thế nào",
                "bn": "bao nhiêu",
                "j": "gì",
                "m": "mình",
                "b": "bạn",
            },
            "patterns": {
                # Fix double consonants
                r'\bkh\s+ông\b': 'không',
                r'\bng\s+ười\b': 'người',
                r'\bnh\s+ư\b': 'như',
                # Fix tone marks
                r'([aeiouáàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ])\s+([̣́̀̉̃])': r'\1\2',
            }
        }
```

#### 5.2. Tạo File Vocabulary

```json
// assets/vocab/vietnamese_phonetic_errors.json
{
  "word_corrections": {
    "dạ vâng": "vâng",
    "à à": "à",
    "ừ ừ": "ừ",
    "ok ok": "ok",
    "yeah yeah": "vâng",
    "zậy": "vậy",
    "dzậy": "vậy",
    "giờ": "giờ",
    "zì": "gì",
    "dzì": "gì",
    "khoong": "không",
    "bít": "biết",
    "thoai": "thôi",
    "roài": "rồi",
    "hok": "không",
    "hem": "không",
    "ngen": "nghen",
    "hen": "hẹn",
    "nghen": "nhé",
    "nha": "nhé",
    "nhe": "nhé",
    "oki": "ok",
    "okie": "ok"
  },
  "patterns": {
    "\\b(ơ|ờ|ớ)\\s+(i|ì|í)\\b": "ơi",
    "\\bđ\\s+ược\\b": "được",
    "\\bkh\\s+ông\\b": "không",
    "\\bng\\s+ười\\b": "người",
    "\\btr\\s+ước\\b": "trước"
  },
  "filler_words": [
    "ừm",
    "ờ",
    "à",
    "uh",
    "um",
    "hmm",
    "ờm",
    "ừ"
  ]
}
```

#### 5.3. Multi-Stage Correction Service

```python
# src/application/services/correction_service.py
from typing import List
from src.core.ports.correction_port import ITextCorrector
from src.core.ports.llm_port import ILLMEngine

class CorrectionService:
    """
    Multi-stage text correction pipeline:
    1. Phonetic (rule-based, fast)
    2. LLM contextual (semantic understanding)
    """
    
    def __init__(
        self,
        phonetic_corrector: ITextCorrector,
        llm_engine: ILLMEngine = None
    ):
        self.phonetic = phonetic_corrector
        self.llm = llm_engine
    
    def correct(self, text: str, use_llm: bool = False) -> str:
        """
        Apply multi-stage correction.
        
        Args:
            text: Raw transcription
            use_llm: Whether to use LLM for contextual correction
        
        Returns:
            Corrected text
        """
        # Stage 1: Phonetic correction (always)
        result = self.phonetic.correct(text)
        
        # Stage 2: LLM contextual correction (optional)
        if use_llm and self.llm:
            result = self._llm_correct(result)
        
        return result
    
    def _llm_correct(self, text: str) -> str:
        """Use LLM for contextual correction"""
        prompt = f"""Sửa lỗi chính tả và ngữ pháp tiếng Việt trong đoạn văn sau.
Chỉ sửa lỗi, KHÔNG thay đổi nội dung hay ý nghĩa.
Trả về văn bản đã sửa, không giải thích.

Văn bản:
{text}

Văn bản đã sửa:"""
        
        try:
            corrected = self.llm.generate(prompt)
            # Validate output is reasonable
            if len(corrected) > 0 and len(corrected) < len(text) * 2:
                return corrected.strip()
        except Exception:
            pass
        
        return text
```

---

## 6. LLM Integration

### Thiếu Sót Hiện Tại

1. **Chỉ có Ollama** - Thiếu llama.cpp fallback
2. **Không có caching** - Mỗi request đều call LLM

### Đề Xuất Thêm

#### 6.1. Thêm LlamaCpp Adapter

```python
# src/infrastructure/adapters/llm/llamacpp_adapter.py
from llama_cpp import Llama
from src.core.ports.llm_port import ILLMEngine
import logging

logger = logging.getLogger(__name__)

class LlamaCppAdapter(ILLMEngine):
    """
    llama.cpp adapter for offline LLM inference.
    Uses GGUF format models.
    """
    
    def __init__(self, config):
        self.config = config
        self.model_path = config.LLAMACPP_MODEL_PATH
        self._model = None
    
    def load(self) -> bool:
        if self._model is None:
            try:
                self._model = Llama(
                    model_path=self.model_path,
                    n_ctx=4096,
                    n_gpu_layers=-1,  # Use all GPU layers
                    verbose=False
                )
                logger.info(f"Loaded llama.cpp model: {self.model_path}")
                return True
            except Exception as e:
                logger.error(f"Failed to load llama.cpp model: {e}")
                return False
        return True
    
    def generate(self, prompt: str, max_tokens: int = 2048) -> str:
        if not self.load():
            raise RuntimeError("Model not loaded")
        
        response = self._model(
            prompt,
            max_tokens=max_tokens,
            temperature=0.1,
            top_p=0.9,
            stop=["</s>", "\n\n\n"]
        )
        
        return response["choices"][0]["text"].strip()
    
    def unload(self):
        if self._model:
            del self._model
            self._model = None
```

#### 6.2. Thêm Response Caching

```python
# src/infrastructure/adapters/llm/cached_llm.py
import hashlib
import json
from pathlib import Path
from src.core.ports.llm_port import ILLMEngine

class CachedLLMAdapter(ILLMEngine):
    """Wrapper that adds caching to any LLM adapter"""
    
    def __init__(self, llm: ILLMEngine, cache_dir: str = ".cache/llm"):
        self.llm = llm
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def generate(self, prompt: str, **kwargs) -> str:
        # Generate cache key
        cache_key = hashlib.md5(
            f"{prompt}:{json.dumps(kwargs, sort_keys=True)}".encode()
        ).hexdigest()
        
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        # Check cache
        if cache_file.exists():
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)["response"]
        
        # Generate and cache
        response = self.llm.generate(prompt, **kwargs)
        
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump({"prompt": prompt, "response": response}, f, ensure_ascii=False)
        
        return response
    
    def load(self) -> bool:
        return self.llm.load()
    
    def unload(self):
        self.llm.unload()
```

---

## 7. Prompt Engineering

### Thiếu Sót Hiện Tại

1. **Prompts hardcoded** - Trong Python code
2. **Không có template engine** - Khó maintain
3. **Không có scenario-based prompts** - Thiếu domain vocabulary

### Đề Xuất Thêm

#### 7.1. Tổ Chức Prompts

```
prompts/
├── templates/
│   ├── analysis.j2              # Master analysis template
│   ├── summarization.j2         # Summarization template
│   └── entity_extraction.j2     # Entity extraction
├── modules/
│   ├── entities_5w1h.j2         # 5W1H extraction
│   ├── sensitive_info.j2        # Sensitive info detection
│   └── speaker_roles.j2         # Speaker role inference
└── scenarios/
    ├── general.yaml             # General vocabulary
    ├── drug_trafficking.yaml    # Drug-related slang
    └── fraud.yaml               # Fraud terminology
```

#### 7.2. Prompt Manager

```python
# src/application/services/prompt_manager.py
from jinja2 import Environment, FileSystemLoader
import yaml
from pathlib import Path

class PromptManager:
    """Jinja2-based prompt management"""
    
    def __init__(self, prompts_dir: str = "prompts"):
        self.prompts_dir = Path(prompts_dir)
        self.env = Environment(
            loader=FileSystemLoader([
                self.prompts_dir / "templates",
                self.prompts_dir / "modules"
            ])
        )
        self._scenarios = {}
    
    def render(self, template_name: str, **context) -> str:
        """Render a prompt template with context"""
        template = self.env.get_template(f"{template_name}.j2")
        return template.render(**context)
    
    def load_scenario(self, scenario_name: str) -> dict:
        """Load scenario-specific vocabulary"""
        if scenario_name not in self._scenarios:
            scenario_path = self.prompts_dir / "scenarios" / f"{scenario_name}.yaml"
            if scenario_path.exists():
                with open(scenario_path, 'r', encoding='utf-8') as f:
                    self._scenarios[scenario_name] = yaml.safe_load(f)
            else:
                self._scenarios[scenario_name] = {}
        return self._scenarios[scenario_name]
    
    def get_analysis_prompt(self, transcript: str, scenario: str = "general") -> str:
        """Get complete analysis prompt with scenario vocabulary"""
        scenario_data = self.load_scenario(scenario)
        return self.render(
            "analysis",
            transcript=transcript,
            slang_dictionary=scenario_data.get("slang", {}),
            keywords=scenario_data.get("keywords", []),
            scenario_context=scenario_data.get("context", "")
        )
```

#### 7.3. Mẫu Template

```jinja2
{# prompts/templates/analysis.j2 #}
Bạn là chuyên gia phân tích hội thoại tiếng Việt cho mục đích điều tra.

{% if scenario_context %}
## Bối cảnh
{{ scenario_context }}
{% endif %}

{% if slang_dictionary %}
## Từ điển tiếng lóng
{% for term, meaning in slang_dictionary.items() %}
- "{{ term }}": {{ meaning }}
{% endfor %}
{% endif %}

## Nhiệm vụ
Phân tích đoạn hội thoại sau và trích xuất thông tin theo format JSON.

## Hội thoại
{{ transcript }}

## Yêu cầu output (JSON)
{
  "entities": {
    "people": [],
    "locations": [],
    "organizations": [],
    "phone_numbers": [],
    "dates_times": []
  },
  "summary": "",
  "key_topics": [],
  "threat_level": "BENIGN|LOW|MEDIUM|HIGH|CRITICAL",
  "suspicious_indicators": [],
  "relationships": []
}

Trả lời bằng JSON, không giải thích thêm.
```

#### 7.4. Scenario YAML

```yaml
# prompts/scenarios/drug_trafficking.yaml
name: "Drug Trafficking Investigation"
context: |
  Phân tích hội thoại liên quan đến buôn bán ma túy.
  Chú ý các từ lóng, mã hóa, và giao dịch ngầm.

slang:
  "hàng": "ma túy"
  "cỏ": "cần sa"
  "đá": "methamphetamine"
  "kẹo": "thuốc lắc/MDMA"
  "bột": "heroin/cocaine"
  "xách": "vận chuyển ma túy"
  "cái": "gram"
  "lạng": "100 gram"
  "củ": "triệu đồng"
  "chai": "1 lít tiền chất"
  "gói": "đơn vị đóng gói"
  "ship": "giao hàng"
  "chốt": "địa điểm giao dịch"

keywords:
  - "giao hàng"
  - "chuyển tiền"
  - "điểm hẹn"
  - "số lượng"
  - "giá cả"
  - "mẫu thử"

indicators:
  - "Sử dụng ngôn ngữ mã hóa"
  - "Trao đổi về số lượng và giá"
  - "Đề cập địa điểm giao dịch"
  - "Thảo luận về phương thức thanh toán"
```

---

## 8. Code Quality

### Các Vấn Đề Cần Sửa

#### 8.1. Duplicate Code

**Vị trí:** `src/cherry_core/services/ollama_processor.py`

```python
# Hiện tại: 2 functions có cùng translation dictionary
def translate_line_to_vietnamese(line: str) -> str: ...
def force_vietnamese_output(text: str) -> str: ...

# Đề xuất: Refactor thành shared module
# src/utils/vietnamese_utils.py
ENGLISH_TO_VIETNAMESE = {
    "Summary": "Tóm tắt",
    "Analysis": "Phân tích",
    # ...
}

def translate_to_vietnamese(text: str) -> str:
    for en, vi in ENGLISH_TO_VIETNAMESE.items():
        text = text.replace(en, vi)
    return text
```

#### 8.2. File Quá Lớn

| File | Lines | Đề xuất |
|------|-------|---------|
| `audio.py` | 800+ | Tách thành `upload.py`, `process.py`, `status.py` |
| `transcriber.py` | 1000+ | Tách thành `model.py`, `processor.py`, `utils.py` |
| `App.tsx` | 1500+ | Tách thành components nhỏ hơn |

#### 8.3. Xóa Files Backup

```bash
# Files cần xóa
del src\speech_to_text\transcriber.py.backup
del frontend\src\components\FileCard_old.tsx
del frontend\src\components\FileCard_backup.tsx
del *.log  # Log files in root
```

#### 8.4. Thêm Type Hints

```python
# Trước
def process_audio(file_path, options=None):
    ...

# Sau
from typing import Optional, Dict, Any
from src.core.domain.entities import Transcript

def process_audio(
    file_path: str, 
    options: Optional[Dict[str, Any]] = None
) -> Transcript:
    ...
```

#### 8.5. Cải Thiện Error Handling

```python
# src/core/exceptions.py
class SpeechToInfoException(Exception):
    """Base exception for the application"""
    pass

class TranscriptionError(SpeechToInfoException):
    """Error during transcription"""
    pass

class DiarizationError(SpeechToInfoException):
    """Error during speaker diarization"""
    pass

class LLMError(SpeechToInfoException):
    """Error during LLM processing"""
    pass

# Usage
from src.core.exceptions import TranscriptionError

def transcribe(audio_path: str) -> Transcript:
    try:
        # ... transcription logic
    except Exception as e:
        raise TranscriptionError(f"Failed to transcribe {audio_path}: {e}") from e
```

---

## 9. Danh Sách Công Việc Ưu Tiên

### Ưu Tiên Cao (Nên làm ngay)

| # | Công việc | Effort | Impact |
|---|-----------|--------|--------|
| 1 | Thêm Hallucination Filter | 2h | Cao |
| 2 | Thêm Phonetic Corrector | 3h | Cao |
| 3 | Cập nhật Whisper anti-hallucination config | 1h | Cao |
| 4 | Tạo Port Interfaces | 4h | Cao |
| 5 | Refactor translation dictionary | 1h | Trung bình |

### Ưu Tiên Trung Bình

| # | Công việc | Effort | Impact |
|---|-----------|--------|--------|
| 6 | Thêm VBx Refiner | 4h | Trung bình |
| 7 | Thêm Alignment Service | 3h | Trung bình |
| 8 | Implement Prompt Manager (Jinja2) | 4h | Trung bình |
| 9 | Thêm LlamaCpp Adapter | 3h | Trung bình |
| 10 | Thêm Response Caching | 2h | Trung bình |

### Ưu Tiên Thấp (Nice to have)

| # | Công việc | Effort | Impact |
|---|-----------|--------|--------|
| 11 | Thêm PhoWhisper Adapter | 4h | Thấp |
| 12 | Thêm SpeechBrain Adapter | 4h | Thấp |
| 13 | Tạo scenario YAML files | 2h | Thấp |
| 14 | Xóa backup files | 0.5h | Thấp |
| 15 | Thêm unit tests | 8h | Trung bình |

### Tổng Effort Ước Tính

- **Ưu tiên cao:** ~11 giờ
- **Ưu tiên trung bình:** ~16 giờ
- **Ưu tiên thấp:** ~18.5 giờ
- **Tổng:** ~45.5 giờ (~6 ngày làm việc)

---

## Kết Luận

SpeechToInformation đã có nền tảng tốt với:
- FastAPI + Celery architecture
- React frontend hoàn chỉnh
- PostgreSQL database
- GPU optimization

Để đạt chất lượng như Cherry Core, cần tập trung vào:

1. **Anti-hallucination** - Quan trọng nhất cho độ chính xác
2. **Text correction pipeline** - Cải thiện chất lượng tiếng Việt
3. **Clean Architecture** - Dễ maintain và mở rộng
4. **Prompt engineering** - Tăng chất lượng phân tích

Với các cải tiến này, hệ thống sẽ đạt chất lượng production-ready cho các ứng dụng điều tra/forensic.
