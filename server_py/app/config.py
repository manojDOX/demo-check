from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core
    DATABASE_URL: str
    SESSION_SECRET: str = "dev-session-secret-change-me"
    FERNET_KEY: str = ""
    PORT: int = 5000
    NODE_ENV: str = "development"

    # Replit OIDC
    ISSUER_URL: str = "https://replit.com/oidc"
    REPL_ID: str = ""

    # Local dev auth bypass (see app/modules/auth) — NEVER enabled in Replit deployment
    DEV_AUTH_BYPASS: bool = False
    DEV_AUTH_USER_EMAIL: str = "dev@example.com"

    # OpenAI (Replit AI Integrations proxy) — used by recommendation flow, audio, image
    AI_INTEGRATIONS_OPENAI_API_KEY: str = ""
    AI_INTEGRATIONS_OPENAI_BASE_URL: str = ""

    # Email
    RESEND_API_KEY: str = ""
    APP_URL: str = ""
    REPLIT_DEPLOYMENT_URL: str = ""

    # GoHighLevel
    GHL_API_KEY: str = ""
    GHL_LOCATION_ID: str = ""
    WEBHOOK_SECRET: str = ""

    # Object storage
    PUBLIC_OBJECT_SEARCH_PATHS: str = ""
    PRIVATE_OBJECT_DIR: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
