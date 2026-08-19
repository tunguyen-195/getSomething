import requests
import time
import os
import json
from pathlib import Path

# Config
API_URL = "http://localhost:8000/api/v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
FILE_PATH = REPO_ROOT / "storage" / "audio" / "Tiếp nhận yêu cầu đặt phòng của khách lẻ qua điện thoại.mp3"
CASE_NAME = "E2E Test - Hotel Booking (Real Audio)"

def run_e2e_test():
    print(f"🚀 Starting End-to-End Test with: {os.path.basename(FILE_PATH)}")
    
    # 1. Create Case
    print("\n[1] Creating Case...")
    try:
        # Endpoint expects JSON body with 'title'
        res = requests.post(f"{API_URL}/cases/", json={"title": CASE_NAME})
        res.raise_for_status()
        case_data = res.json()
        case_id = case_data['id']
        print(f"✅ Case Created: {case_id}")
    except Exception as e:
        print(f"❌ Failed to create case: {e}")
        return

    # 2. Upload File
    print("\n[2] Uploading File...")
    start_upload = time.time()
    try:
        with open(FILE_PATH, 'rb') as f:
            files = {'file': (os.path.basename(FILE_PATH), f, 'audio/mpeg')}
            res = requests.post(
                f"{API_URL}/upload/{case_id}",
                files=files
            )
        res.raise_for_status()
        upload_data = res.json()
        print(f"✅ Upload Complete: {time.time() - start_upload:.2f}s")
    except Exception as e:
        print(f"❌ Failed to upload file: {e}")
        return

    # 3. Monitor Processing
    print("\n[3] Monitoring Processing Stages...")
    start_process = time.time()
    
    # Files endpoint to check status
    file_id = upload_data.get('id') # Or assume first file in case
    
    last_status = None
    while True:
        try:
            # Poll case status (or file status if available)
            # In V2, we usually check file status
            res = requests.get(f"{API_URL}/cases/{case_id}")
            case_info = res.json()
            
            # Find our file
            file_info = None
            if 'files' in case_info:
                for f in case_info['files']:
                    if f['filename'] == os.path.basename(FILE_PATH):
                        file_info = f
                        break
            
            if not file_info:
                print("⚠️ File not found in case...")
                time.sleep(2)
                continue
                
            status = file_info.get('status', 'unknown')
            
            if status != last_status:
                print(f"➡️ Status changed: {last_status} -> {status}")
                last_status = status
            
            if status == 'completed':
                print(f"✅ Processing Completed in {time.time() - start_process:.2f}s")
                break
            elif status == 'failed':
                print(f"❌ Processing Failed!")
                break
            
            time.sleep(1)
            
            if time.time() - start_process > 600: # 10 min timeout
                print("❌ Timeout waiting for processing")
                break
                
        except Exception as e:
            print(f"⚠️ Error polling status: {e}")
            time.sleep(2)

    # 4. Verify Results (Summary, Diarization, Analysis)
    print("\n[4] Verifying Results...")
    try:
        # Get Analysis/Summary
        res = requests.get(f"{API_URL}/api/v1/audio/v2/summary_result/{file_info['id']}")
        if res.status_code == 200:
            data = res.json()
            
            # Check Visualization Data (Structured)
            vis = data.get('visualization_data', {})
            nodes = vis.get('nodes', [])
            print(f"   - Structured Entities Found: {len(nodes)} nodes")
            
            # Check Summary
            summary = data.get('summary', '')
            print(f"   - Summary Length: {len(summary)} chars")
            
            # Check Start-Fix (Content check)
            # Simple check: does transcription start with "Dạ" or "Alo" or similar words often lost?
            transcript = data.get('transcript', '')
            print(f"   - Transcript Start: '{transcript[:50]}...'")
            
        else:
            print(f"⚠️ Could not fetch summary result: {res.status_code}")

    except Exception as e:
        print(f"❌ Error validating results: {e}")

if __name__ == "__main__":
    run_e2e_test()
