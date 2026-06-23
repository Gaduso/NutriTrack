from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Secrets / connection (set via environment variables; never hardcode) ---
    # PostgreSQL connection string, e.g.
    #   postgresql://user:password@host:5432/dbname
    # On Render this is provided by the database resource / dashboard env var.
    DATABASE_URL: str = ""

    OPENROUTER_API_KEY: str = ""
    JWT_SECRET: str = "change-me-in-production-please-use-a-long-random-string"

    # OpenRouter
    OPENROUTER_URL: str = "https://openrouter.ai/api/v1/chat/completions"
    OPENROUTER_MODEL: str = "google/gemma-4-31b-it:free"

    # JWT
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = 365  # ~1 year, long-lived for PWA homescreen use.

    # Default daily targets for new users.
    DAILY_KCAL_GOAL: int = 2200
    DAILY_PROTEIN_GOAL: int = 150


settings = Settings()
