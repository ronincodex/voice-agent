"""TRAI calling-hour enforcement.

Commercial voice calls in India are permitted between 9:00 AM and
9:00 PM IST. This module uses a 8:45 PM cutoff to leave a buffer for
in-progress calls, following Exotel's guidance.
"""

from datetime import datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
_WINDOW_START = time(9, 0)
_WINDOW_END = time(20, 45)  # 8:45 PM IST: 15-minute buffer before 9 PM


def is_within_calling_window(now_utc: datetime) -> bool:
    """Return True if the current UTC instant is within 9 AM - 8:45 PM IST."""
    ist = now_utc.astimezone(IST)
    return _WINDOW_START <= ist.time() < _WINDOW_END


def current_ist_time(now_utc: datetime) -> str:
    """Return the IST wall-clock time as HH:MM for logging and errors."""
    return now_utc.astimezone(IST).strftime("%H:%M")
