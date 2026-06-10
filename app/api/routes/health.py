"""
Health check endpoint.
"""

from fastapi import APIRouter

from app.core.config import settings
from app.core.database import database_available

router = APIRouter()


@router.get("/health")
async def health_check():
    database_ok = True if settings.demo_mode else database_available()
    return {
        "status": "ok" if database_ok else "degraded",
        "service": "conflux",
        "version": settings.app_version,
        "demo_mode": settings.demo_mode,
        "database": "available" if database_ok else "unavailable",
    }
