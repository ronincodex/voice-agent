"""Verfiy Settings loads Supabase credentials from .env."""

from voice_agent.config.settings import get_settings


def main() -> None:
    settings = get_settings()
    assert settings.supabase_url, "SUPABASE_URL is empty"
    assert settings.supabase_url.startswith("https://"), settings.supabase_url
    assert settings.supabase_service_key, "SUPABASE_SERVICE_KEY is empty"
    assert len(settings.supabase_service_key) > 40, "Key looks too short"
    print(f"SUPABASE_URL loaded: {settings.supabase_url}")
    print(f"SERVICE_KEY length: {len(settings.supabase_service_key)} chars")


if __name__ == "__main__":
    main()
