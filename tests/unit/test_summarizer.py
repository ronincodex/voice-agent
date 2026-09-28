"""Test the AI summariser with a sample transcript."""

import asyncio

from voice_agent.config.settings import get_settings
from voice_agent.postcall.summarizer import generate_summary

SAMPLE = """\
assistant: नमस्ते! मैं IT-Webhut से इशिता बोल रही हूँ। क्या अभी बात करने का सही समय है?
user: हाँ बताइए।
assistant: हम website development, cloud support और digital marketing जैसी services provide करते हैं। इनमें से आप किस area में interested हैं?
user: मुझे website development में interest है।
assistant: बहुत बढ़िया! क्या आप थोड़ा और detail share कर सकते हैं?
user: मैं अभी busy हूँ, कल call कर लीजिए।
assistant: बिल्कुल, मैं कल दोबारा call कर लूँगी। धन्यवाद!
"""


async def main() -> None:
    s = get_settings()

    # Test 1: Sarvam healthy, fallback configured but unused
    print("--- Test 1: happy path ---")
    result = await generate_summary(
        api_key=s.sarvam_api_key,
        transcript=SAMPLE,
        groq_api_key=s.groq_api_key,
        groq_model=s.groq_llm_model,
        enable_fallback=True,
    )
    print(f"Outcome: {result['outcome']}")
    print(f"Summary: {result['summary'][:120]}...")
    # print(f"Next action: {result['next_action']}")

    assert result["outcome"] in (
        "interested",
        "not_interested",
        "call_back",
        "wrong_number",
        "completed",
        "other",
    ), f"Unexpected outcome: {result['outcome']}"


if __name__ == "__main__":
    asyncio.run(main())
