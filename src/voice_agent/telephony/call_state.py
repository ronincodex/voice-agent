"""In-memory call state manager for tracing call lifecycles."""

from datetime import UTC, datetime
from typing import Any, Literal

CallStatus = Literal[
    "initiated",
    "ringing",
    "in-progress",
    "completed",
    "no-answer",
    "busy",
    "failed",
    "timeout",
    "cancel",
]


class CallState:
    """Tracks the lifecycle of a single outbound call."""

    def __init__(self, call_uuid: str, to_number: str, language: str):
        self.call_uuid = call_uuid
        self.to_number = to_number
        self.language = language
        self.status: CallStatus = "initiated"
        self.created_at = datetime.now(UTC)
        self.answered_at: datetime | None = None
        self.ended_at: datetime | None = None
        self.failure_reason: str | None = None

    def mark_ringing(self) -> None:
        self.status = "ringing"

    def mark_answered(self) -> None:
        self.status = "in-progress"
        self.answered_at = datetime.now(UTC)

    def mark_ended(self, status: CallStatus, reason: str | None = None) -> None:
        self.status = status
        self.ended_at = datetime.now(UTC)
        self.failure_reason = reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_uuid": self.call_uuid,
            "to_number": self.to_number,
            "language": self.language,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "answered_at": (self.answered_at.isoformat() if self.answered_at else None),
            "ended_at": (self.ended_at.isoformat() if self.ended_at else None),
            "failure_reason": self.failure_reason,
        }


# Module-level registry (replace with Redis in Production)
_active_calls: dict[str, CallState] = {}


def register_call(call_uuid: str, to_number: str, language: str) -> CallState:
    """Register a new call and return its state object."""
    state = CallState(call_uuid, to_number, language)
    _active_calls[call_uuid] = state
    return state


def get_call(call_uuid: str) -> CallState | None:
    """Return the state object for a call, or None if not registered."""
    return _active_calls.get(call_uuid)


def remove_call(call_uuid: str) -> None:
    """Remove a call from the registry."""
    _active_calls.pop(call_uuid, None)


def list_active_calls() -> list[CallState]:
    """Return all currently registered calls."""
    return list(_active_calls.values())
