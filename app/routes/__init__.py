"""DMS Routes Package"""
from .main import router as main_router
from .analytics import router as analytics_router
from .chat import router as chat_router
from .staff import router as staff_router
from .export import router as export_router
from .database import router as database_router

try:
    from .speech import speech_router
except ImportError:
    try:
        from .speech import router as speech_router
    except ImportError:
        from fastapi import APIRouter
        speech_router = APIRouter(prefix="/api", tags=["speech"])

from .prefs import router as prefs_router

__all__ = [
    "main_router",
    "analytics_router",
    "chat_router",
    "staff_router",
    "export_router",
    "database_router",
    "speech_router",
    "prefs_router",
]

