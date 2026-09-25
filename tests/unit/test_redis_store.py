"""Test the RedisSessionStore round-trip."""

import asyncio

from voice_agent.config.settings import get_settings
from voice_agent.state.redis_store import RedisSessionStore


async def main() -> None:
    settings = get_settings()
    store = RedisSessionStore(
        url=settings.upstash_redis_rest_url,
        token=settings.upstash_redis_rest_token,
    )
    call_id = "test_call_001"

    await store.delete(call_id)

    await store.set(call_id, {"refusal_count": 0, "pending": False})
    state = await store.get(call_id)
    assert state == {"refusal_count": 0, "pending": False}, state

    await store.update(call_id, refusal_count=2)
    state = await store.get(call_id)
    assert state is not None
    assert state["refusal_count"] == 2
    assert state["pending"] is False

    await store.delete(call_id)
    assert await store.get(call_id) is None

    print("RedisSessionStore tests passed")


if __name__ == "__main__":
    asyncio.run(main())
