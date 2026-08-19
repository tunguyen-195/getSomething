"""
E2E Test Script for SpeechToInformation System
Tests: Upload, Transcribe, Summarize (Vistral/Qwen3), Visualize
"""
import requests
import time
import json
import os
from pathlib import Path

BASE_URL = "http://localhost:8000"
REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_AUDIO = REPO_ROOT / "storage" / "audio" / "Tiếp nhận yêu cầu đặt phòng của khách lẻ qua điện thoại.mp3"

def create_case(title: str) -> dict:
    """Create a new case for testing."""
    print(f"\n[1] Creating case: {title}")
    r = requests.post(f"{BASE_URL}/api/v1/cases", json={"title": title})
    if r.status_code == 200:
        case = r.json()
        print(f"    ✅ Created case ID: {case['id']}")
        return case
    else:
        print(f"    ❌ Failed: {r.status_code} - {r.text}")
        return None

def upload_audio(file_path: str, case_id: int) -> dict:
    """Upload audio file to a case."""
    print(f"\n[2] Uploading audio: {os.path.basename(file_path)}")
    with open(file_path, 'rb') as f:
        files = {'file': (os.path.basename(file_path), f, 'audio/mpeg')}
        data = {'case_id': str(case_id)}
        r = requests.post(f"{BASE_URL}/api/v1/audio/upload", files=files, data=data)
    
    if r.status_code == 200:
        result = r.json()
        print(f"    ✅ Uploaded | task_id: {result.get('task_id')}")
        return result
    else:
        print(f"    ❌ Failed: {r.status_code} - {r.text}")
        return None

def transcribe(task_id: str) -> dict:
    """Transcribe audio file."""
    print(f"\n[3] Transcribing task: {task_id}")
    r = requests.post(f"{BASE_URL}/api/v1/audio/transcribe/{task_id}", json={
        "enable_diarization": True,
        "diarization_method": "pyannote",
        "fast_mode": True
    })
    
    if r.status_code == 200:
        result = r.json()
        transcript = result.get('transcript', result.get('transcription', ''))
        print(f"    ✅ Transcribed | {len(transcript)} chars | Speakers: {result.get('num_speakers', 'N/A')}")
        return result
    else:
        print(f"    ❌ Failed: {r.status_code} - {r.text}")
        return None

def summarize(task_id: str, model_name: str = "vistral") -> dict:
    """Summarize transcript using specified model."""
    print(f"\n[4] Summarizing with model: {model_name}")
    r = requests.post(f"{BASE_URL}/api/v1/audio/summarize-task/{task_id}", json={
        "model_name": model_name,
        "summary_type": "investigation",
        "include_context_analysis": True
    })
    
    if r.status_code == 200:
        result = r.json()
        summary = result.get('summary', '')
        print(f"    ✅ Summarized | {len(summary)} chars | Engine: {result.get('engine', 'ollama')}")
        print(f"    Preview: {summary[:200]}...")
        return result
    else:
        print(f"    ❌ Failed: {r.status_code} - {r.text}")
        return None

def visualize(task_id: str) -> dict:
    """Generate visualization data."""
    print(f"\n[5] Generating visualization...")
    r = requests.post(f"{BASE_URL}/api/v1/audio/visualize/{task_id}", json={
        "visualization_type": "all"
    })
    
    if r.status_code == 200:
        result = r.json()
        viz = result.get('visualization_data', result)
        nodes = len(viz.get('nodes', []))
        edges = len(viz.get('edges', []))
        timeline = len(viz.get('timeline', []))
        print(f"    ✅ Visualization | Nodes: {nodes} | Edges: {edges} | Timeline: {timeline}")
        return result
    else:
        print(f"    ❌ Failed: {r.status_code} - {r.text}")
        return None

def run_full_test():
    """Run comprehensive E2E test."""
    print("="*60)
    print("   FULL SYSTEM E2E TEST - SpeechToInformation")
    print("="*60)
    
    # 1. Create case
    case = create_case("E2E Test - Hotel Booking (Vietnamese)")
    if not case:
        return False
    
    # 2. Upload audio
    upload_result = upload_audio(TEST_AUDIO, case['id'])
    if not upload_result:
        return False
    
    task_id = upload_result['task_id']
    
    # 3. Transcribe
    transcribe_result = transcribe(task_id)
    if not transcribe_result:
        return False
    
    # 4. Summarize with Vistral (Vietnamese LLM via llama.cpp)
    summary_result = summarize(task_id, "vistral")
    if not summary_result:
        print("    ⚠️ Vistral failed, trying Qwen3...")
        summary_result = summarize(task_id, "qwen3")
    
    if not summary_result:
        print("    ⚠️ Qwen3 failed, trying Ollama fallback...")
        summary_result = summarize(task_id, "gemma2:9b")
    
    # 5. Visualize
    viz_result = visualize(task_id)
    
    # Summary
    print("\n" + "="*60)
    print("   TEST RESULTS")
    print("="*60)
    print(f"   Case ID:      {case['id']}")
    print(f"   Task ID:      {task_id}")
    print(f"   Transcribe:   {'✅ PASS' if transcribe_result else '❌ FAIL'}")
    print(f"   Summarize:    {'✅ PASS' if summary_result else '❌ FAIL'}")
    print(f"   Visualize:    {'✅ PASS' if viz_result else '❌ FAIL'}")
    print("="*60)
    
    return bool(transcribe_result and summary_result)

if __name__ == "__main__":
    success = run_full_test()
    exit(0 if success else 1)
