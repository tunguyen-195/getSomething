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
from faster_whisper import WhisperModel
from dataclasses import dataclass
from typing import List, Optional, Tuple
import time
from concurrent.futures import ThreadPoolExecutor
import librosa
from src.audio_processing.processor import AudioProcessor
from src.core.config import settings
from src.audio_processing.vad.silero_adapter import SileroVADAdapter

@dataclass
class AudioSegment:
    """Class for storing audio segment information"""
    data: np.ndarray
    start_time: float
    end_time: float
    context: Optional[np.ndarray] = None

class OllamaProcessor:
    def __init__(self, model_name: str | None = None):
        """Initialize Ollama processor for context-aware analysis"""
        self.model_name = model_name
        logger.info(
            "Initialized legacy Analysis adapter | model=%s",
            model_name or "auto",
        )

    def get_available_models(self) -> dict:
        """Get list of available models and their descriptions"""
        from src.services.summarization.models.llm_manager import get_llm_manager

        return {
            model: "Mô hình cục bộ đã cài đặt"
            for model in get_llm_manager().get_available_models()
        }

    def set_model(self, model_name: str) -> bool:
        """Set the model to use for analysis"""
        from src.services.summarization.models.llm_manager import get_llm_manager

        if model_name in get_llm_manager().get_available_models():
            self.model_name = model_name
            logger.info(f"Changed model to: {model_name}")
            return True
        logger.warning(f"Model {model_name} không có sẵn")
        return False

    def analyze_context(self, text: str) -> dict:
        """Delegate legacy callers to the single production Analysis pipeline."""
        from src.services.summarization.context_service import (
            analyze_conversation_context,
        )

        return analyze_conversation_context(
            text,
            model_name=self.model_name,
        )

    def visualize_context(self, text: str) -> dict:
        """Legacy entrypoint: Analysis owns facts; this path never calls an LLM."""
        analysis = self.analyze_context(text)
        if not isinstance(analysis, dict):
            return {}
        return {
            "analysis_status": analysis.get("analysis_status"),
            "analysis_text": analysis.get("analysis_text"),
            "timeline": analysis.get("events") or [],
            "nodes": analysis.get("entities") or [],
            "edges": analysis.get("relationships") or [],
            "actions": analysis.get("actions") or [],
        }

