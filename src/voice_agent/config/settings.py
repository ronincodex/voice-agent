"""Application settings loaded from environment variables.

This module uses pydantic-settings to provide type-safe configurations.
If an environment variable is missign or has the wrong type, the app will fail
at startup with a clear error message, not at 03:00 AM during a live call."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration.

    All values are loaded from environment variables.
    The .env file is loaded automatically in development.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ===== AI Service API Keys =====
    sarvam_api_key: str
    groq_api_key: str
    daily_api_key: str | None = None

    # ===== Application Defaults =====
    default_language: str = "hi-IN"

    # ===== Model Selection =====
    groq_model: str = "openai/gpt-oss-20b"
    sarvam_stt_model: str = "saaras:v3"
    sarvam_tts_model: str = "bulbul:v3"


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings.

    The @lru_cache decorator ensures settings are loaded only once,
    even if get_settings() is called from multiple modules.
    """
    return Settings()  # type: ignore[call-arg]
