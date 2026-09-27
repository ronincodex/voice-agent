"""Vobiz REST API client.

Encapsulates all HTTP calls to Vobiz's Voice API.
Uses httpx for async HTTP requests.

Authentication: Vobiz uses X-Auth-ID and X-Auth-Token headers,
not HTTP Basic Auth like Plivo or Twilio.

Enterprise pattern: This is an Adapter. The public interface
(make_outbound_call) is provider-agnostic.
"""

from typing import Any

import httpx
from loguru import logger

from voice_agent.config.settings import get_settings
from voice_agent.observability.retry import retry_fast

settings = get_settings()


class VobizClient:
    """Client for Vobiz's Voice REST API."""

    def __init__(self) -> None:
        self._base_url = "https://api.vobiz.ai/api/v1"
        self._headers = {
            "X-Auth-ID": settings.vobiz_auth_id,
            "X-Auth-Token": settings.vobiz_auth_token,
            "Content-Type": "application/json",
        }

    @retry_fast
    async def make_outbound_call(
        self,
        to_number: str,
        answer_url: str,
        hangup_url: str | None = None,
        ring_url: str | None = None,
    ) -> dict[str, Any]:
        """Initiate an outbound call via Vobiz.

        Args:
            to_number: Destination number in E.164 format (e.g., "+919876543210").
            answer_url: URL Vobiz fetches when the call is answered.
                       Must return valid VobizXML.
            hangup_url: Optional URL Vobiz notifies when the call ends.
            ring_url: Optional URL Vobiz notifies when the call starts ringing.

        Returns:
            The Vobiz API response as a dict.
        """
        url = f"{self._base_url}/Account/{settings.vobiz_auth_id}/Call/"

        payload = {
            "from": settings.vobiz_phone_number,
            "to": to_number,
            "answer_url": answer_url,
            "answer_method": "POST",
        }

        if ring_url:
            payload["ring_url"] = ring_url
            payload["ring_method"] = "POST"
        if hangup_url:
            payload["hangup_url"] = hangup_url
            payload["hangup_method"] = "POST"

        logger.info(f"Initiating outbound call to {to_number}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=self._headers)

        if response.status_code not in (200, 201):
            logger.error(f"Vobiz API error: {response.status_code} - {response.text}")
            response.raise_for_status()

        result: dict[str, Any] = response.json()
        logger.info(f"Call initiated. request_uuid: {result.get('request_uuid')}")
        return result

    @retry_fast
    async def hangup_call(self, call_uuid: str) -> dict[str, Any]:
        """Terminate an active call via Vobiz REST API."""
        url = f"{self._base_url}/Account/{settings.vobiz_auth_id}/Call/{call_uuid}/"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.delete(url, headers=self._headers)
            logger.info(f"Hangup call {call_uuid}: {response.status_code}")
            return {"status": response.status_code}
