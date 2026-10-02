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
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    EndFrame,
    Frame,
    InterruptionFrame,
    TextFrame,
    TranscriptionFrame,
    TTSTextFrame,
)
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
from voice_agent.pipeline.guardrail import PromptInjectionGuard
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
class SplitUtteranceMerger(FrameProcessor):
    """Merge split STT fragments into a single TranscriptionFrame.

    Sarvam STT occasionally splits one continuous utterance into two
    transcriptions when VAD fires a stop mid-thought. From the
    12:26 test call:

        12:27:10.843  transcript='Hmm'          audio_duration=1.216
        12:27:12.359  transcript='and the call' audio_duration=1.440

    The audio was continuous (gap between segments was ~99 ms), but
    the LLM saw two separate turns and replied to each. Neither
    fragment made sense on its own.

    The fix is a "debounce" pattern borrowed from UI programming:
    when a TranscriptionFrame arrives, hold it for `merge_window`
    seconds. If another TranscriptionFrame arrives before the
    timer expires, concatenate the two and restart the timer. When
    the timer finally expires with no new fragment, push the held
    frame downstream.

    Trade-off: adds up to `merge_window` seconds of latency to
    every caller turn. For telephony, where callers pause naturally
    between thoughts, this is acceptable. The window is configurable
    and will be tuned from real call data.

    Python note on asyncio: the background timer is created with
    `asyncio.create_task()`. Python's event loop only keeps a WEAK
    reference to tasks, so a task with no strong reference can be
    garbage-collected before it runs. We store the task on
    `self._flush_task` to prevent that: the same footgun that is
    documented at the top of this module.
    """

    def __init__(self, merge_window: float = 2.0) -> None:
        # Every FrameProcessor subclass must call super().__init__().
        # This initializes Pipecat's internal queues and lifecycle
        # bookkeeping.
        super().__init__()
        self._merge_window = merge_window

        # The frame we are holding back from the pipeline. `None`
        # means nothing is pending: the previous frame was already
        # pushed downstream.
        self._pending: TranscriptionFrame | None = None

        # Strong reference to the flush timer. See the class
        # docstring for why this is required.
        self._flush_task: asyncio.Task[None] | None = None

    async def process_frame(
        self,
        frame: Frame,
        direction: FrameDirection,
    ) -> None:
        # Pipecat requires every processor to call super().process_frame
        # first. It handles frame-lifecycle bookkeeping. Skipping it
        # causes downstream processors to stall.
        await super().process_frame(frame, direction)

        # If the pipeline is being interrupted or shut down, we
        # must NOT hold frames back, push them now. Otherwise:
        #   - an interruption could deliver a stale fragment AFTER
        #     the user has already changed topic
        #   - an EndFrame could silently drop the last utterance
        #     the caller spoke, and the LLM would never respond
        if isinstance(frame, (InterruptionFrame, EndFrame)):
            await self._flush_pending()
            await self.push_frame(frame, direction)
            return

        # Every other frame type passes through untouched. Metrics,
        # bot-speaking notifications, StartFrame, none of these are
        # candidates for merging, and holding them would break the
        # pipeline.
        if not isinstance(frame, TranscriptionFrame):
            await self.push_frame(frame, direction)
            return

        # We now know this is a TranscriptionFrame. Two cases:
        #   (a) Nothing pending  -> hold this frame and start the timer
        #   (b) Something pending -> concatenate, then restart the timer
        if self._pending is None:
            self._pending = frame
            logger.debug(f"Holding fragment: {frame.text!r}")
        else:
            previous_text = self._pending.text
            merged_text = f"{previous_text.strip()} {frame.text.strip()}"

            # Mutate the held frame's text in place. We do NOT
            # construct a new TranscriptionFrame, because that would
            # discard other attributes (language, finalized, result)
            # that Sarvam may have populated. TextFrame.text is a
            # plain attribute in Pipecat 1.10 and is safe to assign.
            self._pending.text = merged_text

            logger.debug(
                f"Merged split utterance: {merged_text!r} "
                f"(from {previous_text!r} + {frame.text!r})"
            )

        # Restart the flush timer. If a new fragment arrives before
        # it fires, this task is cancelled and replaced.
        self._schedule_flush()

    async def _flush_pending(self) -> None:
        """Push the held frame downstream and stop the timer.

        Safe to call when nothing is pending. This matters because
        InterruptionFrame and EndFrame can arrive in quick
        succession, each triggering a flush.
        """
        self._cancel_flush()
        if self._pending is not None:
            frame = self._pending
            self._pending = None
            logger.debug(f"Flushing merged frame: {frame.text!r}")
            await self.push_frame(frame, FrameDirection.DOWNSTREAM)

    def _schedule_flush(self) -> None:
        """Start (or restart) the background flush timer."""
        self._cancel_flush()
        self._flush_task = asyncio.create_task(self._flush_after_delay())

    async def _flush_after_delay(self) -> None:
        """Wait `merge_window` seconds, then flush whatever is held."""
        await asyncio.sleep(self._merge_window)

        # This coroutine IS the timer. Do not call _cancel_flush()
        # here — that would try to cancel our own task. Do the work
        # directly and clear the reference.
        frame = self._pending
        self._pending = None
        self._flush_task = None

        if frame is not None:
            logger.debug(f"Flushing after {self._merge_window}s window: {frame.text!r}")
            await self.push_frame(frame, FrameDirection.DOWNSTREAM)

    def _cancel_flush(self) -> None:
        """Stop the pending timer, if any."""
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
        self._flush_task = None


