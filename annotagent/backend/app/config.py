"""Application configuration via pydantic-settings."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

# Search the nearest parent dir that has a .env (supports: annotagent/backend/.env,
# annotagent/.env, or project-root .env).
def _find_env_file() -> str:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / ".env"
        if candidate.exists():
            return str(candidate)
    return ".env"


_BACKEND_DIR = Path(__file__).resolve().parent.parent  # .../annotagent/backend
# Widened to project-root /data so seed entries can reference any subfolder
# (cleaned/ for gold + reference, test/cleaned/ for unseen test sets).
_DEFAULT_SEED_DIR = (_BACKEND_DIR.parent.parent / "data").resolve()


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./annotagent.db"
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000", "http://localhost:8080"]
    SECRET_KEY: str = "change-me-in-production"
    MAX_CONCURRENCY: int = 10
    SEED_DATA_DIR: str = str(_DEFAULT_SEED_DIR)

    model_config = {"env_file": _find_env_file(), "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()


def resolve_api_key(provider: str, project_key: str = "") -> str:
    """Return the API key to use: project key if set, else environment fallback."""
    if project_key:
        return project_key
    p = (provider or "").lower()
    if p == "anthropic":
        return settings.ANTHROPIC_API_KEY
    return settings.OPENAI_API_KEY
