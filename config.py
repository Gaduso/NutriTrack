import os

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_database_url() -> str:
    """Use the Render persistent disk at /data if it exists, otherwise local file."""
    if os.path.isdir("/data") or os.environ.get("RENDER"):
        try:
            os.makedirs("/data", exist_ok=True)
        except OSError:
            return "./nutritrack.db"
        return "/data/nutritrack.db"
    return "./nutritrack.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Secrets / configuration — set via environment variables (Render) or .env (local).
    # Never hardcode real secrets here; this file is committed to the repo.
    OPENROUTER_API_KEY: str = ""
    JWT_SECRET: str = "change-me-in-production-please-use-a-long-random-string"
    DATABASE_URL: str = _default_database_url()

    # OpenRouter
    OPENROUTER_URL: str = "https://openrouter.ai/api/v1/chat/completions"
    OPENROUTER_MODEL: str = "google/gemma-4-31b-it:free"

    # JWT
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = 365  # ~1 year, long-lived for PWA homescreen use.

    # Daily targets shown in the UI.
    DAILY_KCAL_GOAL: int = 2200
    DAILY_PROTEIN_GOAL: int = 150


settings = Settings()