class TranscriptionDeduplicator(FrameProcessor):
    """Suppress near-identical transcriptions within a time window.

    Sarvam STT occasionally emits variants of the same utterance that
    differ only in case or punctuation:

        "I need Cloud Services"  vs  "I need cloud services."
        "Call me later"          vs  "call me later"
        "Haan"                   vs  "haan"

    The original implementation used exact string equality, so these
    variants slipped through and the LLM received the same user turn
    twice. We now normalize both sides before comparing:

        1. strip punctuation (ASCII and Indic danda)
        2. lowercase
        3. strip leading/trailing whitespace

    Only consecutive duplicates within `window_seconds` are filtered.
    A legitimate repeat after the window is preserved.

    Python concept note: `re.Pattern[str]` is a generic type: it tells
    mypy that `_PUNCT` is a compiled regex whose `.sub()` returns `str`.
    Without the type parameter, mypy strict mode would report an error.
    """

    # Character class [^\w\s] means "not (word character OR whitespace)".
    # In Python 3, \w matches Unicode letters (Hindi, Tamil, etc.) plus
    # digits and underscore, so we only strip punctuation and symbols.
    _PUNCT: re.Pattern[str] = re.compile(r"[^\w\s]")

    def __init__(self, window_seconds: float = 3.0) -> None:
        # super().__init__() initializes Pipecat's FrameProcessor base
        # class. Every FrameProcessor subclass must call it.
        super().__init__()
        self._window = window_seconds
        self._last_normalized: str | None = None
        self._last_time: float = 0.0

    @classmethod
    def _normalize(cls, text: str) -> str:
        """Return a comparison-friendly form of `text`.

        `cls._PUNCT` is a classmethod-style access to the class variable
        `_PUNCT`. Using `cls` (rather than hardcoding the class name)
        means subclasses would see their own `_PUNCT` if they overrode it.
        """
        without_punct = cls._PUNCT.sub("", text)
        return without_punct.lower().strip()

    async def process_frame(
        self,
        frame: Frame,
        direction: FrameDirection,
    ) -> None:
        # Always call super().process_frame() first: Pipecat relies on
        # it for internal frame-lifecycle bookkeeping. Skipping it
        # causes downstream processors to stall.
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            now = time.monotonic()
            normalized = self._normalize(frame.text)

            if (
                normalized == self._last_normalized
                and now - self._last_time < self._window
            ):
                logger.debug(f"Deduplicated transcript (normalized): {frame.text!r}")
                return

            self._last_normalized = normalized
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


