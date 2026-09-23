"""Core Pipecat pipeline for the multilingual voice agent.

This module constructs the STT -> LLM -> TTS pipeline that powers
the voice agent. It is the equivalent of the "Agent Core" layer
in the enterprise architecture diagram, but adapted for real-time
voice rather than text-based workflows.

Compatible with Pipecat 1.x (universal LLMContext API).
"""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    EndTaskFrame,
    Frame,
    TextFrame,
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
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.sarvam.llm import SarvamLLMService
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService

from voice_agent.config.languages import LanguageConfig, get_language_config
from voice_agent.config.settings import get_settings
from voice_agent.pipeline.validators import (
    is_affirmative_reply,
    is_explicit_goodbye,
    is_wrong_number,
    was_confirmation_question,
)

settings = get_settings()
# Strong references to fire-and-forget bckground tasks.
# Without this, asyncio.create_task() results may be garbage collected
# before they run (Python's asyncio footgun).
_background_tasks: set[asyncio.Task[None]] = set()


# =========================================================================
# Per-call shared state
# =========================================================================
class CallSessionState:
    """Per-pipeline state shared between frame processors and tool handlers.

    Currently tracks the most recent user and assistant utterances so the
    hang_up_call tool can validate intent against the caller's literal
    words before executing.
    """

    def __init__(self) -> None:
        self.last_user_utterance: str = ""
        self.last_assistant_utterance: str = ""
        # Set to True by UtteranceTracker when a new caller turn begins.
        # TTSInputSanitizer consumes this flag to reset the assistant buffer,
        # so last_assistant_utterance always holds the PREVIOUS turn only.
        self.pending_assistant_reset: bool = False
        # Set True when the guard has blocked a hangup and instructed
        # the LLM to ask the caller for confirmation. Cleared once the
        # caller's next turn is evaluated.
        self.confirmation_pending: bool = False
        # Loop breaker: track consecutive identical tool calls.
        self.last_tool_signature: tuple[str, str] | None = None
        self.consecutive_identical_tool_calls: int = 0


