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

    # ===== Telephony: Voibz =====
    vobiz_auth_id: str = ""
    vobiz_auth_token: str = ""
    vobiz_phone_number: str = ""
    # plivo_auth_id: str = ""
    # plivo_auth_token: str = ""
    # plivo_phone_number: str = "" # The US number, e.g., "+1415lXXXXXXX"
    # twilio_api_key: str = ""      # Optional: API Key SID (starts with SK)
    # twilio_api_secret: str = ""   # Optional: API Key Secret
    # exotel_api_key: str = ""
    # exotel_api_token: str = ""
    # exotel_account_sid: str = ""
    # exotel_phone_number: str = ""
    # exotel_subdomain: str = "api.exotel.com"
    # exotel_flow_app: str = "" # The ~appid~ from the Exotel flow

    # ===== Application Defaults =====
    default_language: str = "hi-IN"

    # ===== Model Selection =====
    sarvam_llm_model: str = "sarvam-105b-conversations"
    sarvam_stt_model: str = "saaras:v3"
    sarvam_stt_mode: str = "codemix"
    sarvam_tts_model: str = "bulbul:v3"

    # ===== Redis (Upstash) ======
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""

    # ====== Database (Supabase) ======
    supabase_url: str = ""
    supabase_service_key: str = ""

    # ====== Storage (Cloudflare R2) ======
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "voice-recordings"


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings.

    The @lru_cache decorator ensures settings are loaded only once,
    even if get_settings() is called from multiple modules.
    """
    return Settings()  # type: ignore[call-arg]
