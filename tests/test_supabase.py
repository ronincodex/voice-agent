"""Round-trip test for Supabase store."""

import asyncio

from voice_agent.config.settings import get_settings
from voice_agent.db.supabase_client import SupabaseStore


async def main() -> None:
    settings = get_settings()
    store = SupabaseStore(settings.supabase_url, settings.supabase_service_key)

    # Create a test call
    call_id = await store.create_call(
        call_uuid="test_uuid_001",
        direction="outbound",
        from_number="+910000000000",
        to_number="+919999999999",
        language="hi-IN",
    )
    print(f"Created call with internal ID: {call_id}")

    # Save a message
    await store.save_message(call_id, "user", "हाँ, बताइए")
    await store.save_message(call_id, "assistant", "नमस्ते, मैं इशिता बोल रही हूँ")

    # Update the call
    await store.update_call("test_uuid_001", status="completed", duration_seconds=120)

    # Clean up
    store._client.table("calls").delete().eq("id", call_id).execute()
    print("Supabase tests passed")


if __name__ == "__main__":
    asyncio.run(main())
