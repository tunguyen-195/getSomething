from fastapi import APIRouter
from .endpoints import audio, tasks, auth
from .endpoints import cases
from .endpoints import summary
from .endpoints import audio_v2  # New modular workflow endpoints

api_router = APIRouter()

# v1 endpoints (backward compatible)
api_router.include_router(audio.router, prefix="/audio", tags=["audio"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(cases.router, prefix="/cases", tags=["cases"])
api_router.include_router(summary.router, prefix="/summaries", tags=["summaries"])

# v2 endpoints (modular workflow: Upload → Transcribe → Summarize → Visualize)
api_router.include_router(audio_v2.router, prefix="/audio/v2", tags=["audio-v2"]) 