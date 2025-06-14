import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

from src.core.config import settings

def setup_logging():
    # Create logs directory if it doesn't exist
    log_dir = Path(settings.LOG_FILE).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    # Configure logging
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            RotatingFileHandler(
                settings.LOG_FILE,
                maxBytes=10_000_000,  # 10MB
                backupCount=5,
                encoding='utf-8',  # Thêm encoding UTF-8 để hỗ trợ Unicode
            ),
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Set log levels for specific modules
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("fastapi").setLevel(logging.INFO)
    logging.getLogger("celery").setLevel(logging.INFO)

    # Create logger
    logger = logging.getLogger(__name__)
    logger.info("Logging setup completed")

    return logger

logger = setup_logging() 