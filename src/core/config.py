from typing import List
from pydantic_settings import BaseSettings
from pydantic import AnyHttpUrl, validator

class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    # Backend
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    DEBUG: bool = False
    SECRET_KEY: str = "your-super-secret-key-here"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    AUTH_ENABLED: bool = False
    INIT_DB_ON_STARTUP: bool = False
    ENABLE_API_DOCS: bool = True
    VERSION: str = "0.1.0"
    DESCRIPTION: str = "Speech to Information API"

    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/speech_to_info"
    DATABASE_TEST_URL: str = "postgresql://postgres:postgres@localhost:5432/speech_to_info_test"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: str = "5432"
    POSTGRES_DB: str = "speech_to_info"

    # Redis
    # Khi chạy local/offline, đảm bảo Redis chạy trên localhost:6379
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""

    # Celery
    # Khi chạy local/offline, broker/backend phải là redis://localhost:6379/0
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # Model
    WHISPER_MODEL: str = "large-v3-turbo"  # Upgraded from large-v2 (6-7x faster, better accuracy)
    WHISPER_USE_LOCAL: bool = True  # Use local cached model for offline mode
    WHISPER_MODEL_PATH: str = "models/whisper"  # Local model cache directory
    WHISPER_FAST_MODE: bool = True  # Skip heavy LLM post-processing (31x speed vs 3x)
    HF_TOKEN: str = ""  # HuggingFace token for gated models (pyannote)
    VOSK_MODEL_PATH: str = "models/vosk-model-vn-0.4"
    T5_MODEL_PATH: str = "models/t5-base"

    # Language & AI Model Settings
    DEFAULT_LANGUAGE: str = "vi"  # Tiếng Việt
    DEFAULT_AI_MODEL: str = "gpt-oss"  # Model AI mặc định
    FORCE_VIETNAMESE_OUTPUT: bool = True  # Ép buộc đầu ra tiếng Việt
    PRESERVE_ORIGINAL_LANGUAGE: bool = True  # Giữ nguyên ngôn ngữ gốc trong hội thoại
    TRANSLATE_SUMMARY_TO_VIETNAMESE: bool = True  # Chỉ dịch tóm tắt sang tiếng Việt

    # Storage
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE: int = 100_000_000  # 100MB
    ALLOWED_EXTENSIONS: List[str] = ["wav", "mp3", "m4a", "ogg"]
    AUDIO_STORAGE_ROOT: str = "storage/audio"

    # Auth/session cookies
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"
    COOKIE_DOMAIN: str | None = None
    COOKIE_PATH: str = "/"
    CSRF_COOKIE_NAME: str = "csrf_token"
    AUTH_COOKIE_NAME: str = "access_token"
    TRUSTED_PROXY_IPS: List[str] = []

    # Rate limits
    RATE_LIMIT_ENABLED: bool = True
    LOGIN_RATE_LIMIT_ATTEMPTS: int = 5
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 900
    UPLOAD_RATE_LIMIT_PER_HOUR: int = 20
    PROCESS_RATE_LIMIT_PER_HOUR: int = 60

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/app.log"
    LOKI_URL: str = "http://localhost:3100"

    # Frontend
    FRONTEND_URL: str = "http://localhost:3000"
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000"]

    # API Settings
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Speech to Information"
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000"]

    # Monitoring
    PROMETHEUS_MULTIPROC_DIR: str = "/tmp/prometheus_multiproc"
    METRICS_PORT: int = 9090

    # Whisper optimization
    WHISPER_DEVICE: str = "cuda"  # "cuda" hoặc "cpu"
    WHISPER_COMPUTE_TYPE: str = "float16"  # "float16" cho GPU, "int8" cho CPU
    WHISPER_BATCH_SIZE: int = 8
    WHISPER_BEAM_SIZE: int = 10  # Increased for better Vietnamese accuracy

    @validator("CORS_ORIGINS", pre=True)
    def assemble_cors_origins(cls, v: str | List[str]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    class Config:
        case_sensitive = True
        env_file = ".env"
        env_file_encoding = 'utf-8'
        extra = "allow"
        model_config = {'protected_namespaces': ()}

settings = Settings()

def validate_security_settings() -> None:
    """Fail fast for production-grade security settings."""
    production = settings.ENVIRONMENT.lower() in {"prod", "production"} or (
        settings.AUTH_ENABLED and not settings.DEBUG
    )
    if not production:
        return

    secret = settings.SECRET_KEY or ""
    lowered = secret.lower()
    weak_markers = [
        "your-super-secret-key-here",
        "changeme",
        "change_me",
        "secret",
        "password",
        "default",
        "template",
    ]
    if (
        len(secret) < 32
        or lowered in weak_markers
        or any(marker in lowered for marker in weak_markers)
        or len(set(secret)) < 8
    ):
        raise RuntimeError(
            "Weak SECRET_KEY for production/auth-enabled mode. Generate one with: "
            "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    if not settings.COOKIE_SECURE:
        raise RuntimeError("COOKIE_SECURE must be true in production/auth-enabled mode")
    if settings.COOKIE_SAMESITE.lower() == "none" and not settings.COOKIE_SECURE:
        raise RuntimeError("SameSite=None cookies require COOKIE_SECURE=true")
