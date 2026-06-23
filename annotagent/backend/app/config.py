"""Application configuration via pydantic-settings."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

# Search the nearest parent dir that has a .env (supports: annotagent/backend/.env,
# annotagent/.env, or project-root .env).
_KEY_NAMES = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")


def _env_defines_key(path: Path) -> bool:
    """True if the .env actually sets a non-empty provider key."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() in _KEY_NAMES and value.strip():
                return True
    except OSError:
        pass
    return False


def _find_env_file() -> str:
    here = Path(__file__).resolve()
    existing = [parent / ".env" for parent in here.parents if (parent / ".env").exists()]
    # Prefer the nearest .env that actually defines a provider key, so an empty
    # placeholder .env never shadows a populated one further up the tree.
    for candidate in existing:
        if _env_defines_key(candidate):
            return str(candidate)
    return str(existing[0]) if existing else ".env"


_BACKEND_DIR = Path(__file__).resolve().parent.parent  # .../annotagent/backend
# Bundled seed data lives under annotagent/assets/data/ so the demo is self-
# contained inside the annotagent/ subtree. Override via SEED_DATA_DIR env var.
_DEFAULT_SEED_DIR = (_BACKEND_DIR.parent / "assets" / "data").resolve()


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
