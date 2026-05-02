import os
import sys

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("INIT_DB_ON_STARTUP", "false")
os.environ.setdefault("INITIAL_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-enough-length-1234567890")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

# Add the project root directory to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
