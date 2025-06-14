import os
from diart import SpeakerDiarization
from diart.sources import FileAudioSource
from diart.inference import StreamingInference
from diart.sinks import RTTMWriter
import tempfile


def diarize_with_diart(audio_path, output_rttm=None):
    """
    Chạy speaker diarization bằng Diart trên file audio.
    Trả về danh sách segment: [(start, end, speaker_label), ...]
    """
    if output_rttm is None:
        tmp_dir = tempfile.mkdtemp()
        output_rttm = os.path.join(tmp_dir, "output.rttm")
    pipeline = SpeakerDiarization()
    source = FileAudioSource(audio_path)
    inference = StreamingInference(pipeline, source)
    inference.attach_observers(RTTMWriter(source.uri, output_rttm))
    _ = inference()
    # Parse RTTM
    segments = []
    with open(output_rttm, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 8:
                start = float(parts[3])
                duration = float(parts[4])
                speaker = parts[7]
                segments.append((start, start+duration, speaker))
    return segments

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python diarization_diart.py <audio_path>")
        exit(1)
    audio_path = sys.argv[1]
    segments = diarize_with_diart(audio_path)
    for seg in segments:
        print(f"start={seg[0]:.2f}s end={seg[1]:.2f}s speaker={seg[2]}")
