import requests
import json
import sys

BASE_URL = "http://localhost:8000"

def check_sorting():
    print("re-checking sorting...")
    # Test Title ASC
    try:
        r = requests.get(f"{BASE_URL}/api/v1/cases?sort_by=title&order=asc")
        if r.status_code == 200:
            cases = r.json()
            titles = [c['title'].lower() for c in cases if c['title']]
            if titles == sorted(titles):
                print(f"[OK] Title ASC: {titles[:3]}...")
            else:
                print(f"[FAIL] Title ASC: {titles[:3]}...")
        else:
            print(f"[FAIL] API Error: {r.status_code}")
    except Exception as e:
         print(f"[FAIL] Exception: {e}")

def check_models():
    print("\nChecking available models in Backend...")
    try:
        # LLM Manager is lazy loaded, but we can list via Ollama directly or assume if list worked
        # We will try a dry-run summary (mock) or just check API endpoint if exists
        # Actually, let's just check if deepseek-r1 works via a direct generate call if possible, 
        # but the backend exposes endpoints.
        pass
    except:
        pass

if __name__ == "__main__":
    check_sorting()
    # Summary check is hard without an audio file, skipping for now as UI is the main verification point
