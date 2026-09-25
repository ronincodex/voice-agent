"""Redis-backed session state for Pipecat Flows.

Replaces the in-memory CallSessionState with a Redis-backed
version that survives process restarts.

Uses Upstash Redis (Serverless pay-per-request).
Documentation: https://upstash.com/docs/redis/sdks/py/gettingstarted"""

import json
from typing import Any

from loguru import logger
from upstash_redis.asyncio import Redis


class RedisSessionStore:
    """Persistent session state backed by Upstash Redis.

    Each call gets its own Redis key with a 1-hour TTL
    matching the maximum call duration.

    Example:
        store = RedisSessionStore(url, token)
        await store.update("call_123, refusal_count=2)
        state = await store.get("call_123")
        # state === {"refusal_count: 2}
    """

    def __init__(self, url: str, token: str, ttl_seconds: int = 3600) -> None:
        self._redis = Redis(url=url, token=token)
        self._ttl = ttl_seconds

    def _key(self, call_id: str) -> str:
        """Build the Redis key for a call."""
        return f"session:{call_id}"

    async def get(self, call_id: str) -> dict[str, Any] | None:
        """Load full session state. Return None if no session exists."""
        data = await self._redis.hgetall(self._key(call_id))
        if not data:
            return None
        result: dict[str, Any] = {}
        for k, v in data.items():
            if not isinstance(v, str):
                result[k] = v
                continue
            try:
                result[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                result[k] = v
        return result

    async def set(self, call_id: str, state: dict[str, Any]) -> None:
        """Save the full session state and refresh the TTL."""
        serialized = {
            k: json.dumps(v) if not isinstance(v, str) else v for k, v in state.items()
        }
        await self._redis.hset(self._key(call_id), values=serialized)
        await self._redis.expire(self._key(call_id), self._ttl)
        logger.debug(f"Redis: saved session {call_id}")

    async def update(self, call_id: str, **kwargs: Any) -> None:
        """Update specific fields without touching the rest."""
        serialized = {
            k: json.dumps(v) if not isinstance(v, str) else v for k, v in kwargs.items()
        }

        await self._redis.hset(self._key(call_id), values=serialized)
        await self._redis.expire(self._key(call_id), self._ttl)
        logger.debug(f"Redis: updated {call_id} fields={list(kwargs.keys())}")

    async def delete(self, call_id: str) -> None:
        """Remove the session entirely (called on hangup)."""
        await self._redis.delete(self._key(call_id))
        logger.debug(f"Redis: deleted session {call_id}")
