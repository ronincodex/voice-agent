"""Round-trip test for the audit trail."""

import asyncio
from typing import Any, cast

from voice_agent.config.settings import get_settings
from voice_agent.db.audit import AuditTrail


async def main() -> None:
    s = get_settings()
    audit = AuditTrail(s.supabase_url, s.supabase_service_key)

    call_uuid = "test-audit-001"

    # Clean up any prior test data
    audit._client.table("call_audit").delete().eq("call_uuid", call_uuid).execute()

    # Write three events
    await audit.record(call_uuid, "call_started")
    await audit.record(call_uuid, "consent_captured", {"version": "v1"})
    await audit.record(call_uuid, "call_ended", {"duration": 45})

    # Read back in insertion order
    result = (
        audit._client.table("call_audit")
        .select("*")
        .eq("call_uuid", call_uuid)
        .order("created_at")
        .execute()
    )
    rows = cast(list[dict[str, Any]], result.data)
    assert len(rows) == 3, f"Expected 3 rows, got {len(rows)}"
    assert rows[0]["event_type"] == "call_started"
    assert rows[1]["event_type"] == "consent_captured"
    event_data = cast(dict[str, Any], rows[1]["event_data"])
    assert event_data["version"] == "v1"
    assert rows[2]["event_type"] == "call_ended"

    # Clean up
    audit._client.table("call_audit").delete().eq("call_uuid", call_uuid).execute()
    print("Audit trail tests passed")


if __name__ == "__main__":
    asyncio.run(main())
