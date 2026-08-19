import requests
import os
import sys
from pathlib import Path

# Config
API_URL = "http://localhost:8000/api/v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
FILE_PATH = REPO_ROOT / "storage" / "audio" / "Tiếp nhận yêu cầu đặt phòng của khách lẻ qua điện thoại.mp3"
CASE_NAME = "Manual UI Test - User Simulation"

def trigger_upload():
    print(f"🚀 [USER ACTION] Creating Case: {CASE_NAME}")
    
    # 1. Create Case
    try:
        res = requests.post(f"{API_URL}/cases/", json={"title": CASE_NAME})
        res.raise_for_status()
        case_data = res.json()
        case_id = case_data['id']
        print(f"✅ Case Created: ID {case_id}")
    except Exception as e:
        print(f"❌ Failed to create case: {e}")
        sys.exit(1)

    # 2. Upload File
    print(f"🚀 [USER ACTION] Uploading File: {os.path.basename(FILE_PATH)}")
    try:
        with open(FILE_PATH, 'rb') as f:
            files = {'file': (os.path.basename(FILE_PATH), f, 'audio/mpeg')}
            res = requests.post(f"{API_URL}/upload/{case_id}", files=files)
        res.raise_for_status()
        print(f"✅ Upload Started. Go to Browser checking Case ID {case_id}")
        print(f"::set-output name=case_id::{case_id}")
    except Exception as e:
        print(f"❌ Failed to upload file: {e}")
        sys.exit(1)

if __name__ == "__main__":
    trigger_upload()
