"""Idempotency framework for Pipecat Flows tool handlers.

Prevents a single logical tool call from being executed twice when the
LLM invokes it multiple times within a short window. Observed in
production: the LLM calls hang_up_call twice (once from `confirm`,
once from `closing`) within ~300ms, overwriting state that the first
call had already committed.

Design (verified against current docs):
  - Key:    idem:{call_id}:{tool_name}       (Redis HASH)
  - Field:  sha256 of the tool's keyword args (short hex)
  - Value:  the serialized result of the first successful call
  - TTL:    300 seconds, refreshed on every hit

The decorator preserves the function's __doc__ and __annotations__ via
functools.wraps so Pipecat Flows' tool-schema extraction continues to
work. This is verified by a smoke test in tests/unit/test_idempotency.py.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

from loguru import logger
from pipecat.flows import FlowManager

# mypy: disable-error-code="attr-defined"

T = TypeVar("T", bound=Callable[..., Awaitable[Any]])

_DEFAULT_TTL_SECONDS = 300


def _signature(tool_name: str, kwargs: dict[str, Any]) -> str:
    """Build a stable, short signature for one invocation's arguments."""
    canonical = json.dumps(kwargs, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{tool_name}:{digest}"


def idempotent_tool(
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> Callable[[T], T]:
    """Decorator: skip duplicate executions of the same tool+args.

    Usage:
        @idempotent_tool()
        async def hang_up_call(flow_manager, reason="user_requested"):
            ...

    The wrapped function must accept flow_manager as its first
    positional argument. If flow_manager has no "redis" or "call_id"
    in state, the decorator runs the function unguarded.
    """

    def decorator(func: T) -> T:
        @wraps(func)
        async def wrapper(
            flow_manager: FlowManager,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            redis = flow_manager.state.get("redis")
            call_id = flow_manager.state.get("call_id", "unknown")

            if redis is None or call_id == "unknown":
                logger.debug(
                    f"idempotency_unguarded tool={func.__name__} "
                    f"reason={'no_redis' if redis is None else 'no_call_id'}"
                )
                return await func(flow_manager, *args, **kwargs)

            sig = _signature(func.__name__, kwargs)
            key = f"idem:{call_id}:{func.__name__}"

            cached = await redis._redis.hget(key, sig)
            if cached:
                try:
                    await redis._redis.expire(key, ttl_seconds)
                    cached_result = json.loads(cached)
                    logger.info(
                        f"tool_idempotent_skip tool={func.__name__} "
                        f"call_id={call_id} sig={sig[-8:]}"
                    )
                    return cached_result, None
                except json.JSONDecodeError:
                    logger.warning(
                        f"tool_idempotent_corrupt tool={func.__name__} "
                        f"key={key} - ignoring cache and re-running"
                    )

            result = await func(flow_manager, *args, **kwargs)

            if isinstance(result, tuple) and len(result) == 2:
                result_half, _ = result
            else:
                result_half = result

            try:
                await redis._redis.hset(key, sig, json.dumps(result_half, default=str))
                await redis._redis.expire(key, ttl_seconds)
            except Exception as e:
                logger.warning(
                    f"tool_idempotent_cache_failed tool={func.__name__} "
                    f"error={type(e).__name__} msg={str(e)[:200]}"
                )

            return result

        return wrapper  # type: ignore[return-value]

    return decorator
