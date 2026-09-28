"""Generic fallback helper for batch operations.

Batch HTTP calls (summariser, post-call processing) can try a primary
provider and fall back to a secondary provider on transient transport
failures. This module does not handle real-time pipeline fallback —
see docs/fallback-design.md for the Tier 2 plan.
"""

from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
from loguru import logger

T = TypeVar("T")

# Transient errors that justify a provider switch. Business logic
# errors (bad prompt, 4xx) must NOT be retried — they will fail the
# same way on the fallback provider and should surface immediately.
_FALLBACK_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TimeoutError,
    ConnectionError,
    httpx.TransportError,
    httpx.TimeoutException,
)


async def with_fallback(
    primary_name: str,
    primary: Callable[[], Awaitable[T]],
    fallback_name: str,
    fallback: Callable[[], Awaitable[T]],
    *,
    enabled: bool = True,
) -> T:
    """Run primary; on transient failure, run fallback.

    Args:
        primary_name:  Human label for logs, e.g. "sarvam-105b".
        primary:       Zero-arg coroutine returning T.
        fallback_name: Human label for logs, e.g. "groq-llama-3.3-70b".
        fallback:      Zero-arg coroutine returning T.
        enabled:       If False, run primary only and let exceptions propagate.

    Returns:
        The value returned by whichever provider succeeded.

    Raises:
        The primary exception if fallback is disabled or the fallback
        also raises a _FALLBACK_EXCEPTIONS. Business logic errors from
        the primary always propagate without invoking the fallback.
    """
    try:
        result = await primary()
        return result
    except _FALLBACK_EXCEPTIONS as exc:
        if not enabled:
            logger.error(
                f"primary_failed fallback_disabled "
                f"provider={primary_name} "
                f"error={type(exc).__name__} "
                f"msg={str(exc)[:200]}"
            )
            raise
        logger.warning(
            f"fallback_triggered "
            f"from={primary_name} to={fallback_name} "
            f"error={type(exc).__name__} "
            f"msg={str(exc)[:200]}"
        )
        result = await fallback()
        logger.info(f"fallback_success provider={fallback_name}")
        return result
