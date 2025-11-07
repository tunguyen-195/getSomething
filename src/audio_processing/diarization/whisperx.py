from .base import SpeakerDiarizationPipeline
from typing import List, Dict, Any
import subprocess
import os

class WhisperXPipeline(SpeakerDiarizationPipeline):
    def run(self, audio_path: str) -> List[Dict[str, Any]]:
        """
        Gọi whisperx qua subprocess (hoặc import nếu đã cài đặt), trả về list segment.
        Yêu cầu: whisperx, pyannote.audio đã cài đặt và model đã tải về local.
        """
        # TODO: Thay thế bằng code native nếu muốn tích hợp sâu hơn
        # Ví dụ mẫu: subprocess gọi whisperx CLI, parse kết quả json
        output_json = "output_whisperx.json"
        cmd = [
            "whisperx",
            audio_path,
            "--diarize",
            "--output_format", "json",
            "--output_file", output_json
        ]
        subprocess.run(cmd, check=True)
        import json
        with open(output_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        segments = []
        for seg in data.get("segments", []):
            segments.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
                "speaker": seg.get("speaker", "unknown")
            })
        os.remove(output_json)
        return segments