# =========================================================================
# Frame processors
# =========================================================================
class TranscriptionDeduplicator(FrameProcessor):
    """Suppress consecutive identical transcriptions within a time window.

    Sarvam STT occasionally emits the same transcription twice for a single
    utterance when VAD fires multiple start events. This processor filters
    duplicates so the LLM context stays clean.

    IMPORTANT: super().process_frame() must be called so that Pipecat's
    base class can maintain its internal frame lifecycle bookkeeping.
    Without it, downstream processors (aggregator, LLM, TTS) may stall.
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
        await super().process_frame(frame, direction)

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


class UtteranceTracker(FrameProcessor):
    """Records the most recent user and assistant utterances into shared state.

    This state is read by the hang_up_call validator to determine whether
    the caller has explicitly authorized ending the call.
    """

    def __init__(self, state: CallSessionState) -> None:
        super().__init__()
        self._state = state

    async def process_frame(
        self,
        frame: Frame,
        direction: FrameDirection,
    ) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            self._state.last_user_utterance = frame.text
            self._state.pending_assistant_reset = True
            logger.debug(f"Tracked user utterance: {frame.text!r}")

        await self.push_frame(frame, direction)


class TTSInputSanitizer(FrameProcessor):
    """Strip non-speakable text from LLM output before TTS.

    Sanitization only. Assistant utterance tracking is handled by the
    assistant aggregator's on_assistant_turn_stopped event, which fires
    with the complete turn rather than individual TextFrames.
    """

    _FULL_PLACEHOLDER = re.compile(r"^\s*[\(\[\{][^\)\]\}]*[\)\]\}][\s।\.!\?]*$")
    _TOOL_NARRATION = re.compile(
        r"^\s*(?:calling|invoking|executing|using|running)\s+"
        r"(?:the\s+)?(?:tool|function|hang[_ ]?up|api)",
        re.IGNORECASE,
    )

    def __init__(self, state: CallSessionState) -> None:
        super().__init__()
        self._state = state

    async def process_frame(
        self,
        frame: Frame,
        direction: FrameDirection,
    ) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame):
            original = frame.text
            cleaned = self._sanitize(original)

            if not cleaned:
                logger.debug(f"Dropped non-speakable TTS input: {original!r}")
                return

            if cleaned != original:
                logger.debug(f"Sanitize TTS input: {original!r} -> {cleaned!r}")
                frame.text = cleaned

        await self.push_frame(frame, direction)

    def _sanitize(self, text: str) -> str:
        # Fast path: no placeholders in this token; preserve whitespace.
        if not re.search(r"[\(\[\{]", text):
            return text

        stripped = text.strip()
        if not stripped:
            return text
        if self._FULL_PLACEHOLDER.match(stripped):
            return ""
        if self._TOOL_NARRATION.match(stripped):
            return ""
        return text


# =========================================================================
# Tool: hang_up_call (factory with guard)
# =========================================================================
def create_hang_up_call(
    state: CallSessionState, lang_config: LanguageConfig
) -> Callable[..., Awaitable[None]]:
    """Build the hang_up_call tool bound to the per-call session state.

    The returned function is registered with the LLM as `hang_up_call`.
    Before executing, it validates the caller's last utterance against
    deterministic goodbye / wrong-number patterns. If validation fails,
    the tool returns a blocked status that instructs the LLM to redirect
    and continue the conversation instead of ending the call.
    """

    async def hang_up_call(
        params: FunctionCallParams,
        reason: str = "user_requested",
    ) -> None:
        """End the phone call.

        Call this ONLY when the caller has explicitly ended the conversation.

        Valid reasons (and ONLY these):
            - "user_requested": The caller explicitly said goodbye,
              asked to hang up, or said they are not interested.
            - "wrong_number": The caller clearly stated this is the wrong
              number or they are not the intended recipient.

        INVALID uses — do NOT invoke for these:
            - Off-topic or unrelated questions (redirect and continue instead).
            - Silence, pauses, "okay", "hmm", "haan".
            - Repeated greetings.
            - Your own sense that the conversation is going nowhere.
            - Task did not complete as hoped (this is NOT "task_completed").

        If unsure, ASK: "Would you like me to end the call now?" and wait
        for the caller's explicit yes.
        """
        last_user = state.last_user_utterance
        last_assistant = state.last_assistant_utterance

        logger.info(
            f"hang_up_call invoked: reason={reason!r}, "
            f"last_user={last_user!r}, last_assistant={last_assistant!r}"
        )
        # Debug: dump exact codepoints so we can see if combining-mark
        # ordering is causing silent regex mismatches on Indic text.
        logger.debug(f"CODEPOINTS last_user={[hex(ord(c)) for c in last_user]!r}")

        # ---- GUARD: validate intent against literal caller words ----
        if reason == "wrong_number":
            if not is_wrong_number(last_user):
                logger.warning(
                    "hang_up_call BLOCKED: 'wrong_number' reason claimed "
                    "but no wrong-number pattern in last utterance."
                )
                await params.result_callback(
                    {
                        "status": "blocked",
                        "reason": "no_explicit_wrong_number",
                        "instruction": (
                            "The caller did NOT say this is the wrong number. "
                            "Do NOT hang up. Continue the conversation. If the "
                            "caller asked about something unrelated, redirect "
                            "using your scope-boundary phrase and continue."
                        ),
                    }
                )
                return
        else:
            # ---- LOOP BREAKER: detect consecutive identical tool calls ----
            current_signature = (reason, last_user)
            if current_signature == state.last_tool_signature:
                state.consecutive_identical_tool_calls += 1
            else:
                state.consecutive_identical_tool_calls = 1
                state.last_tool_signature = current_signature

            if state.consecutive_identical_tool_calls >= 3:
                logger.warning(
                    f"hang_up_call LOOP DETECTED: same call repeated "
                    f"{state.consecutive_identical_tool_calls} times. "
                    f"Injecting corrective instruction."
                )
                # Reset the counter so the next 3 attempts can still work
                # if the caller eventually says something new.
                state.consecutive_identical_tool_calls = 0
                await params.result_callback(
                    {
                        "status": "blocked",
                        "reason": "loop_detected",
                        "instruction": (
                            "You are repeating the same tool call with identical "
                            "parameters. Do NOT call hang_up_call again. Instead, "
                            "ask the caller directly: 'Would you like me to end "
                            "the call now? and wait for their reply. If the caller "
                            "already answered, accept their answer."
                        ),
                    }
                )
                return
            # First, check the deterministic goodbye patterns OR the
            # affirmative escape hatch armed by a prior blocked hangup.
            goodbye_detected = is_explicit_goodbye(last_user, last_assistant)
            affirmative_detected = state.confirmation_pending and is_affirmative_reply(
                last_user
            )

            if not (goodbye_detected or affirmative_detected):
                logger.warning(
                    "hang_up_call BLOCKED: no explicit goodbye in caller's "
                    "last utterance and no confirmation flow detected. "
                    "Setting confirmation_pending=True so the next caller. "
                    "turn can unlock the affirmative escape hatch."
                )
                state.confirmation_pending = True
                await params.result_callback(
                    {
                        "status": "blocked",
                        "reason": "no_explicit_goodbye",
                        "instruction": (
                            "The caller did NOT explicitly end the call. "
                            "You may NOT hang up. Ask the caller directly: "
                            "'Would you like me to end the call now?' "
                            "(or the Hindi/Tamil equivalent) and wait for "
                            "their reply."
                        ),
                    }
                )
                return

        # Confirmed: clear loop state and proceed to hangup
        state.last_tool_signature = None
        state.consecutive_identical_tool_calls = 0
        # Confirmed - clear the flag and proceed to hangup
        state.confirmation_pending = False

        # ---- PASSED: speak a farewell, then end ----
        farewell_text = (
            lang_config.farewell_wrong_number
            if reason == "wrong_number"
            else lang_config.farewell
        )
        logger.info(
            f"hang_up_call CONFIRMED: reason={reason}, "
            f"caller_utterance={last_user!r}, farewell={farewell_text!r}"
        )

        # Speak the farewell ( downstream = toward TTS).
        await params.llm.push_frame(
            TTSSpeakFrame(farewell_text),
            FrameDirection.DOWNSTREAM,
        )

        # Let TTS synthesize and play before closing the pipeline.
        # Heuristic: ~80ms/char + 1.5s buffer, capped at 6s.
        # This is imprecise but works reliably in practice; the log
        # from the last successful call showed ~1.4s of margin.
        play_seconds = min(len(farewell_text) * 0.08 + 1.5, 6.0)
        await asyncio.sleep(play_seconds)

        # End the task (upstream toward pipeline controller).
        await params.llm.push_frame(
            EndTaskFrame(reason=reason),
            FrameDirection.UPSTREAM,
        )
        await params.result_callback({})

    # Ensure Pipecat registers the tool under the correct name.
    hang_up_call.__name__ = "hang_up_call"
    return hang_up_call


# =========================================================================
# Pipeline factory
# =========================================================================
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

    # Per-call shared state (see CallSessionState).
    session_state = CallSessionState()

    # ===== 1. Transport Layer (injected by caller) =====

    # ===== 2. Speech-to-Text (Sarvam AI) =====
    stt = SarvamSTTService(
        api_key=settings.sarvam_api_key,
        keepalive_timeout=30.0,
        keepalive_interval=5.0,  # Sending keyalive every 5s instead of every 10s
        settings=SarvamSTTService.Settings(
            model=settings.sarvam_stt_model,
            language=lang_config.stt_locale,
        ),
    )

    # ===== 3. LLM (Sarvam-105b-conversations) =====
    base_instruction = system_prompt or DEFAULT_SYSTEM_PROMPT
    composed_instruction = lang_config.get_system_prompt(base_instruction)

    llm = SarvamLLMService(
        api_key=settings.sarvam_api_key,
        settings=SarvamLLMService.Settings(
            model=settings.sarvam_llm_model,
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
    try:
        tts._websocket_ping_interval = 20.0  # type: ignore[attr-defined]  # send ping every 20s
        tts._websocket_ping_timeout = 20.0  # type: ignore[attr-defined]  # Wait 20s for pong before declaring dead.
    except Exception:
        pass

    # ===== 5. Context & Aggregators =====
    hang_up_tool = create_hang_up_call(session_state, lang_config)
    context = LLMContext(tools=[hang_up_tool])

    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    @assistant_aggregator.event_handler("on_assistant_turn_stopped")  # type: ignore[misc, untyped-decorator]
    async def _on_assistant_turn_stopped(aggregator: Any, message: Any) -> None:
        content = getattr(message, "content", None)
        if content:
            session_state.last_assistant_utterance = content
            logger.debug(f"Assistant turn recorded: {content[:80]!r}")
            # If the model spontaneously asked for confirmation, arm the
            # flag so the caller's affirmative reply can authorize hangup.

            if was_confirmation_question(content):
                session_state.confirmation_pending = True
                logger.debug("confirmation_pending armed by assistant's question")

    # ===== 6. Pipeline Construction =====
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            TranscriptionDeduplicator(),
            UtteranceTracker(session_state),
            user_aggregator,
            llm,
            TTSInputSanitizer(session_state),
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    # ===== 7. Pipeline Task =====
    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_out_sample_rate=audio_out_sample_rate,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=180,
    )

    # ===== 7a. Non-Fatal Error Filter =====
    @task.event_handler("on_pipeline_error")  # type: ignore[misc, untyped-decorator]
    async def on_pipeline_error(worker: Any, frame: Any) -> None:
        error_str = str(getattr(frame, "error", frame))
        if "completed with no audio" in error_str:
            logger.debug(f"Suppressed non-fatal TTS error: {error_str}")
            return
        logger.error(f"Pipeline error: {error_str}")

    # ===== 7b. Graceful STT Shutdown =====
    @task.event_handler("on_pipeline_finished")  # type: ignore[misc, untyped-decorator]
    async def on_pipeline_finished(task: Any, frame: Any) -> None:
        try:
            await stt.stop(frame)
            logger.debug("Sarvam STT stopped cleanly")
        except Exception as e:
            logger.debug(f"STT stop raised (usually harmless): {e}")

    # ===== 8. Greeting Queue =====
    async def _queue_greeting() -> None:
        await asyncio.sleep(1.5)
        greeting_text = lang_config.get_greeting()
        logger.info(f"Queue greeting: {greeting_text[:40]}...")
        try:
            await task.queue_frames([TTSSpeakFrame(lang_config.get_greeting())])
            logger.info(f"Greeting queued for {lang_config.name}")
        except Exception as e:
            logger.error(f"Failed to queue greeting: {e}")

    # NOTE: The create_task call MUST be OUTSIDE the coroutine, at the
    # top level of create_agent_pipeline, otherwise it never runs.
    _greeting_task = asyncio.create_task(_queue_greeting())
    _background_tasks.add(_greeting_task)
    _greeting_task.add_done_callback(_background_tasks.discard)

    return task


# =========================================================================
# Base prompt (CRITICAL RULES first — model-attention-safe)
# =========================================================================
DEFAULT_SYSTEM_PROMPT = """You are a friendly, professional AI voice assistant for IT-Webhut.