class Transcriber:
    def __init__(self):
        device = settings.WHISPER_DEVICE
        compute_type = settings.WHISPER_COMPUTE_TYPE
        model_name = settings.WHISPER_MODEL
        # --- Tự động điều chỉnh batch_size theo VRAM GPU ---
        batch_size = settings.WHISPER_BATCH_SIZE
        if device == "cuda":
            try:
                import torch
                vram = torch.cuda.get_device_properties(0).total_memory // (1024 ** 3)  # GB
                if vram >= 12:
                    auto_bs = 16
                elif vram >= 8:
                    auto_bs = 8
                elif vram >= 4:
                    auto_bs = 4
                else:
                    auto_bs = 2
                if batch_size < auto_bs:
                    logger.info(f"[AUTO-BATCH] batch_size giữ nguyên theo settings: {batch_size}")
                else:
                    batch_size = auto_bs
                    logger.info(f"[AUTO-BATCH] batch_size tự động điều chỉnh theo VRAM: {batch_size}")
            except Exception as e:
                logger.warning(f"[AUTO-BATCH] Không thể kiểm tra VRAM, dùng batch_size mặc định: {batch_size}. Lỗi: {e}")
        # Support both local path và automatic download/cache
        use_local = getattr(settings, 'WHISPER_USE_LOCAL', True)
        download_root = getattr(settings, 'WHISPER_MODEL_PATH', 'models/whisper') if use_local else None

        if use_local:
            logger.info(f"[OFFLINE MODE] Using local model cache: {download_root}")

        # Load model - will use cache if available, download if needed
        self.model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=download_root
        )
        logger.info(f"[MODEL] Loaded {model_name} successfully")
        self.device = device
        self.compute_type = compute_type
        self.model_name = model_name
        self.batch_size = batch_size
        self.beam_size = settings.WHISPER_BEAM_SIZE
        self.min_segment_length = getattr(settings, 'WHISPER_MIN_SEGMENT_LENGTH', None) or 10
        self.max_segment_length = getattr(settings, 'WHISPER_MAX_SEGMENT_LENGTH', None) or 30
        self.context_window = getattr(settings, 'WHISPER_CONTEXT_WINDOW', None) or 5
        self.overlap = getattr(settings, 'WHISPER_OVERLAP', None) or 0.5
        self._set_segmentation_params(self.min_segment_length, self.max_segment_length, self.context_window, self.overlap)
        self.min_silence_len = getattr(settings, 'WHISPER_MIN_SILENCE_LEN', None) or 1000  # ms
        self.silence_thresh = getattr(settings, 'WHISPER_SILENCE_THRESH', None) or -40.0
        self.keep_silence = 100  # ms
        self.llm_processor = OllamaProcessor()
        self.speaker_pipeline = None
        self.pipeline = self.model
        self.audio_processor = AudioProcessor()
        # Initialize Silero VAD Adapter (Start-Fix)
        try:
            self.vad_adapter = SileroVADAdapter()
            logger.info("✅ Silero VAD Adapter initialized for start-fix")
        except Exception as e:
            logger.warning(f"⚠️ Failed to init Silero VAD: {e}")
            self.vad_adapter = None

        logger.info(f"Transcriber initialized: model={model_name}, device={device}, compute_type={compute_type}")

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
            # Loại bỏ các segment quá ngắn (<0.5s)
            min_len = int(0.5 * sr)
            segments = [seg for seg in segments if len(seg.data) >= min_len]
            if len(segments) == 0:
                logger.warning("[SEGMENT-LOG] Không có segment nào đủ dài để nhận diện!")
            return segments
        except Exception as e:
            logger.error(f"Error segmenting audio: {str(e)}")
            return []

    def _process_segment(self, segment: AudioSegment) -> str:
        """Process a single audio segment."""
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
            # Dùng pipeline.transcribe (WhisperModel) với batch_size nếu cần
            # NOTE: VAD filter disabled to avoid cutting important speech at beginning/end
            # This ensures complete transcription of all audio content
            segments, info = self.pipeline.transcribe(
                audio,
                language="vi",
                beam_size=self.beam_size,
                vad_filter=False  # Disabled to preserve all content
            )
            if segments is None or info is None:
                logger.error(f"pipeline.transcribe trả về None: segments={segments}, info={info}")
                raise Exception(f"pipeline.transcribe trả về None: segments={segments}, info={info}")
            # Không còn KenLM, chỉ lấy transcript tốt nhất
            text = " ".join([s.text for s in segments if hasattr(s, 'text') and s.text])
            return text
        except Exception as e:
            logger.error(f"Error processing segment: {str(e)}")
            return ""

    def _post_process_text(self, text: str) -> str:
        """Post-process transcribed text: loại filler, chuẩn hóa dấu câu, kiểm tra ngôn ngữ."""
        try:
            # Remove extra whitespace
            text = " ".join(text.split())
            # Remove multiple spaces
            text = " ".join(text.split())
            # Loại bỏ filler
            fillers = ['ừ', 'à', 'ờ', 'ơ', 'ừm', 'à ừm']
            for filler in fillers:
                text = text.replace(filler, '')
            # Chuẩn hóa dấu câu
            import re
            text = re.sub(r'([.,!?])\s*', r'\1 ', text)
            text = re.sub(r'\s+([.,!?])', r'\1', text)
            # Viết hoa đầu câu
            text = re.sub(r'(^|[.!?]\s+)([a-zà-ỹ])', lambda m: m.group(1) + m.group(2).upper(), text)
            # Remove leading/trailing whitespace
            text = text.strip()
            return text
        except Exception as e:
            logger.error(f"Error post-processing text: {str(e)}")
            return text

    def _is_noisy(self, audio: np.ndarray) -> bool:
        """Phát hiện audio nhiễu (placeholder, cần tích hợp model thực tế)"""
        # TODO: Tích hợp model phát hiện nhiễu
        return False

    def _generate_caption(self, audio: np.ndarray, sr: int = 16000) -> str:
        """Sinh caption mô tả toàn bộ nội dung audio bằng Whisper (nếu hỗ trợ)."""
        try:
            # Nếu model hỗ trợ captioning (Whisper >= large-v3), dùng transcribe với task='translate' để sinh mô tả
            if hasattr(self.model, 'transcribe'):
                segments, info = self.model.transcribe(
                    audio,
                    language="vi",
                    beam_size=self.beam_size,
                    vad_filter=True,
                    vad_parameters=dict(
                        min_silence_duration_ms=500,
                        speech_pad_ms=100
                    ),
                    task="translate"  # Whisper hỗ trợ mô tả audio qua task này
                )
                caption = " ".join([s.text for s in segments if hasattr(s, 'text') and s.text])
                return caption
            else:
                return ""
        except Exception as e:
            logger.error(f"Error generating caption: {str(e)}")
            return ""

    def transcribe_with_diarization(self, audio_path: str, fast_mode: bool = False, enable_diarization: bool = True) -> dict:
        """
        Transcribe audio with speaker diarization

        Args:
            audio_path: Path to audio file
            fast_mode: Skip heavy LLM post-processing
            enable_diarization: Enable speaker diarization (labels who spoke when)

        Returns:
            dict with 'segments' containing [{'start', 'end', 'text', 'speaker'}]
                 and 'formatted_transcript' in SRT-like format
        """
        logger.info(f"[TRANSCRIBER] Starting transcribe_with_diarization | audio={audio_path} | fast_mode={fast_mode} | diarization={enable_diarization}")

        try:
            start_time = time.time()

            # Step 0: Preprocess audio with Silero VAD (Fix Missing Start)
            process_path = audio_path
            if self.vad_adapter:
                try:
                    logger.info("[VAD-PRE] Running Silero VAD to fix start/end and remove silence...")
                    process_path = self.vad_adapter.remove_silence(audio_path)
                    logger.info(f"[VAD-PRE] Processed audio saved to: {process_path}")
                except Exception as e:
                    logger.error(f"[VAD-PRE] Failed to process audio: {e}. Using original.")
                    process_path = audio_path

            # Step 1: Run Whisper transcription to get segments with timestamps
            # NOTE: vad_filter can cut off beginning/end of audio, so we disable it
            # for diarization to ensure we don't miss any content
            segments_whisper, info = self.model.transcribe(
                process_path,
                language="vi",
                beam_size=self.beam_size,
                vad_filter=False,  # Disable VAD to avoid missing content
                word_timestamps=True  # Important for diarization alignment
            )

            # Convert generator to list
            transcript_segments = []
            for seg in segments_whisper:
                transcript_segments.append({
                    'start': seg.start,
                    'end': seg.end,
                    'text': seg.text.strip()
                })

            logger.info(f"[TRANSCRIBER] Whisper produced {len(transcript_segments)} segments")

            # Step 2: Run speaker diarization if enabled
            final_segments = transcript_segments
            if enable_diarization and len(transcript_segments) > 0:
                try:
                    from src.audio_processing.diarization.whisperx import WhisperXPipeline
                    diarizer = WhisperXPipeline()

                    # Get speaker segments
                    # Use processed path for better alignment if VAD was successful
                    diar_audio_path = process_path if process_path and os.path.exists(process_path) else audio_path
                    speaker_segments = diarizer.run(diar_audio_path)
                    logger.info(f"[DIARIZATION] Found {len(speaker_segments)} speaker segments")

                    # Assign speakers to transcript segments
                    if len(speaker_segments) > 0:
                        final_segments = diarizer.assign_speakers_to_transcript(
                            transcript_segments,
                            speaker_segments,
                            audio_path=audio_path  # Pass audio path for fallback
                        )
                        logger.info(f"[DIARIZATION] Assigned speakers to {len(final_segments)} segments")
                    else:
                        # Fallback: assign default speaker
                        final_segments = [
                            {**seg, 'speaker': 'Speaker 0'}
                            for seg in transcript_segments
                        ]
                except Exception as e:
                    logger.error(f"[DIARIZATION] Error: {e}. Using no speaker labels.")
                    final_segments = [
                        {**seg, 'speaker': 'Speaker 0'}
                        for seg in transcript_segments
                    ]
            else:
                # No diarization: assign default speaker
                final_segments = [
                    {**seg, 'speaker': 'Speaker 0'}
                    for seg in transcript_segments
                ]

            # Step 3: Format output like ElevenLabs Scribe / file mẫu
            formatted_lines = []
            for seg in final_segments:
                start_time_str = self._format_timestamp(seg['start'])
                end_time_str = self._format_timestamp(seg['end'])
                speaker = seg.get('speaker', 'Speaker 0')
                text = seg['text']

                # Format: HH:MM:SS,mmm --> HH:MM:SS,mmm [Speaker X]
                formatted_lines.append(f"{start_time_str} --> {end_time_str} [{speaker}]")
                formatted_lines.append(text)
                formatted_lines.append("")  # Empty line

            formatted_transcript = "\n".join(formatted_lines)

            # Step 4: Optional full-mode processing
            full_text = " ".join([seg['text'] for seg in final_segments])
            context_analysis = {}
            summary = ""

            if not fast_mode:
                try:
                    context_analysis = self.llm_processor.analyze_context(full_text)
                except Exception as e:
                    logger.warning(f"[LLM] Context analysis failed: {e}")

            processing_time = time.time() - start_time
            duration = info.duration if hasattr(info, 'duration') else final_segments[-1]['end'] if final_segments else 0

            result = {
                'transcription': full_text,
                'formatted_transcript': formatted_transcript,
                'segments': final_segments,
                'duration': duration,
                'processing_time': processing_time,
                'speed_factor': duration / processing_time if processing_time > 0 else 0,
                'language': 'vi',
                'analysis': context_analysis,
                'summary': summary,
                'num_speakers': len(set(seg['speaker'] for seg in final_segments)),
                'fast_mode': fast_mode,
                'diarization_enabled': enable_diarization
            }

            logger.info(f"[TRANSCRIBER] Completed in {processing_time:.2f}s | Speed: {result['speed_factor']:.1f}x")
            return result

        except Exception as e:
            logger.error(f"[TRANSCRIBER] Error in transcribe_with_diarization: {e}", exc_info=True)
            raise

    def _format_timestamp(self, seconds: float) -> str:
        """Format seconds to HH:MM:SS,mmm"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def transcribe(self, audio_path: str, fast_mode: bool = False) -> dict:
        """Transcribe audio file to text with parallel processing và context analysis

        Args:
            audio_path: Path to audio file
            fast_mode: If True, skip heavy post-processing (LLM analysis, summarization)
                      to achieve maximum speed (~30x real-time)
        """
        logger.info(f"[TRANSCRIBER] Bắt đầu transcribe | audio_path={audio_path} | fast_mode={fast_mode}")
        try:
            start_time = time.time()
            # Load audio và nhận diện
            audio, sr = self._load_audio(audio_path)
            logger.info(f"[TRANSCRIBER] Đã load audio | path={audio_path} | shape={audio.shape if hasattr(audio, 'shape') else 'N/A'} | sr={sr}")
            # --- Bổ sung bước làm sạch ---
            # audio = self.audio_processor.normalize_audio(audio)
            # audio = self.audio_processor.remove_silence(audio, top_db=20)
            # --- Phát hiện và enhance nếu nhiễu ---
            if audio.std() < 0.01 or self._is_noisy(audio):
                logger.info("[AUDIO] Phát hiện audio nhiễu, thực hiện enhance_speech_llase...")
                audio = self.audio_processor.enhance_speech_llase(audio)
            # Log VRAM trước khi transcribe
            if self.device == "cuda":
                try:
                    import torch
                    logger.info(f"[GPU] VRAM used before: {torch.cuda.memory_allocated() // (1024**2)} MB")
                except Exception:
                    pass
            # Segment audio
            segments = self._segment_audio(audio, sr)
            logger.info(f"[TRANSCRIBER] Đã segment audio | num_segments={len(segments)}")
            # --- Tối ưu ThreadPoolExecutor cho batch lớn ---
            max_workers = min(self.batch_size, 8)
            try:
                import torch
                vram = torch.cuda.get_device_properties(0).total_memory // (1024 ** 3)
                if self.device == "cuda" and self.batch_size > 8 and vram >= 8:
                    max_workers = min(self.batch_size, 16)
                if self.device == "cuda" and self.batch_size > 12 and vram >= 12:
                    max_workers = min(self.batch_size, 32)
            except Exception:
                pass
            segment_times = []
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = []
                for segment in segments:
                    t0 = time.time()
                    future = executor.submit(self._process_segment, segment)
                    futures.append((future, t0))
            results = []
            for idx, (future, t0) in enumerate(futures):
                result = future.result()
                t1 = time.time()
                segment_times.append(t1 - t0)
                logger.info(f"[TRANSCRIBER] Segment {idx+1}/{len(futures)} processed in {t1-t0:.2f}s | result_len={len(result) if result else 0}")
                if result:
                    results.append(result)
            if len(segment_times) > 0:
                logger.info(f"[TRANSCRIBE] Thời gian xử lý từng segment: {segment_times}")
            # Log VRAM sau khi transcribe
            if self.device == "cuda":
                try:
                    import torch
                    logger.info(f"[GPU] VRAM used after: {torch.cuda.memory_allocated() // (1024**2)} MB")
                except Exception:
                    pass
            text = " ".join(results)
            # --- Hậu xử lý transcript nâng cao ---
            text = self._post_process_text(text)
            # Kiểm tra chất lượng transcript
            import re
            min_length = 20  # ký tự
            max_invalid_ratio = 0.2
            valid_chars = re.sub(r'[^\w\s.,!?à-ỹÀ-Ỹ]', '', text)
            char_ratio = len(valid_chars) / max(1, len(text))
            if len(text) < min_length or char_ratio < (1 - max_invalid_ratio):
                logger.warning(f"[TRANSCRIBE] Transcript không đạt chuẩn: length={len(text)}, char_ratio={char_ratio:.2f}")
                text = "[CẢNH BÁO] Transcript không đạt chuẩn chất lượng, vui lòng kiểm tra lại file audio."
            # --- Sinh caption và phân tích ngữ cảnh (chỉ khi không dùng fast_mode) ---
            caption = ""
            context_analysis = {}
            summary = ""

            if not fast_mode:
                # Sinh caption mô tả audio
                caption = self._generate_caption(audio, sr)
                # Phân tích ngữ cảnh bằng Ollama
                context_analysis = self.llm_processor.analyze_context(text)
                # Tóm tắt nội dung (nếu có summarizer)
                if hasattr(self, "summarizer") and self.summarizer:
                    try:
                        summary = self.summarizer.summarize(text, context=context_analysis)
                    except Exception as e:
                        logger.error(f"Error summarizing: {e}")
                        summary = ""
            else:
                logger.info("[FAST_MODE] Skipping caption, LLM analysis, and summarization for maximum speed")
            # Calculate confidence (simple heuristic)
            duration = len(audio) / sr
            confidence = min(1.0, len(text) / (duration * 10))  # Assume 10 chars per second is good
            # Tính quality_score: trung bình giữa confidence và tỉ lệ ký tự hợp lệ
            import re
            valid_chars = re.sub(r'[^\w\s.,!?à-ỹÀ-Ỹ]', '', text)
            char_ratio = len(valid_chars) / max(1, len(text))
            quality_score = round((confidence + char_ratio) / 2, 3)
            if confidence < 0.5:
                logger.warning(f"[TRANSCRIBE] Confidence thấp: {confidence:.2f}")
            if char_ratio < 0.8:
                logger.warning(f"[TRANSCRIBE] Transcript có nhiều ký tự không hợp lệ: {char_ratio:.2f}")
            # Log chi tiết độ dài transcript, duration, số segment
            logger.info(f"[TRANSCRIBE] Transcript length: {len(text)} chars, Audio duration: {duration:.2f}s, Num segments: {len(segments) if 'segments' in locals() else 'N/A'}")
            if len(text) < 0.5 * duration * 10:
                logger.warning(f"[TRANSCRIBE] Transcript ngắn bất thường so với duration: {len(text)} chars / {duration:.2f}s. Có thể nhận diện thiếu!")
            # Trả về đúng schema chuẩn, bổ sung caption
            result = {
                "transcription": text,
                "transcript": text,
                "caption": caption,
                "analysis": context_analysis,
                "summary": summary,
                "confidence": confidence,
                "duration": duration,
                "language": "vi",
                "quality_score": quality_score,
                "processing_time": time.time() - start_time
            }
            logger.info(f"[TRANSCRIBER] Kết quả transcribe | audio_path={audio_path} | result_keys={list(result.keys())}")
            return result
        except Exception as e:
            logger.error(f"Error transcribing audio: {str(e)}", exc_info=True)
            raise
