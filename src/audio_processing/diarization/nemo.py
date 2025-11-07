from .base import SpeakerDiarizationPipeline
from typing import List, Dict, Any
import subprocess
import os

class NeMoPipeline(SpeakerDiarizationPipeline):
    def run(self, audio_path: str) -> List[Dict[str, Any]]:
        """
        Gọi NeMo diarization qua subprocess (hoặc import nếu đã cài đặt), trả về list segment.
        Yêu cầu: nemo_toolkit, model đã tải về local.
        """
        # TODO: Thay thế bằng code native nếu muốn tích hợp sâu hơn
        # Ví dụ mẫu: subprocess gọi script diarization, parse kết quả json
        output_json = "output_nemo.json"
        cmd = [
            "python", "scripts/run_nemo_diarization.py",
            "--audio", audio_path,
            "--output", output_json
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
