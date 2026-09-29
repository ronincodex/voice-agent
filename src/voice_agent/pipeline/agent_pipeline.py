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
from typing import Any

from loguru import logger
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.flows import FlowManager
from pipecat.frames.frames import Frame, TextFrame, TranscriptionFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.sarvam.llm import SarvamLLMService
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.turns.user_start import (
    TranscriptionUserTurnStartStrategy,
    VADUserTurnStartStrategy,
)
from pipecat.turns.user_stop import (
    SpeechTimeoutUserTurnStopStrategy,
    TurnAnalyzerUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from voice_agent.config.languages import get_language_config
from voice_agent.config.settings import get_settings
from voice_agent.db.audit import AuditTrail
from voice_agent.db.supabase_client import SupabaseStore
from voice_agent.observability.metrics import MetricsCollector, MetricsObserver
from voice_agent.pipeline.validators import was_confirmation_question
from voice_agent.state.redis_store import RedisSessionStore

settings = get_settings()
# Strong references to fire-and-forget bckground tasks.
# Without this, asyncio.create_task() results may be garbage collected
# before they run (Python's asyncio footgun).
_background_tasks: set[asyncio.Task[None]] = set()


# ====== Per-call shared state ======
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


# ====== Frame processors ======
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


# ====== Pipeline factory ======
async def create_agent_pipeline(
    transport: Any,
    language_code: str = "hi-IN",
    audio_out_sample_rate: int = 24000,
    call_id: str = "unknown",
) -> tuple[PipelineTask, FlowManager]:
    """Create and configure the voice agent pipeline with Pipecat Flows.

    Returns:
        A tupple of (PipelineTask, FlowManager). The caller must call
        `await flow_manager.initialize(build_initial_node(lang_config))`
        after the pipeline starts, since Vobiz does not fire on_client_connected.
    """
    lang_config = get_language_config(language_code)
    logger.info(f"Creating Flows pipeline for language: {lang_config.name}")

    # Single source of truth for utterance tracking across the pipeline
    # and the Flows handlers. Stored in flow_manager.state so nodes.py
    # can read from it.
    session_state = CallSessionState()
    # External state stores
    redis_store = RedisSessionStore(
        url=settings.upstash_redis_rest_url,
        token=settings.upstash_redis_rest_token,
    )
    supabase_store = SupabaseStore(
        url=settings.supabase_url,
        service_key=settings.supabase_service_key,
    )

    # ====== 1. STT ======
    stt = SarvamSTTService(
        api_key=settings.sarvam_api_key,
        keepalive_timeout=30.0,
        keepalive_interval=5.0,
        settings=SarvamSTTService.Settings(
            model=settings.sarvam_stt_model,
            language=lang_config.stt_locale,
        ),
    )

    # ====== 2. LLM ======
    llm = SarvamLLMService(
        api_key=settings.sarvam_api_key,
        settings=SarvamLLMService.Settings(
            model=settings.sarvam_llm_model,
            system_instruction="",  # Flows provides per-node role_message
        ),
    )

    # ====== 3. TTS ======
    tts = SarvamTTSService(
        api_key=settings.sarvam_api_key,
        settings=SarvamTTSService.Settings(
            model=settings.sarvam_tts_model,
            voice=lang_config.tts_voice,
            language=lang_config.tts_language_code,
        ),
    )
    try:
        tts._websocket_ping_interval = 20.0  # type: ignore[attr-defined]
        tts._websocket_ping_timeout = 20.0  # type: ignore[attr-defined]
    except Exception:
        pass

    # ====== 4. Context & Aggregators (Flows-managed) ======
    context = LLMContext()
    vad = SileroVADAnalyzer(
        params=VADParams(
            confidence=0.6,  # was 0.7: lower threshold accepts weaker signal
            start_secs=0.15,  # was 0.2: faster speech-onset detection
            stop_secs=0.2,  # REQUIRED by Smart Turn v3 (training-data value, do not change)
            min_volume=0.3,  # was 0.6: softer callers now captured
        )
    )

    # Turn strategies resolve the asymmetry in PIpecat issue #3643:
    # a turn can START from a transcription without VAD, but the
    # TurnAnalyzer stop strategy requires a VAD event. Adding a
    # transcription-based stop strategy as fallback means short/soft
    # utterances that VAD misses still finalize their turn.
    user_turn_strategies = UserTurnStrategies(
        start=[
            VADUserTurnStartStrategy(),
            TranscriptionUserTurnStartStrategy(),
        ],
        stop=[
            TurnAnalyzerUserTurnStopStrategy(
                turn_analyzer=LocalSmartTurnAnalyzerV3(
                    params=SmartTurnParams(stop_secs=1.0)  # was default 3.0
                )
            ),
            SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.4),
        ],
    )
    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=vad,
            user_turn_strategies=user_turn_strategies,
            user_turn_stop_timeout=1.5,  # was 5.0 than changed to 3.0: faster fallback
        ),
    )

    # ====== 5. Assistant turn tracking (arms confirmation_pending) ======
    @context_aggregator.assistant().event_handler("on_assistant_turn_stopped")  # type: ignore[misc, untyped-decorator]
    async def _on_assistant_turn_stopped(aggregator: Any, message: Any) -> None:
        content = getattr(message, "content", None)
        if content:
            session_state.last_assistant_utterance = content
            logger.debug(f"Assistant turn recorded: {content[:80]!r}")

            # Persist to Supabase
            supabase = flow_manager.state.get("supabase")
            internal_call_id = flow_manager.state.get("internal_call_id")
            if supabase and internal_call_id:
                try:
                    await supabase.save_message(
                        call_id=internal_call_id,
                        role="assistant",
                        text=content,
                    )
                except Exception as e:
                    logger.error(f"Failed to persist assistant message: {e}")
            if was_confirmation_question(content):
                session_state.confirmation_pending = True
                logger.debug("[flows] confirmation_pending armed by assistant question")

    @context_aggregator.user().event_handler("on_user_turn_stopped")  # type: ignore[misc, untyped-decorator]
    async def _on_user_turn_stopped(aggregator: Any, *args: Any) -> None:
        """Persist every caller utterance to Supabase.

        Deduplication when Pipecat fires the event twice per turn
        (once per registered stop strategy).
        """
        # The message is always the LAST positional argument
        message = args[-1] if args else None
        content = str(getattr(message, "content", "") or "").strip()

        if not content:
            return

        # Dedup: same content within 1 second is a duplicate event
        now = time.monotonic()
        last_text = getattr(session_state, "_last_saved_user_text", "")
        last_time = getattr(session_state, "_last_saved_user_time", 0.0)
        if content == last_text and now - last_time < 1.0:
            logger.debug(f"[user-turn] dedup skipped: {content[:40]!r}")
            return
        session_state._last_saved_user_text = content  # type: ignore[attr-defined]
        session_state._last_saved_user_time = now  # type: ignore[attr-defined]

        session_state.last_user_utterance = content

        supabase = flow_manager.state.get("supabase")
        internal_call_id = flow_manager.state.get("internal_call_id")

        if not supabase or not internal_call_id:
            logger.warning(
                "[user-turn] missing supabase or internal_call_id, skipping persist"
            )
            return

        try:
            await supabase.save_message(
                call_id=internal_call_id,
                role="user",
                text=content,
            )
            logger.debug(f"[user-turn] saved: {content[:40]!r}")
        except Exception as e:
            logger.error(f"[user-turn] failed to persist: {e}")

    # ====== 6. Pipeline ======
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            TranscriptionDeduplicator(),
            UtteranceTracker(session_state),
            context_aggregator.user(),
            llm,
            TTSInputSanitizer(session_state),
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    # ====== 7b. Latency metrics ======
    metrics_collector = MetricsCollector()
    metrics_observer = MetricsObserver(metrics_collector)

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_out_sample_rate=audio_out_sample_rate,  # 8000 for Vobiz telephony
            # audio_in_sample_rate intentionally NOT set here: it must remain 16000
            # for Smart Turn v3. The VobizFrameSerializer upsamples 8kHz wire audio
            # to 16kHz internally. See Pipecat issue #3844
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=180,
        observers=[metrics_observer],  # <-- the fix
    )

    # ====== 8. FlowManager ======
    flow_manager = FlowManager(
        worker=task,
        # mypy limiataion: pipecat-flows' TYPE_CHECKING union only lists
        # OpenAI/Anthropic/Google LLM services. SarvamLLMservice is a
        # subclass of OpenAILLMService and works at runtime (the docs
        # explicitly list OpenAI-compatible services as supported).
        llm=llm,  # type: ignore[arg-type]
        context_aggregator=context_aggregator,
        transport=transport,
    )

    # Store lang_config for node builders to access.
    # Store all shared state in flow_manager.state
    flow_manager.state["session_state"] = session_state
    flow_manager.state["lang_config"] = lang_config
    flow_manager.state["redis"] = redis_store
    flow_manager.state["supabase"] = supabase_store
    # call_id is set by the WebSocket handler before pipeline creation
    flow_manager.state["call_id"] = call_id
    # NOTE: internal_call_id is set by server.py AFTER this function returns,
    # because the Supabase call record is created there, not here.
    # flow_manager.state["internal_call_id"] = internal_call_id
    flow_manager.state["metrics_collector"] = metrics_collector
    audit_trail = AuditTrail(
        supabase_url=settings.supabase_url,
        service_key=settings.supabase_service_key,
    )
    flow_manager.state["audit"] = audit_trail
    flow_manager.state["supabase_url"] = settings.supabase_url
    flow_manager.state["supabase_key"] = settings.supabase_service_key

    return task, flow_manager
