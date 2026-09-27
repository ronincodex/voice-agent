"""Structured JSON logging configuration.

Loguru writes JSON lines (serialize=True).
structlog's contextvars carry the per-call correlation ID.
A Loguru patcher injects that context into every record's `extra` field.

Why this design:
  - Loguru remains the single sink (no structlog/stdlib logging interop).
  - `bind_call_context(call_id)` uses structlog contextvars, which are
    coroutine-local and propagate into child tasks automatically.
  - The patcher runs on every log call, so `call_id` appears on every
    line without callers having to pass it explicitly.
"""

import sys
from typing import Any

import structlog
from loguru import logger as loguru_logger


def _inject_contextvars(record: Any) -> None:
    """Loguru patcher: copy structlog contextvars into record["extra"].

    Loguru's serialize=True bypasses structlog's processor chain, so
    merge_contextvars never sees Loguru records. This patcher bridges the
    two: every Loguru record gets the current call_id attached before
    serialization. The parameter is typed Any because Loguru's internal
    Record type is not part of its public stub surface.
    """
    ctx = structlog.contextvars.get_contextvars()
    if ctx:
        extra = record.get("extra")
        if isinstance(extra, dict):
            extra.update(ctx)


def configure_logging(level: str = "INFO") -> None:
    """Configure Loguru to emit single-line JSON to stdout.

    Call once at application import time, before importing any module
    that logs.
    """
    # 1. Bind a structlog logger (used only for its contextvars API)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        cache_logger_on_first_use=True,
    )

    # 2. Configure Loguru: JSON sink + contextvars patcher
    loguru_logger.remove()
    loguru_logger.configure(patcher=_inject_contextvars)
    loguru_logger.add(
        sys.stdout,
        level=level,
        serialize=True,
        backtrace=False,
        diagnose=False,
        enqueue=False,
    )


def bind_call_context(call_id: str) -> None:
    """Bind `call_id` to all subsequent log lines in this task.

    Uses structlog contextvars so the binding is coroutine-local and
    automatically propagates into child tasks created by asyncio.
    """
    structlog.contextvars.bind_contextvars(call_id=call_id)


def unbind_call_context() -> None:
    """Clear the bound call context. Call in the finally block."""
    structlog.contextvars.clear_contextvars()
