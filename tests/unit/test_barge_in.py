"""Unit tests for Phase 6 barge-in and merger behavior.

Run as a standalone script:
    python tests/unit/test_barge_in.py

Exits non-zero on any assertion failure, matching the pattern of
tests/unit/test_pii.py and tests/unit/test_guardrail.py.

What is covered:

    - SplitUtteranceMerger word-level comparison logic
    - SplitUtteranceMerger debounce timing and flush behavior
    - TranscriptionDeduplicator case/punctuation normalization
    - PlayedTextTracker turn buffering and interrupt handling

What is NOT covered:

    - The full Pipecat pipeline (importing create_agent_pipeline
      would require a Vobiz transport and a live event loop)
    - The MinWordsUserTurnStartStrategy and FunctionCallUserMuteStrategy
      strategies (they are library code; our configuration is verified
      by the absence of a mypy error and by the next real test call)
"""

# mypy: disable-error-code="attr-defined"

import asyncio
from typing import Any

from pipecat.frames.frames import (
    AggregationType,
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterruptionFrame,
    TranscriptionFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from voice_agent.pipeline.agent_pipeline import (
    PlayedTextTracker,
    SplitUtteranceMerger,
    TranscriptionDeduplicator,
)

# ====== Helpers ======


def _transcript(text: str) -> TranscriptionFrame:
    """Build a TranscriptionFrame for testing.

    TranscriptionFrame requires three positional fields in Pipecat
    1.10: text, user_id, timestamp. We use fixed placeholder values
    because the processors under test do not inspect user_id or
    timestamp.
    """
    return TranscriptionFrame(
        text=text,
        user_id="test-user",
        timestamp="2026-10-03T00:00:00Z",
    )


async def _push_sequence(
    processor: Any,
    frames: list[tuple[Frame, float]],
) -> list[Frame]:
    """Push a sequence of frames through a processor; collect its output.

    The processor under test normally forwards frames by calling
    `self.push_frame(...)`, which hands them to Pipecat's internal
    queue. In a test there is no queue and no downstream processor,
    so we replace `push_frame` on the instance with a collector that
    appends to a list.

    Using `setattr` (instead of `processor.push_frame = ...`) avoids
    a mypy strict error about assigning to a bound method.

    Args:
        processor: the FrameProcessor to test.
        frames: list of (frame, delay_after_seconds) tuples. Each
            frame is pushed, then the test sleeps for the given delay
            before the next one. A delay of 0.0 does not sleep.

    Returns:
        The list of frames the processor emitted downstream.
    """
    collected: list[Frame] = []

    async def fake_push(frame: Frame, direction: FrameDirection) -> None:
        collected.append(frame)

    # The base FrameProcessor.process_frame calls self._start_interruption
    # when it sees an InterruptionFrame. That handler requires a
    # TaskManager, which Pipecat only attaches to a processor once the
    # pipeline is started. Our test runs the processor standalone, so we
    # stub the handler to a no-op. Without this, Pipecat logs a
    # "TaskManager is not initialized" ERROR on every InterruptionFrame
    # test. The behavior under test (our merger's flush) is unaffected.
    async def _noop_start_interruption(*args: Any, **kwargs: Any) -> None:
        return None

    processor._start_interruption = _noop_start_interruption
    processor.push_frame = fake_push

    for frame, delay in frames:
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
        if delay > 0:
            await asyncio.sleep(delay)

    # SplitUtteranceMerger schedules a background flush task with
    # asyncio.create_task(). If the task is still running when we
    # return, the collected list would be incomplete. Await it here.
    # The merger clears self._flush_task when the task finishes, so
    # a None value means nothing is pending.
    pending = getattr(processor, "_flush_task", None)
    if pending is not None:
        try:
            await pending
        except asyncio.CancelledError:
            # _flush_pending cancels the task on interruption, and
            # then pushes the held frame itself. The captured list is
            # already complete.
            pass

    return collected


# ====== Pure helper tests ======
# These test the small static/class methods that do the actual string
# work. Testing them directly is faster than building a pipeline, and
# if one of them is wrong the failure message is precise.


def test_compare_words_strips_punctuation() -> None:
    """_compare_words lowercases and strips punctuation, not letters."""
    # English: commas and periods must go.
    assert SplitUtteranceMerger._compare_words("Hello, world!") == [
        "hello",
        "world",
    ]
    # Whitespace collapse is implicit in .split().
    assert SplitUtteranceMerger._compare_words("  HELLO  ") == ["hello"]
    # Indic text: the danda (।) must be stripped but the Devanagari
    # letters kept. If this fails, the merger cannot compare Hindi.
    assert SplitUtteranceMerger._compare_words("हाँ।") == ["हाँ"]
    print("test_compare_words_strips_punctuation passed")


def test_normalize_dedup_key() -> None:
    """The deduplicator's normalization collapses case and punctuation."""
    assert TranscriptionDeduplicator._normalize("Hello.") == "hello"
    assert TranscriptionDeduplicator._normalize("HELLO") == "hello"
    assert TranscriptionDeduplicator._normalize("हाँ।") == "हाँ"
    print("test_normalize_dedup_key passed")


# ====== SplitUtteranceMerger tests ======


async def test_merger_flushes_single_fragment() -> None:
    """A single fragment flushes after merge_window seconds."""
    merger = SplitUtteranceMerger(merge_window=0.1)
    collected = await _push_sequence(merger, [(_transcript("Hello"), 0.2)])

    assert len(collected) == 1, f"Expected 1 frame, got {len(collected)}"
    frame = collected[0]
    assert isinstance(frame, TranscriptionFrame)
    assert frame.text == "Hello", f"Got {frame.text!r}"
    print("test_merger_flushes_single_fragment passed")


async def test_merger_concatenates_distinct_fragments() -> None:
    """Two distinct fragments within merge_window are concatenated."""
    merger = SplitUtteranceMerger(merge_window=0.3)
    collected = await _push_sequence(
        merger,
        [
            (_transcript("I am"), 0.05),
            (_transcript("busy right now"), 0.4),
        ],
    )

    assert len(collected) == 1, f"Expected 1 frame, got {len(collected)}"
    frame = collected[0]
    assert isinstance(frame, TranscriptionFrame)
    assert frame.text == "I am busy right now", f"Got {frame.text!r}"
    print("test_merger_concatenates_distinct_fragments passed")


async def test_merger_drops_identical_duplicate() -> None:
    """Identical consecutive fragments collapse to one.

    This is the exact scenario from the 20:48 test call:
        Holding fragment: 'Hello'
        Holding fragment: 'Hello'
        Merged split utterance: 'Hello Hello Hello'   <- bug
    After the 6.1.b.fix, the merger must produce a single 'Hello'.
    """
    merger = SplitUtteranceMerger(merge_window=0.3)
    collected = await _push_sequence(
        merger,
        [
            (_transcript("Hello"), 0.05),
            (_transcript("Hello"), 0.4),
        ],
    )

    assert len(collected) == 1, f"Expected 1 frame, got {len(collected)}"
    assert isinstance(collected[0], TranscriptionFrame)
    assert collected[0].text == "Hello", f"Got {collected[0].text!r}"
    print("test_merger_drops_identical_duplicate passed")


async def test_merger_replaces_with_extended_transcript() -> None:
    """Progressive STT: 'Hello' then 'Hello world' replaces, not concatenates."""
    merger = SplitUtteranceMerger(merge_window=0.3)
    collected = await _push_sequence(
        merger,
        [
            (_transcript("Hello"), 0.05),
            (_transcript("Hello world"), 0.4),
        ],
    )

    assert len(collected) == 1, f"Expected 1 frame, got {len(collected)}"
    assert isinstance(collected[0], TranscriptionFrame)
    assert collected[0].text == "Hello world", f"Got {collected[0].text!r}"
    print("test_merger_replaces_with_extended_transcript passed")


async def test_merger_keeps_longer_when_new_is_shorter() -> None:
    """Pending extends new: keep the longer pending, drop the shorter."""
    merger = SplitUtteranceMerger(merge_window=0.3)
    collected = await _push_sequence(
        merger,
        [
            (_transcript("Hello world"), 0.05),
            (_transcript("Hello"), 0.4),
        ],
    )

    assert len(collected) == 1, f"Expected 1 frame, got {len(collected)}"
    assert isinstance(collected[0], TranscriptionFrame)
    assert collected[0].text == "Hello world", f"Got {collected[0].text!r}"
    print("test_merger_keeps_longer_when_new_is_shorter passed")


async def test_merger_flushes_on_interruption() -> None:
    """An InterruptionFrame flushes the pending fragment immediately.

    Without this, the caller's last utterance would be dropped when
    they interrupt, and the LLM would never see what they said.
    """
    # Large window so the timer would never fire on its own during
    # the test. We want to prove that the InterruptionFrame is what
    # triggers the flush, not the timer.
    merger = SplitUtteranceMerger(merge_window=10.0)
    collected = await _push_sequence(
        merger,
        [
            (_transcript("Hello"), 0.0),
            (InterruptionFrame(), 0.0),
        ],
    )

    texts = [f.text for f in collected if isinstance(f, TranscriptionFrame)]
    assert "Hello" in texts, f"Pending frame not flushed: {texts}"
    assert any(isinstance(f, InterruptionFrame) for f in collected), (
        "InterruptionFrame not forwarded"
    )
    print("test_merger_flushes_on_interruption passed")


async def test_merger_no_merge_across_window() -> None:
    """Fragments separated by more than merge_window stay separate."""
    merger = SplitUtteranceMerger(merge_window=0.1)
    collected = await _push_sequence(
        merger,
        [
            (_transcript("Hello"), 0.2),  # window expires, Hello flushed
            (_transcript("World"), 0.2),  # new turn, World flushed
        ],
    )

    assert len(collected) == 2, f"Expected 2 frames, got {len(collected)}"
    assert isinstance(collected[0], TranscriptionFrame)
    assert isinstance(collected[1], TranscriptionFrame)
    assert collected[0].text == "Hello", f"Got {collected[0].text!r}"
    assert collected[1].text == "World", f"Got {collected[1].text!r}"
    print("test_merger_no_merge_across_window passed")


# ====== TranscriptionDeduplicator tests ======


async def test_dedup_collapses_case_variants() -> None:
    """Case and punctuation variants collapse to one frame.

    From the 23:04 call: "I need Cloud Services" vs "I need cloud
    services." The old exact-match comparison let both through.
    """
    dedup = TranscriptionDeduplicator(window_seconds=1.0)
    collected = await _push_sequence(
        dedup,
        [
            (_transcript("I need Cloud Services"), 0.01),
            (_transcript("I need cloud services."), 0.01),
        ],
    )

    assert len(collected) == 1, f"Expected 1 frame, got {len(collected)}"
    print("test_dedup_collapses_case_variants passed")


async def test_dedup_preserves_distinct_utterances() -> None:
    """Two genuinely different utterances both pass through."""
    dedup = TranscriptionDeduplicator(window_seconds=1.0)
    collected = await _push_sequence(
        dedup,
        [
            (_transcript("Hello"), 0.01),
            (_transcript("How are you"), 0.01),
        ],
    )

    assert len(collected) == 2, f"Expected 2 frames, got {len(collected)}"
    print("test_dedup_preserves_distinct_utterances passed")


async def test_dedup_preserves_repeat_after_window() -> None:
    """A legitimate repeat outside the window is not deduplicated."""
    dedup = TranscriptionDeduplicator(window_seconds=0.1)
    collected = await _push_sequence(
        dedup,
        [
            (_transcript("Hello"), 0.2),
            (_transcript("Hello"), 0.2),
        ],
    )

    assert len(collected) == 2, (
        f"Repeat outside window should be preserved, got {len(collected)}"
    )
    print("test_dedup_preserves_repeat_after_window passed")


# ====== PlayedTextTracker tests ======


async def test_tracker_records_tts_frames() -> None:
    """TTS text spoken before an interruption is stashed."""
    tracker = PlayedTextTracker()
    await _push_sequence(
        tracker,
        [
            (BotStartedSpeakingFrame(), 0.0),
            (TTSTextFrame(text="Hello", aggregated_by=AggregationType.SENTENCE), 0.0),
            (TTSTextFrame(text=" world", aggregated_by=AggregationType.SENTENCE), 0.0),
            (InterruptionFrame(), 0.0),
        ],
    )

    text = tracker.consume_interrupted_text()
    assert "Hello" in text, f"Got {text!r}"
    assert "world" in text, f"Got {text!r}"
    print("test_tracker_records_tts_frames passed")


async def test_tracker_clears_on_normal_stop() -> None:
    """A normal bot stop does not produce a stashed interrupted text."""
    tracker = PlayedTextTracker()
    await _push_sequence(
        tracker,
        [
            (BotStartedSpeakingFrame(), 0.0),
            (TTSTextFrame(text="Hello", aggregated_by=AggregationType.SENTENCE), 0.0),
            (BotStoppedSpeakingFrame(), 0.0),
        ],
    )

    text = tracker.consume_interrupted_text()
    assert text == "", f"Expected empty, got {text!r}"
    print("test_tracker_clears_on_normal_stop passed")


async def test_tracker_consume_clears_state() -> None:
    """Reading the stashed text clears it, so it is not seen twice."""
    tracker = PlayedTextTracker()
    await _push_sequence(
        tracker,
        [
            (BotStartedSpeakingFrame(), 0.0),
            (TTSTextFrame(text="Hi", aggregated_by=AggregationType.SENTENCE), 0.0),
            (InterruptionFrame(), 0.0),
        ],
    )

    first = tracker.consume_interrupted_text()
    second = tracker.consume_interrupted_text()
    assert first != "", "First consume should return text"
    assert second == "", "Second consume should return empty"
    print("test_tracker_consume_clears_state passed")


# ====== Orchestrator ======


async def main() -> None:
    # Pure helpers (synchronous, no event loop needed).
    test_compare_words_strips_punctuation()
    test_normalize_dedup_key()

    # SplitUtteranceMerger.
    await test_merger_flushes_single_fragment()
    await test_merger_concatenates_distinct_fragments()
    await test_merger_drops_identical_duplicate()
    await test_merger_replaces_with_extended_transcript()
    await test_merger_keeps_longer_when_new_is_shorter()
    await test_merger_flushes_on_interruption()
    await test_merger_no_merge_across_window()

    # TranscriptionDeduplicator.
    await test_dedup_collapses_case_variants()
    await test_dedup_preserves_distinct_utterances()
    await test_dedup_preserves_repeat_after_window()

    # PlayedTextTracker.
    await test_tracker_records_tts_frames()
    await test_tracker_clears_on_normal_stop()
    await test_tracker_consume_clears_state()

    print("\nAll barge-in / merger tests passed")


if __name__ == "__main__":
    asyncio.run(main())
