"""Core Pipecat pipeline for the multilingual voice agent.

This module constructs the STT -> LLM -> TTS pipeline that powers
the voice agent. It is the equivalent of the "Agent Core" layer
in the enterprise architecture diagram, but adapted for real-time
voice rather than text-based workflows.

Compatible with Pipecat 1.x (universal LLMContext API).
"""

import asyncio
import time
from typing import Any

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    EndTaskFrame,
    Frame,
    TranscriptionFrame,
    TTSSpeakFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService

from voice_agent.config.languages import get_language_config
from voice_agent.config.settings import get_settings

settings = get_settings()


class TranscriptionDeduplicator(FrameProcessor):
    """Suppress consecutive identical transcriptions within a time window.

    Sarvam STT occasionally emits the same transcription twice for a single
    utterance when VAD fires multiple start events. This processor filters
    duplicates so the LLM context stays clean.
    """

    def __init__(self, window_seconds: float = 2.0) -> None:
        super().__init__()
        self._window = window_seconds
        self._last_transcript: str | None = None
        self._last_time: float = 0.0

    async def process_frame(
        self,
        frame: Frame,
        direction: FrameDirection,
    ) -> None:
        if isinstance(frame, TranscriptionFrame):
            now = time.monotonic()
            if (
                frame.text == self._last_transcript
                and now - self._last_time < self._window
            ):
                logger.debug(f"Deduplicated transcript: {frame.text}")
                return
            self._last_transcript = frame.text
            self._last_time = now
        await self.push_frame(frame, direction)


async def create_agent_pipeline(
    transport: Any,
    language_code: str = "hi-IN",
    system_prompt: str | None = None,
    audio_out_sample_rate: int = 24000,
) -> PipelineTask:
    """Create and configure the voice agent pipeline.

    Args:
        transport: A Pipecat transport instance (Daily, Exotel, etc.)
        language_code: BCP-47 language code (e.g., "hi-IN").
        system_prompt: Optional custom system prompt for the LLM.

    Returns:
        A configured PipelineTask ready to be run.
    """
    lang_config = get_language_config(language_code)
    logger.info(f"Creating pipeline for language: {lang_config.name}")

    # ===== 1. Transport Layer =====
    # The transport is INJECTED by the caller (run local_agent.py or server.py).
    # This is the Dependency Injection pattern: the pipeline does not
    # know whether it is talking to Daily, Exotel, or any other transport.
    # This makes the same pipeline reusable across all providers.

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
    context = LLMContext(tools=[hang_up_call])

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
            TranscriptionDeduplicator(),
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
            audio_out_sample_rate=audio_out_sample_rate,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    # ===== 7a. Non-Fatal Error Filter =====
    # Sarvam TTS sometimes reports "completed with no audio" when a context
    # is cancelled by an interruption. This is a false positive - the
    # context was cancelled, not failed. Suppress it to avoid log noise.
    @task.event_handler("on_pipeline_error")  # type: ignore[misc, untyped-decorator]
    async def on_pipeline_error(worker: Any, frame: Any) -> None:
        error_str = str(getattr(frame, "error", frame))
        if "completed with no audio" in error_str:
            logger.debug(f"Suppressed non-fatal TTS error: {error_str}")
            return

        logger.error(f"Pipeline error: {error_str}")

    # ===== 8. Greeting Queue =====
    # Vobiz (and other telephony transports) do not fire on_client_connected
    # on_client_connected event. We queue the greeting through TTS via a background task
    # directly, bypassing the LLM. The LLM is only triggered when the
    # caller actually speaks.
    async def _queue_greeting() -> None:
        # Brief delay to let the pipeline start and TTS connect.
        await asyncio.sleep(1.5)
        try:
            await task.queue_frames([TTSSpeakFrame(lang_config.get_greeting())])
            logger.info(f"Greeting queued for {lang_config.name}")
        except Exception as e:
            logger.error(f"Failed to queue greeting: {e}")

    asyncio.create_task(_queue_greeting())

    return task


DEFAULT_SYSTEM_PROMPT = """You are a friendly, professional AI voice assistant.
Your goal is to have a natural, helpful conversation.

IMPORTANT: Begin the conversation by saying your greeting immediately.
Do not wait for the caller to speak first.

Guidelines:
- Keep responses concise and conversational. Aim for 1-3 sentences.
- Never use markdown, bullet points, or numbered lists in your responses.
- If you don't understand something, ask for clarification naturally.
- Be warm and empathetic in your tone.
- If the user asks a question you cannot answer, politely say so.
"""


async def hang_up_call(
    params: FunctionCallParams,
    reason: str = "user_requested",
) -> None:
    """End the phone call.

    Call this when the caller says goodbye, says they are done, requests
    to end the conversation, or when the task is complete and the caller
    has no further questions.

    Args:
        reason: A short reason for ending the call, One of:
            "user_requested", "task_completed", "caller_not_interested",
            or "wrong_number".
    """
    logger.info(f"LLM invoked hang_up_call with reason: {reason}")
    await params.llm.push_frame(
        EndTaskFrame(reason=reason),
        FrameDirection.UPSTREAM,
    )
    await params.result_callback({"status": "call_ending", "reason": reason})
