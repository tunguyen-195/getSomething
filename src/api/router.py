from fastapi import APIRouter
from .endpoints import audio, tasks, auth
from .endpoints import cases
from .endpoints import summary

api_router = APIRouter()

api_router.include_router(audio.router, prefix="/audio", tags=["audio"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(cases.router, prefix="/cases", tags=["cases"])
api_router.include_router(summary.router, prefix="/summaries", tags=["summaries"]) 