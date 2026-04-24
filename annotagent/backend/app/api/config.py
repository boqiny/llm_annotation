"""Config API — reports backend-loaded settings to the frontend (no secrets)."""
from __future__ import annotations

from fastapi import APIRouter

from app.config import settings

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
async def get_config():
    """Non-sensitive config surface: which providers have an env-loaded key."""
    return {
        "openai_key_loaded": bool(settings.OPENAI_API_KEY),
        "anthropic_key_loaded": bool(settings.ANTHROPIC_API_KEY),
        "max_concurrency": settings.MAX_CONCURRENCY,
    }
