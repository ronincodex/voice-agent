"""Supabase client for persisting call records and transcripts.

Uses the service_role key for full database access from the backend.
Documentation: https://supabase.com/docs/reference/python
"""

from typing import Any, cast

from loguru import logger
from postgrest.types import CountMethod
from supabase import Client, create_client

from voice_agent.observability.retry import retry_standard


def _normalize_phone(number: str) -> str:
    """E.164 normalization matching server._normalize_phone."""
    digits = number.strip().replace(" ", "").replace("-", "")
    if not digits:
        return ""
    if digits.startswith("+"):
        return digits
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91{digits}"
    if digits.startswith("91") and len(digits) == 12:
        return f"+{digits}"
    return f"+{digits}"


class SupabaseStore:
    """Persist call data to Supabase Postgres."""

    def __init__(self, url: str, service_key: str) -> None:
        self._client: Client = create_client(url, service_key)

    @retry_standard
    async def create_call(
        self,
        call_uuid: str,
        direction: str,
        from_number: str,
        to_number: str,
        language: str,
    ) -> str:
        """Insert a new call record. Returns the internal call UUID."""
        result = (
            self._client.table("calls")
            .insert(
                {
                    "call_uuid": call_uuid,
                    "direction": direction,
                    "from_number": from_number,
                    "to_number": to_number,
                    "language": language,
                    "status": "initiated",
                }
            )
            .execute()
        )
        logger.info(f"Supabase: created call record for {call_uuid}")
        rows = cast(list[dict[str, Any]], result.data)
        return str(rows[0]["id"])

    @retry_standard
    async def save_message(
        self,
        call_id: str,
        role: str,
        text: str,
        tool_name: str | None = None,
        tool_args: dict[str, Any] | None = None,
        latency_ms: int | None = None,
    ) -> None:
        """Save a single utterance to the messages table."""
        self._client.table("messages").insert(
            {
                "call_id": call_id,
                "role": role,
                "text": text,
                "tool_name": tool_name,
                "tool_args": tool_args,
                "latency_ms": latency_ms,
            }
        ).execute()
        logger.debug(f"Supabase: saved {role} message for call {call_id}")

    @retry_standard
    async def update_call(self, call_uuid: str, **fields: Any) -> None:
        """Update a call record with any subset of fields."""
        self._client.table("calls").update(fields).eq("call_uuid", call_uuid).execute()
        logger.info(f"Supabase: updated {call_uuid} fields={list(fields.keys())}")

    @retry_standard
    async def get_call_by_uuid(self, call_uuid: str) -> dict[str, Any] | None:
        """Fetch a call record by Vobiz call UUID."""
        result = (
            self._client.table("calls").select("*").eq("call_uuid", call_uuid).execute()
        )
        rows = cast(list[dict[str, Any]], result.data)
        return rows[0] if rows else None

    @retry_standard
    async def list_calls(
        self,
        *,
        page: int = 1,
        limit: int = 20,
        direction: str | None = None,
        status: str | None = None,
        language: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Fetch a page of calls plus the total count matching filters.

        Returns (rows, total). `total` is the count across ALL pages
        matching the filter, not the size of the current page.

        Filter chaining is logical AND. Calling .eq("direction", "outbound")
        then .eq("status", "completed") matches rows where BOTH are true.

        The count uses head=True so Postgres does a COUNT(*) without
        materializing any rows. This is faster than fetching and
        counting, and avoids the 1000-row cap on the row query.
        """
        # Range is 0-based and inclusive on both ends in the Supabase
        # Python client. Page 1 with limit 20 is range(0, 19).
        start = (page - 1) * limit
        end = start + limit - 1

        query = self._client.table("calls").select(
            "call_uuid,direction,from_number,to_number,language,"
            "status,started_at,ended_at,duration_seconds,"
            "outcome,recording_url",
            count=CountMethod.exact,
        )

        if direction:
            query = query.eq("direction", direction)
        if status:
            query = query.eq("status", status)
        if language:
            query = query.eq("language", language)

        result = query.order("started_at", desc=True).range(start, end).execute()

        rows = cast(list[dict[str, Any]], result.data)
        total = result.count or 0
        return rows, total

    @retry_standard
    async def get_call_detail(self, call_uuid: str) -> dict[str, Any] | None:
        """Fetch one call plus its full transcript in one round trip.

        Returns None if no call matches the UUID. The transcript is
        fetched with a second query (Supabase does not support joining
        in a single PostgREST request without an RPC) but both queries
        run concurrently via asyncio.gather so the total latency is
        the slower of the two, not the sum.
        """
        call_query = (
            self._client.table("calls").select("*").eq("call_uuid", call_uuid).execute()
        )
        call_rows = cast(list[dict[str, Any]], call_query.data)
        if not call_rows:
            return None

        call = call_rows[0]
        internal_id = call["id"]

        transcript_query = (
            self._client.table("messages")
            .select("role,text,created_at")
            .eq("call_id", internal_id)
            .order("created_at")
            .execute()
        )
        transcript = cast(list[dict[str, Any]], transcript_query.data)

        call["messages"] = transcript
        return call

    @retry_standard
    async def get_call_counts(self) -> dict[str, int]:
        """Return the four counter values for the dashboard cards.

        Four COUNT(*) queries, each with head=True. A single round
        trip per counter is simpler to reason about than a GROUP BY
        that Supabase does not expose through the Python client
        without an RPC.
        """
        total_res = (
            self._client.table("calls")
            .select("id", count=CountMethod.exact, head=True)
            .execute()
        )
        completed_res = (
            self._client.table("calls")
            .select("id", count=CountMethod.exact, head=True)
            .eq("status", "completed")
            .execute()
        )
        failed_statuses = ["failed", "busy", "no-answer", "timeout", "cancel"]
        failed_res = (
            self._client.table("calls")
            .select("id", count=CountMethod.exact, head=True)
            .in_("status", failed_statuses)
            .execute()
        )
        in_progress_res = (
            self._client.table("calls")
            .select("id", count=CountMethod.exact, head=True)
            .in_("status", ["initiated", "ringing", "in-progress"])
            .execute()
        )

        return {
            "total": total_res.count or 0,
            "completed": completed_res.count or 0,
            "failed": failed_res.count or 0,
            "in_progress": in_progress_res.count or 0,
        }

    @retry_standard
    async def get_transcript(self, call_id: str) -> list[dict[str, Any]]:
        """Fetch all messages for a call, ordered chronologically."""
        result = (
            self._client.table("messages")
            .select("*")
            .eq("call_id", call_id)
            .order("created_at")
            .execute()
        )
        return cast(list[dict[str, Any]], result.data)

    @retry_standard
    async def check_opt_out(self, phone_number: str) -> bool:
        """Return True if the number is on the local opt-out list."""
        normalized = _normalize_phone(phone_number)
        result = (
            self._client.table("dnd_optouts")
            .select("phone_number")
            .eq("phone_number", normalized)
            .limit(1)
            .execute()
        )
        rows = cast(list[dict[str, Any]], result.data)
        return len(rows) > 0

    @retry_standard
    async def add_opt_out(
        self,
        phone_number: str,
        reason: str,
        source_call_uuid: str,
    ) -> None:
        """Add or refresh a number in the local opt-out list (idempotent)."""
        normalized = _normalize_phone(phone_number)
        self._client.table("dnd_optouts").upsert(
            {
                "phone_number": normalized,
                "reason": reason,
                "source_call_uuid": source_call_uuid,
            }
        ).execute()
        logger.info(f"Supabase: opt-out recorded for {normalized}")
