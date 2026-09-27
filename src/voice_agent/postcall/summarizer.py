"""Post-call summarisation using Sarvam 105b (flagship).

The flagship model has a 128K context window, Mixture-of-Experts
architecture (10.3B active parameters per token), and native support
for Indian languages. Batch operation, so latency is not critical.

Pricing: see https://www.sarvam.ai/pricing
A typical 3-minute call transcript is ~500 tokens -> fractions of a paisa.
"""

import json
from typing import Any

import httpx
from loguru import logger

from voice_agent.observability.retry import retry_standard

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


@retry_standard
async def generate_summary(
    api_key: str,
    transcript: str,
    model: str = "sarvam-105b",
) -> dict[str, Any]:
    """Generate a structured summary from a call transcript.

    Args:
        api_key: Sarvam API key.
        transcript: Formatted "role: text" lines for the whole call.
        model: Sarvam model name. Default is the flagship 105b.
        Uses reasoning_effort=None to disable thinking mode. Structured JSON
        output doesn not benefit from reasoning traces and they cause the model
        to return reasoning_content instead of valid JSON.

    Returns:
        Parsed dict with keys: outcome, summary, next_action.
        On parse failure, returns a safe fallback dict.
    """
    if not transcript.strip():
        logger.warning("generate_summary: empty transcript")
        return {
            "outcome": "other",
            "summary": "No transcript available.",
            "next_action": "Review recording manually.",
        }

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
                "reasoning_effort": None,  # <-- disables thinking mode
            },
        )
        if response.status_code >= 400:
            logger.error(
                f"Sarvam summary API {response.status_code}: {response.text[:500]}"
            )
        response.raise_for_status()
        payload = response.json()

    # Only read `content`. If reasoning was disabled, `reasoning_content`
    # is not populated. Reading it is a bug: reasoning text is never JSON.
    message = payload["choices"][0].get("message", {})
    # raw_content = message.get("content") or message.get("reasoning_content") or ""
    content = str(message.get("content") or "").strip()

    if not content:
        logger.error(
            f"Sarvam summary returned empty content. "
            f"finish_reason={payload['choices'][0].get('finish_reason')!r}, "
            f"full_message_keys={list(message.keys())}"
        )
        return {
            "outcome": "other",
            "summary": "Summary unavailable (empty model response).",
            "next_action": "Review recording manually.",
        }

    # Strip markdown fences if the model added them anyway
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
