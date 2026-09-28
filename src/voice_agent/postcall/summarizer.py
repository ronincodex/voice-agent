"""Post-call summarisation with Sarvam primary and Groq fallback.

Primary:  Sarvam 105b (flagship, 128K context, native Indic support)
Fallback: Groq Llama 3.3 70B (OpenAI-compatible, low latency)

Fallback is engaged only on transient transport failures. Client errors
(bad prompt, 4xx) surface immediately without invoking the fallback.
"""

import json
from typing import Any

import httpx
from loguru import logger

from voice_agent.observability.fallback import with_fallback

SUMMARY_HEADER = """Analyse this call transcript and return ONLY valid JSON
matching this exact schema:

{
  "outcome": "interested | not_interested | call_back | wrong_number | completed | other",
  "summary": "3-5 sentence natural language summary in English",
  "next_action": "concise action recommendation for the sales team"
}

Rules:
- Do NOT wrap the JSON in markdown fences.
- Do NOT include any text before or after the JSON.
- The transcript may be in Hindi, English, Tamil or a mix. The summary must be in English.
- If the caller expressed interest in a specific service, name it in the summary.
- If the caller asked to be called back later, use outcome "call_back".

Transcript:
"""

SUMMARY_FOOTER = "\n\nReturn ONLY the JSON object. No prose, no markdown."

_FALLBACK_RESULT: dict[str, Any] = {
    "outcome": "other",
    "summary": "Summary unavailable (all providers failed).",
    "next_action": "Review recording manually.",
}


def _parse_response(content: str) -> dict[str, Any]:
    """Parse the JSON body returned by either provider."""
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:].lstrip()
    try:
        result: dict[str, Any] = json.loads(content)
        logger.info(f"Summary generated: outcome={result.get('outcome')!r}")
        return result
    except json.JSONDecodeError as e:
        logger.error(f"Summary JSON parse failed: {e}\nRaw: {content[:200]}")
        return {
            "outcome": "other",
            "summary": content[:500],
            "next_action": "Manual review required (parser fallback).",
        }


async def _summarise_via_sarvam(
    api_key: str,
    transcript: str,
    model: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.sarvam.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": SUMMARY_HEADER + transcript + SUMMARY_FOOTER,
                    }
                ],
                "temperature": 0.1,
                "reasoning_effort": None,
            },
        )
        response.raise_for_status()
        payload = response.json()

    message = payload["choices"][0].get("message", {})
    return _parse_response(str(message.get("content") or ""))


async def _summarise_via_groq(
    api_key: str,
    transcript: str,
    model: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": SUMMARY_HEADER + transcript + SUMMARY_FOOTER,
                    }
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        payload = response.json()

    message = payload["choices"][0].get("message", {})
    return _parse_response(str(message.get("content") or ""))


async def generate_summary(
    api_key: str,
    transcript: str,
    model: str = "sarvam-105b",
    *,
    groq_api_key: str | None = None,
    groq_model: str = "openai/gpt-oss-120b",
    enable_fallback: bool = True,
) -> dict[str, Any]:
    """Generate a structured summary.

    Primary provider: Sarvam. Fallback: Groq. If both fail, returns the
    safe fallback dict so the call record still persists.
    """
    if not transcript.strip():
        logger.warning("generate_summary: empty transcript")
        return {
            "outcome": "other",
            "summary": "No transcript available.",
            "next_action": "Review recording manually.",
        }

    if not groq_api_key:
        # No fallback configured. Run Sarvam directly.
        return await _summarise_via_sarvam(api_key, transcript, model)

    try:
        return await with_fallback(
            primary_name="sarvam-105b",
            primary=lambda: _summarise_via_sarvam(api_key, transcript, model),
            fallback_name=f"groq-{groq_model}",
            fallback=lambda: _summarise_via_groq(groq_api_key, transcript, groq_model),
            enabled=enable_fallback,
        )
    except Exception as e:
        logger.error(f"Summary generation failed on all providers: {e}")
        return _FALLBACK_RESULT
