from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.auth import get_current_user
from src.database.config.database import get_db
from src.database.models.models import User
from src.services.lite_runtime import get_active_lease
from src.services.summarization.models.llm_manager import llm_provider_configured
from src.services.transcription.asr_providers import provider_health


router = APIRouter()


@router.get("/runtime-profile")
async def runtime_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    active_lease = get_active_lease(db)
    llm_configured = llm_provider_configured()
    return {
        "edition": settings.APP_EDITION,
        "display_name": settings.APP_DISPLAY_NAME,
        "runtime_profile": settings.RUNTIME_PROFILE,
        "processing_runner": settings.PROCESSING_RUNNER,
        "max_active_jobs": settings.MAX_ACTIVE_JOBS,
        "active_job": active_lease,
        "asr": provider_health(),
        "llm": {
            "provider": settings.ANALYSIS_LLM_PROVIDER,
            "model": settings.ANALYSIS_LLM_MODEL,
            "fallback_model": settings.ANALYSIS_LLM_FALLBACK_MODEL,
            "configured": llm_configured,
            "local_base_url": settings.ANALYSIS_LLM_BASE_URL
            if settings.ANALYSIS_LLM_PROVIDER in {"ollama", "llama_cpp_server"}
            else None,
        },
    }


@router.get("/jobs/active")
async def active_job(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {"active_job": get_active_lease(db)}
