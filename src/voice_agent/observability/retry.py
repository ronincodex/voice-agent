"""Retry policies with exponential backoff for transient failures.

Only network-level and 5xx/429 HTTP errors are retried. Client errors
(4xx other than 429) are our bug, not a blip, and must fail fast.

Three presets:
  - retry_fast      : in-call operations, tight budget
  - retry_standard  : post-call I/O (Supabase, R2, Vobiz metadata)
  - retry_critical  : must-succeed, wider budget, more attempts

Usage:
    from voice_agent.observability.retry import retry_standard

    @retry_standard
    async def upload_recording(...): ...
"""

from collections.abc import Callable
from typing import Any, TypeVar

import httpx
from loguru import logger
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential_jitter,
)

T = TypeVar("T")

# HTTP statuses that warrant a retry. Everything else in the 4xx range
# is a bug in our request and must surface immediately.
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


def _is_transient(exc: BaseException) -> bool:
    """Return True if the exception represents a transient failure."""
    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUSES
    # botocore ClientError covers R2/S3 transient failures
    try:
        from botocore.exceptions import ClientError

        if isinstance(exc, ClientError):
            code = exc.response.get("Error", {}).get("Code", "")
            return code in {
                "RequestTimeout",
                "RequestTimeTooSkewed",
                "ServiceUnavailable",
                "SlowDown",
                "InternalError",
            }
    except ImportError:
        pass
    return False


def _log_retry(service: str) -> Callable[[RetryCallState], None]:
    """Build a before_sleep callback that logs each retry attempt."""

    def _hook(state: RetryCallState) -> None:
        exc = state.outcome.exception() if state.outcome else None
        attempt = state.attempt_number
        next_wait = state.next_action.sleep if state.next_action else 0.0
        logger.warning(
            f"retry_attempt service={service} attempt={attempt} "
            f"wait={round(float(next_wait), 2)}s "
            f"error={type(exc).__name__ if exc else None} "
            f"msg={str(exc)[:200] if exc else None}"
            # "retry_attempt",
            # service=service,
            # attempt=attempt,
            # wait_seconds=round(float(next_wait), 2),
            # error_class=type(exc).__name__ if exc else None,
            # error_msg=str(exc)[:200] if exc else None,
        )

    return _hook


def _make_preset(
    service: str,
    max_attempts: int,
    max_delay: float,
    initial: float,
    max_wait: float,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Build a retry decorator with the given policy."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception(_is_transient),
                stop=(stop_after_attempt(max_attempts) | stop_after_delay(max_delay)),
                wait=wait_exponential_jitter(initial=initial, max=max_wait),
                before_sleep=_log_retry(service),
                reraise=True,
            ):
                with attempt:
                    return await func(*args, **kwargs)
            # Unreachable - AsyncRetrying always either returns or raises
            raise RuntimeError("retry loop exited unexpectedly")

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator


# In-call: tight budget, small number of attempts.
# Used for anything that blocks a live caller.
retry_fast = _make_preset(
    service="in_call",
    max_attempts=3,
    max_delay=5.0,
    initial=0.3,
    max_wait=2.0,
)

# Post-call: standard I/O, more attempts but still bounded.
# Used for Supabase writes, R2 uploads, Vobiz metadata fetch.
retry_standard = _make_preset(
    service="post_call",
    max_attempts=4,
    max_delay=20.0,
    initial=0.5,
    max_wait=8.0,
)

# Critical: must succeed, wide budget. Use sparingly - only for jobs
# that cannot be safely skipped (e.g. recording persistence).
retry_critical = _make_preset(
    service="critical",
    max_attempts=6,
    max_delay=60.0,
    initial=1.0,
    max_wait=16.0,
)
