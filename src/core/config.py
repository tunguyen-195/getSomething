import json
from typing import Annotated, Any, List

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


StringListSetting = Annotated[List[str], NoDecode]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",
        protected_namespaces=(),
    )

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
    APP_EDITION: str = "full"
    APP_DISPLAY_NAME: str = "Speech to Information"
    RUNTIME_PROFILE: str = "full"
    PROCESSING_RUNNER: str = "celery"
    MAX_ACTIVE_JOBS: int = 1
    LITE_JOB_LEASE_TTL_SECONDS: int = 900
    LITE_JOB_HEARTBEAT_SECONDS: int = 15
    UVICORN_RELOAD: bool = False

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
    ASR_PROVIDER: str = "cherry_whisper_v2"
    ASR_PROFILE: str = "full"
    ENABLE_DIARIZATION_DEFAULT: bool = True
    WHISPER_MODEL: str = "large-v3-turbo"  # Upgraded from large-v2 (6-7x faster, better accuracy)
    WHISPER_USE_LOCAL: bool = True  # Use local cached model for offline mode
    WHISPER_MODEL_PATH: str = "models/whisper"  # Local model cache directory
    WHISPER_FAST_MODE: bool = True  # Skip heavy LLM post-processing (31x speed vs 3x)
    WHISPER_INITIAL_PROMPT: str = (
        "Cuộc hội thoại tiếng Việt, có thể xen kẽ thuật ngữ tiếng Anh, tên riêng, "
        "số điện thoại, ngày giờ, địa chỉ và số tiền. Giữ nguyên thuật ngữ tiếng Anh khi nghe rõ."
    )
    WHISPER_HOTWORDS: str = (
        "SpeechToInformation, Speech to Information, số điện thoại, ngày mai, hôm nay, "
        "địa chỉ, khách hàng, công ty, hợp đồng, thanh toán"
    )
    WHISPER_CPP_BIN: str = "tools/whisper.cpp/whisper-cli.exe"
    WHISPER_CPP_MODEL: str = "models/asr/whisper_cpp/ggml-small-q5_0.bin"
    WHISPER_CPP_THREADS: int = 6
    WHISPER_CPP_LANGUAGE: str = "vi"
    WHISPER_CPP_TIMEOUT_SECONDS: int = 3600
    PHOWHISPER_CPP_MODEL: str = "models/asr/phowhisper_cpp/ggml-phowhisper-large-q5_0.bin"
    PHOWHISPER_CPP_SHA256: str = "1ECFF4DB87EF84AD1356D2955D2ECEA03E6C240B46FE1CA87F07EA8390E3109C"
    PHOWHISPER_CPP_SIZE_BYTES: int = 1080732108
    HF_TOKEN: str = ""  # HuggingFace token for gated models (pyannote)
    PYANNOTE_MODEL_ID: str = "pyannote/speaker-diarization-community-1"
    PYANNOTE_FALLBACK_MODEL_ID: str = "pyannote/speaker-diarization-3.1"
    PYANNOTE_CACHE_DIR: str = "models/pyannote"
    PYANNOTE_AUTO_DOWNLOAD: bool = False
    VOSK_MODEL_PATH: str = "models/vosk-model-vn-0.4"
    T5_MODEL_PATH: str = "models/t5-base"

    # Evidence-grounded analysis intelligence
    ANALYSIS_INTELLIGENCE_V2_ENABLED: bool = True
    ANALYSIS_INTELLIGENCE_LLM_ENABLED: bool = False
    ANALYSIS_CLIP_MAX_DURATION_SECONDS: int = 60
    ANALYSIS_LLM_PROVIDER: str = "ollama"  # ollama, openrouter, openai, openai_compatible, llama_cpp_server
    ANALYSIS_LLM_BASE_URL: str = "http://localhost:11434"
    ANALYSIS_LLM_MODEL: str = "gpt-oss"
    ANALYSIS_LLM_FALLBACK_MODEL: str = "gpt-4.1-mini"
    ANALYSIS_LLM_API_KEY: str = ""
    ANALYSIS_LLM_HTTP_REFERER: str = "http://localhost:3000"
    ANALYSIS_LLM_APP_TITLE: str = "SpeechToInformation"
    ANALYSIS_LLM_TIMEOUT_SECONDS: int = 60
    ANALYSIS_LLM_MAX_INPUT_CHARS: int = 24000
    ANALYSIS_LLM_MAX_OUTPUT_TOKENS: int = 2000
    ANALYSIS_LLM_DAILY_BUDGET_USD: str = ""

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
    TRUSTED_PROXY_IPS: StringListSetting = []

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
    CORS_ORIGINS: StringListSetting = ["http://localhost:3000", "http://localhost:8000"]

    # API Settings
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Speech to Information"
    BACKEND_CORS_ORIGINS: StringListSetting = ["http://localhost:3000", "http://localhost:8000"]

    # Monitoring
    PROMETHEUS_MULTIPROC_DIR: str = "/tmp/prometheus_multiproc"
    METRICS_PORT: int = 9090

    # Whisper optimization
    WHISPER_DEVICE: str = "cuda"  # "cuda" hoặc "cpu"
    WHISPER_COMPUTE_TYPE: str = "float16"  # "float16" cho GPU, "int8" cho CPU
    WHISPER_BATCH_SIZE: int = 8
    WHISPER_BEAM_SIZE: int = 10  # Increased for better Vietnamese accuracy

    @field_validator("TRUSTED_PROXY_IPS", "CORS_ORIGINS", "BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def parse_string_list_setting(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            raw_items = value
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            if text.startswith("["):
                try:
                    raw_items = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ValueError("must be a JSON list or comma-separated string") from exc
                if not isinstance(raw_items, list):
                    raise ValueError("must be a JSON list")
            else:
                raw_items = text.split(",")
        else:
            raise ValueError("must be a list or string")

        items: list[str] = []
        for item in raw_items:
            if not isinstance(item, str):
                raise ValueError("all list items must be strings")
            stripped = item.strip()
            if stripped:
                items.append(stripped)
        return items

settings = Settings()

def validate_security_settings() -> None:
    """Fail fast for production-grade security settings."""
    production = settings.ENVIRONMENT.lower() in {"prod", "production"} or (
        settings.AUTH_ENABLED and not settings.DEBUG
    )
    if not production:
        return

    if not settings.AUTH_ENABLED:
        raise RuntimeError("AUTH_ENABLED must be true in production mode")
    if settings.ENABLE_API_DOCS:
        raise RuntimeError("ENABLE_API_DOCS must be false in production mode")
    if any(origin.strip() == "*" for origin in settings.CORS_ORIGINS):
        raise RuntimeError("CORS_ORIGINS must not contain '*' in production mode")

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