CRITICAL RULES:

1. TWO DISTINCE CALLER BEHAVIORS, DO NOT CONFUSE THEM:
    (a) OFF-TOPIC QUESTIONS (weather, jokes, sports, chit-chat, other
        companies): use your scope-redirect phrase, then IMMEDIATELY
        ask about the objectives. CONTINUE the call.

    (b) REFUSALS / NOT INTERESTED ("नहीं धन्यवाद", "no thank you",
       "मुझे नहीं चाहिए", "नहीं", "not interested", "बात नहीं करना"):
       NEVER use the scope-redirect phrase. Instead:
         - First refusal: try a different approach, ask a fresh
           qualifying question.
         - Second consecutive refusal: ASK the caller directly:
           "क्या आप चाहते हैं कि मैं अभी call end कर दूँ?"
           (or "Would you like me to end the call now?") and WAIT.
       Do NOT redirect. Do NOT keep re-asking the same topic.

2. GREETING ALREADY DONE. Never greet or re-introduce. If caller says
   "hello" again, move directly to the objective.

3. HANGUP: Call hang_up_call ONLY when the caller literally ends the call.
   Valid triggers:
     - "bye" / "goodbye" / "अलविदा" / "गुड बाय" / "फिर मिलते हैं" / "பை"
     - "end the call" / "hang up" / "फोन रख दीजिए" / "कॉल बंद कर दीजिए"
     - "not interested" / "नहीं धन्यवाद" / "मुझे दिलचस्पी नहीं है"
     - "wrong number" / "गलत नंबर"

   If the caller has refused TWICE in a row (e.g. "नहीं धन्यवाद" said twice),
   ASK them directly: "क्या आप चाहते हैं कि मैं अभी call end कर दूँ?" and WAIT.
   When the caller says "हाँ" / "yes" / "बिल्कुल" to that question, THEN call
   hang_up_call with reason="user_requested".

   If hang_up_call returns {"status": "blocked"}, follow the instruction field.
   Never invoke the same tool twice in a row.






4. NEVER say farewell phrases ("Have a great day", "Take care") without
   calling hang_up_call in the same turn.

5. ALWAYS speak. Never output silent reasoning.

Style: 1-3 sentences per turn. No markdown. Warm and concise.
"""
