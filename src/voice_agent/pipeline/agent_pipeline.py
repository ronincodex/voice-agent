"""Core Pipecat pipeline for the multilingual voice agent.

This module constructs the STT -> LLM -> TTS pipeline that powers
the voice agent. It is the equivalent of the "Agent Core" layer
in the enterprise architecture diagram, but adapted for real-time
voice rather than text-based workflows.

Compatible with Pipecat 1.x (universal LLMContext API).
"""

from typing import Any

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.transports.daily.transport import DailyParams, DailyTransport

from voice_agent.config.languages import get_language_config
from voice_agent.config.settings import get_settings

settings = get_settings()


async def create_agent_pipeline(
    room_url: str,
    language_code: str = "hi-IN",
    system_prompt: str | None = None,
) -> PipelineTask:
    """Create and configure the voice agent pipeline.

    Args:
        room_url: The Daily room URL for WebRTC transport.
        language_code: BCP-47 language code (e.g., "hi-IN").
        system_prompt: Optional custom system prompt for the LLM.

    Returns:
        A configured PipelineTask ready to be run.
    """
    lang_config = get_language_config(language_code)
    logger.info(f"Creating pipeline for language: {lang_config.name}")

    # ===== 1. Transport Layer =====
    # In Pipecat 1.x, VAD is NOT configured here anymore.
    # It is configured on the user aggregator (see step 5).
    transport = DailyTransport(
        room_url=room_url,
        token=None,
        bot_name="AI Assistant",
        params=DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    )

    # ===== 2. Speech-to-Text (Sarvam AI) =====
    stt = SarvamSTTService(
        api_key=settings.sarvam_api_key,
        settings=SarvamSTTService.Settings(
            model=settings.sarvam_stt_model,
            language=lang_config.stt_locale,
        ),
    )

    # ===== 3. LLM (Groq) =====
    base_instruction = system_prompt or DEFAULT_SYSTEM_PROMPT
    composed_instruction = lang_config.get_system_prompt(base_instruction)

    llm = GroqLLMService(
        api_key=settings.groq_api_key,
        settings=GroqLLMService.Settings(
            model=settings.groq_model,
            system_instruction=composed_instruction,
        ),
    )

    # ===== 4. Text-to-Speech (Sarvam AI) =====
    tts = SarvamTTSService(
        api_key=settings.sarvam_api_key,
        settings=SarvamTTSService.Settings(
            model=settings.sarvam_tts_model,
            voice=lang_config.tts_voice,
            language=lang_config.tts_language_code,
        ),
    )

    # ===== 5. Context & Aggregators (Pipecat 1.x Universal API) =====
    # LLMContext is the universal context container. It works with
    # any LLM provider, so you can swap Groq for another provider
    # without changing this code.
    context = LLMContext()

    # VAD now lives on the user aggregator, NOT the transport.
    # This is the Pipecat 1.x pattern for interruption handling.
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    # ===== 6. Pipeline Construction =====
    # Note: user_aggregator and assistant_aggregator are now separate
    # processors, not .user() / .assistant() methods on a single object.
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    # ===== 7. Pipeline Task =====
    # allow_interruptions has been removed in Pipecat 1.x.
    # Interruption is controlled by the VAD + user mute strategy.
    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    # ===== 8. Greeting Handler =====
    # When a paticipant (the human) joins the room, make the agent speak
    # the greeting first. This is the "proactive opening line" required
    # based upon the project brief.

    @transport.event_handler("on_client_connected")  # type: ignore[misc]
    async def on_client_connected(transport: Any, client: Any) -> None:
        logger.info(f"Participant joined - sending greeting in {lang_config.name}.")
        await task.queue_frames([TTSSpeakFrame(lang_config.get_greeting())])

    return task


DEFAULT_SYSTEM_PROMPT = """You are a friendly, professional AI voice assistant.
Your goal is to have a natural, helpful conversation.

Guidelines:
- Keep responses concise and conversational. Aim for 1-3 sentences.
- Never use markdown, bullet points, or numbered lists in your responses.
- If you don't understand something, ask for clarification naturally.
- Be warm and empathetic in your tone.
- If the user asks a question you cannot answer, politely say so.
"""
