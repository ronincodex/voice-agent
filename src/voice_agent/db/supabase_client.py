"""Supabase client for persisting call records and transcripts.

Uses the service_role key for full database access from the backend.
Documentation: https://supabase.com/docs/reference/python
"""

from typing import Any, cast

from loguru import logger
from supabase import Client, create_client


class SupabaseStore:
    """Persist call data to Supabase Postgres."""

    def __init__(self, url: str, service_key: str) -> None:
        self._client: Client = create_client(url, service_key)

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

    async def update_call(self, call_uuid: str, **fields: Any) -> None:
        """Update a call record with any subset of fields."""
        self._client.table("calls").update(fields).eq("call_uuid", call_uuid).execute()
        logger.info(f"Supabase: updated {call_uuid} fields={list(fields.keys())}")

    async def get_call_by_uuid(self, call_uuid: str) -> dict[str, Any] | None:
        """Fetch a call record by Vobiz call UUID."""
        result = (
            self._client.table("calls").select("*").eq("call_uuid", call_uuid).execute()
        )
        rows = cast(list[dict[str, Any]], result.data)
        return rows[0] if rows else None

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
