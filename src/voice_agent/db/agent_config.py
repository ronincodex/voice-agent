"""Read and write the singleton agent configuration row.

The config is read on every call (create_agent_pipeline) and written
by PUT /agents/config. Reads are cached for a short window so a burst
of simultaneous calls does not produce a Supabase round trip each.
Writes invalidate the cache immediately, so the next call always sees
the change.

Why not functools.lru_cache: decorating an async function caches the
coroutine object, not its resolved value. The second caller would
await the same already-consumed coroutine and get a RuntimeError.
A module-level variable with a timestamp is the correct async-safe
pattern.
"""

import time
from datetime import UTC, datetime
from typing import Any, cast

from loguru import logger
from supabase import Client, create_client

from voice_agent.observability.retry import retry_standard

# Cache window. 60 seconds is short enough that an operator who saves
# a change and immediately places a test call sees the change, and
# long enough that a hundred simultaneous calls produce one read.
_CACHE_TTL_SECONDS = 60

_cached_config: dict[str, Any] | None = None
_cached_at: float = 0.0


def invalidate_config_cache() -> None:
    """Force the next read to hit Supabase.

    Called by the PUT handler after a successful write. Also called by
    the startup hook so the first call after a deploy always reads
    fresh.
    """
    global _cached_config, _cached_at
    _cached_config = None
    _cached_at = 0.0
    logger.debug("agent_config cache invalidated")


class AgentConfigStore:
    """Read/write the agent_configs singleton."""

    def __init__(self, url: str, service_key: str) -> None:
        self._client: Client = create_client(url, service_key)

    @retry_standard
    async def get(self, *, use_cache: bool = True) -> dict[str, Any]:
        """Return the config row, using the module cache if fresh.

        Returns the seeded defaults if the row is somehow missing.
        The seeding INSERT in schema.sql guarantees a row, so a
        missing row means something is very wrong, we log loudly
        and return a valid default rather than 500 on every call.
        """
        global _cached_config, _cached_at

        if use_cache and _cached_config is not None:
            age = time.monotonic() - _cached_at
            if age < _CACHE_TTL_SECONDS:
                return _cached_config

        result = (
            self._client.table("agent_configs")
            .select("*")
            .eq("config_key", "default")
            .limit(1)
            .execute()
        )
        # supabase-py types result.data as list[JSON], a union type.
        # Cast to the concrete shape we know from the schema. Same
        # pattern as db/supabase client.py
        rows = cast(list[dict[str, Any]], result.data or [])
        if not rows:
            logger.error(
                "agent_configs has no 'default' row. Seed row missing. "
                "Returning in-code defaults."
            )
            return _DEFAULT_CONFIG

        _cached_config = rows[0]
        _cached_at = time.monotonic()
        return _cached_config

    @retry_standard
    async def upsert(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Write the config row and invalidate the cache.

        upsert() with on_conflict='config_key' produces
        INSERT ... ON CONFLICT (config_key) DO UPDATE, so a second
        call with the same key updates in place. Returns the row as
        stored so the caller can echo it back to the frontend.
        """
        # Set updated_at explicitly. The schema's DEFAULT now() fires
        # on INSERT only; ON CONFLICT DO UPDATE touches only columns
        # present in the SET clause, and Supabase's upsert builds that
        # clause from the row we send. Without an explicit value here,
        # updated_at would stay at whatever it was on the very first
        # insert, and the frontend's "last updated" would be wrong.

        row = {
            "config_key": "default",
            **payload,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        result = (
            self._client.table("agent_configs")
            .upsert(row, on_conflict="config_key")
            .execute()
        )
        invalidate_config_cache()
        rows = cast(list[dict[str, Any]], result.data or [])
        if not rows:
            raise RuntimeError("agent_configs upsert returned no row")
        logger.info(
            f"agent_config updated: agent={rows[0].get('agent_name')!r} "
            f"languages={rows[0].get('supported_languages')}"
        )
        return rows[0]


# Minimal fallback so a missing seed row does not break every call.
# Must contain every key create_agent_pipeline reads.
_DEFAULT_CONFIG: dict[str, Any] = {
    "config_key": "default",
    "agent_name": "Priya",
    "company_name": "IT-Webhut",
    "company_info": "",
    "objective": "Qualify inbound leads and schedule follow-ups.",
    "personality": "Professional, friendly, empathetic and conversational.",
    "greeting_template": (
        "Hello! I'm {name} calling from {company}. Is this a good time to speak?"
    ),
    "max_call_duration_seconds": 600,
    "primary_language": "en-IN",
    "supported_languages": ["hi-IN", "en-IN", "ta-IN"],
    "voice_overrides": {},
    "persona_gender": "female",
    "updated_at": None,
}
