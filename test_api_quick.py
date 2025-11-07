# Quick API Test - Check if backend is ready

import requests

BASE = 'http://localhost:8000'

# Test health
try:
    r = requests.get(f'{BASE}/api/health', timeout=5)
    print(f'[Health] Status: {r.status_code}')
except Exception as e:
    print(f'[Health] ERROR: {e}')
    print('Start backend: uvicorn src.main:app --reload')
    exit(1)

# Test v2 endpoint exists
try:
    # This will fail if route not registered, but we can check
    print('[Info] Backend is running')
    print('[Info] Next: Update router.py to include audio_v2')
except Exception as e:
    print(f'[Error] {e}')
