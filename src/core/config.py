from typing import List
from pydantic_settings import BaseSettings
from pydantic import AnyHttpUrl, validator

class Settings(BaseSettings):
    # Backend
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    DEBUG: bool = False
    SECRET_KEY: str = "your-super-secret-key-here"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
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
    WHISPER_MODEL: str = "large-v2"
    VOSK_MODEL_PATH: str = "models/vosk-model-vn-0.4"
    T5_MODEL_PATH: str = "models/t5-base"

    # Storage
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE: int = 100_000_000  # 100MB
    ALLOWED_EXTENSIONS: List[str] = ["wav", "mp3", "m4a", "ogg"]
    AUDIO_STORAGE_ROOT: str = "storage/audio"

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
    WHISPER_BEAM_SIZE: int = 5

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