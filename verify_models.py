
import sys
import os
sys.path.append(os.getcwd())

try:
    from src.database.models.models import Task, AudioFile
    print("✅ Models imported successfully")
except ImportError as e:
    print(f"❌ Models import failed: {e}")
except Exception as e:
    print(f"❌ Error: {e}")