class PlayedTextTracker(FrameProcessor):
    """Record the assistant text the caller actually heard.

    Issue #4996 (pipecat-ai/pipecat, open as of 1.10.0): on an
    interruption, TTS text the caller has already heard can be lost
    from the assistant context. The InterruptionFrame is a SystemFrame
    and overtakes TTSTextFrames still queued in the assistant
    aggregator's FrameProcessorQueue. The aggregator commits the turn
    without those words, and the overtaken frames are then prepended
    to the NEXT assistant message, corrupting both turns.

    This processor records every TTSTextFrame that reaches it. Since
    it sits between transport.output() and the assistant aggregator,
    it sees the same frames the aggregator receives, including the
    ones that the interruption will overtake.

    On interruption, the recorded text for the interrupted turn is
    stashed in `_interrupted_text` and can be read by the
    on_assistant_turn_stopped handler for comparison against the
    committed content.

    This class does NOT repair the context. The committed content is
    not guaranteed to be a clean prefix of the recorded text (STT and
    TTS may reorder or punctuate differently), and a bad repair is
    worse than no repair. We instrument first, collect data from a
    real call, then decide whether a repair is justified.

    Python note: we deliberately do not use a boolean to track "is
    the bot speaking". We track it by intercepting BotStartedSpeaking
    and BotStoppedSpeaking frames, which the transport emits itself.
    That is the most reliable signal, it cannot desync from the
    actual audio state.
    """

    def __init__(self) -> None:
        # Every FrameProcessor subclass must call super().__init__().
        super().__init__()

        # Words accumulated for the current bot turn. Reset on
        # BotStartedSpeakingFrame.
        self._current_turn: list[str] = []

        # Text of the most recent turn that was interrupted.
        # Consumed by consume_interrupted_text().
        self._interrupted_text: str = ""

        # Set to True when a BotStartedSpeakingFrame has arrived and
        # no matching BotStoppedSpeakingFrame or InterruptionFrame
        # has been seen yet. Guards against stray TTSTextFrames that
        # arrive outside a turn (should not happen, but defensive).
        self._bot_speaking: bool = False

    async def process_frame(
        self,
        frame: Frame,
        direction: FrameDirection,
    ) -> None:
        # Pipecat requires every processor to call super().process_frame
        # first. It handles frame-lifecycle bookkeeping. Skipping it
        # causes downstream processors to stall.
        await super().process_frame(frame, direction)

        if isinstance(frame, BotStartedSpeakingFrame):
            # The bot just began speaking. Start a fresh turn buffer.
            self._bot_speaking = True
            self._current_turn = []
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TTSTextFrame):
            # A word or phrase was just released by the transport.
            # The caller heard it. Record it, then forward it so the
            # assistant aggregator can add it to context.
            self._current_turn.append(frame.text)
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, InterruptionFrame):
            # The caller barged in. Whatever we have recorded for
            # this turn is text the caller heard BEFORE the
            # interruption. Stash it so the handler can compare.
            if self._bot_speaking and self._current_turn:
                self._interrupted_text = " ".join(self._current_turn).strip()
                logger.debug(
                    f"PlayedTextTracker: interrupted turn had "
                    f"{len(self._current_turn)} frames, "
                    f"text={self._interrupted_text[:120]!r}"
                )
            self._current_turn = []
            self._bot_speaking = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, BotStoppedSpeakingFrame):
            # The bot finished speaking normally (no interruption).
            # Discard the buffer, the aggregator committed the full
            # turn and there is nothing to compare.
            self._current_turn = []
            self._bot_speaking = False
            await self.push_frame(frame, direction)
            return

        # Any other frame passes through untouched.
        await self.push_frame(frame, direction)

    def consume_interrupted_text(self) -> str:
        """Return and clear the stashed interrupted-turn text.

        Called from the on_assistant_turn_stopped handler. Returns
        an empty string if no interruption occurred since the last
        call, or if the interruption happened before any TTSTextFrame
        was released.
        """
        text = self._interrupted_text
        self._interrupted_text = ""
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
        interrupted = getattr(message, "interrupted", False)

        # --- Phase 6.1.C: detect assistant context loss (#4996) ---
        if interrupted:
            played = played_tracker.consume_interrupted_text()
            committed = content or ""
            logger.warning(
                f"assistant_interrupted "
                f"committed_len={len(committed)} "
                f"played_len={len(played)} "
                f"committed={committed[:100]!r} "
                f"played={played[:100]!r}"
            )
            # If the committed text is shorter than the played text,
            # the aggregator lost the tail. This is issue #4996.
            # We log the delta but do NOT repair the context yet.
            if played and committed and not played.startswith(committed):
                logger.error(
                    f"assistant_context_loss_suspected "
                    f"played={played[:120]!r} committed={committed[:120]!r}"
                )
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
    guard = PromptInjectionGuard(lang_config.guardrail_deflect)
    played_tracker = PlayedTextTracker()

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            SplitUtteranceMerger(merge_window=2.0),  # <-- new line
            TranscriptionDeduplicator(),
            guard,
            UtteranceTracker(session_state),
            context_aggregator.user(),
            llm,
            TTSInputSanitizer(session_state),
            tts,
            transport.output(),
            played_tracker,  # <-- new
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
    flow_manager.state["prompt_injection_guard"] = guard

    return task, flow_manager
