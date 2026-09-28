"""Unit tests for the idempotency decorator."""

import asyncio
import inspect
from typing import Any

from voice_agent.config.settings import get_settings
from voice_agent.observability.idempotency import idempotent_tool
from voice_agent.state.redis_store import RedisSessionStore


class FakeFlowManager:
    """Minimal stand-in for Pipecat's FlowManager in unit tests."""

    def __init__(self, redis: RedisSessionStore, call_id: str) -> None:
        self.state: dict[str, Any] = {"redis": redis, "call_id": call_id}


# ---- Schema preservation test ----


@idempotent_tool(ttl_seconds=60)
async def sample_tool(
    flow_manager: FakeFlowManager,
    reason: str = "user_requested",
) -> tuple[dict[str, Any], None]:
    """Record a sample reason.

    Args:
        reason (str): The reason string.
    """
    return {"reason": reason}, None


def test_schema_preserved() -> None:
    """functools.wraps must preserve __doc__ and signature for Flows."""
    # __doc__ preserved
    assert sample_tool.__doc__ is not None
    assert "Record a sample reason" in sample_tool.__doc__

    # Signature preserved (inspect.signature follows __wrapped__)
    sig = inspect.signature(sample_tool)
    params = list(sig.parameters.keys())
    assert params == ["flow_manager", "reason"], f"Bad params: {params}"

    # Return annotation preserved
    assert sig.return_annotation != inspect.Signature.empty

    print("test_schema_preserved passed")


# ---- Behavioral tests ----


async def test_dedup() -> None:
    s = get_settings()
    redis = RedisSessionStore(
        url=s.upstash_redis_rest_url,
        token=s.upstash_redis_rest_token,
    )

    calls = {"n": 0}

    @idempotent_tool(ttl_seconds=60)
    async def echo(
        flow_manager: FakeFlowManager,
        value: str = "",
    ) -> tuple[dict[str, Any], None]:
        calls["n"] += 1
        return {"echoed": value, "count": calls["n"]}, None

    fm = FakeFlowManager(redis, "test_idem_002")
    await redis._redis.delete("idem:test_idem_002:echo")

    r1, _ = await echo(fm, value="hello")
    assert r1["count"] == 1
    assert calls["n"] == 1

    r2, _ = await echo(fm, value="hello")
    assert r2["count"] == 1, "Expected cached result"
    assert calls["n"] == 1, "Function should not have run twice"

    r3, _ = await echo(fm, value="world")
    assert r3["count"] == 2
    assert calls["n"] == 2

    await redis._redis.delete("idem:test_idem_002:echo")
    print("test_dedup passed")


async def main() -> None:
    test_schema_preserved()
    await test_dedup()
    print("All idempotency tests passed")


if __name__ == "__main__":
    asyncio.run(main())
