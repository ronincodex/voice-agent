"""Compliance audit trail writer.

Every compliance-relevant event (consent, DND block, guard-rail
violation, PII masking, opt-out) is appended to Supabase's call_audit
table. Writes are fire-and-forget: a Supabase failure never breaks the
call pipeline.
"""

from typing import Any, Literal

from loguru import logger
from supabase import Client, create_client

AuditEventType = Literal[
    "consent_captured",
    "consent_declined",
    "guardrail_prompt_injection",
    "dnd_blocked",
    "calling_hours_blocked",
    "opt_out_requested",
    "pii_masked",
    "call_started",
    "call_ended",
]


class AuditTrail:
    """Append-only writer for compliance events."""

    def __init__(self, supabase_url: str, service_key: str) -> None:
        self._client: Client = create_client(supabase_url, service_key)

    async def record(
        self,
        call_uuid: str,
        event_type: AuditEventType,
        event_data: dict[str, Any] | None = None,
    ) -> None:
        """Append one audit event. Logs errors but never raises."""
        try:
            self._client.table("call_audit").insert(
                {
                    "call_uuid": call_uuid,
                    "event_type": event_type,
                    "event_data": event_data or {},
                }
            ).execute()
            logger.info(f"AuditTrail: recorded {event_type} for {call_uuid}")
        except Exception as e:
            logger.error(
                f"AuditTrail: failed to record {event_type} "
                f"for {call_uuid}: {type(e).__name__} {str(e)[:200]}"
            )
