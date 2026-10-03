# Phase 6 — Interruption Handling

## Objective

Fix three user-visible races:

1. **"Speak twice"** — the caller's utterance was duplicated or
   split, causing the LLM to respond twice or lose half of what was
   said.
2. **Farewell race** — the closing farewell occasionally did not
   play to completion.
3. **Barge-in false positives** — background noise and single-word
   backchannels were interrupting the bot mid-sentence.

## Commits

| Hash | Title |
|---|---|
| 348d6f4 | fix(phase-6.1.a): normalize case and punctuation in transcript dedup |
| fcd7001 | feat(phase-6.1.b): merge split STT fragments before dedup |
| e43829d | fix(phase-6.1.b.fix): prevent merger from stacking progressive STT |
| 509763d | feat(phase-6.1.c): instrument assistant context loss on interruption |
| 12dcc40 | feat(phase-6.3): barge-in false-positive defense |
| 2c9343d | test(phase-6.4): unit and integration tests for Phase 6 |
| c63c4ca | fix(flows): qualify node responds immediately after tool results |
| *(uncommitted at time of writing)* | Unicode fix in `agent_pipeline.py` for Devanagari marks |

## Phase 6.1 — "Speak twice" race

Three distinct mechanisms were discovered from test-call logs:

**Pattern A — case/punctuation variants.** Sarvam emitted `"I need
Cloud Services"` and later `"I need cloud services."` for the same
utterance. The exact-match deduplicator missed both. **Fix:**
normalize before comparing (strip punctuation, lowercase, strip
whitespace). `TranscriptionDeduplicator` updated.

**Pattern B — split fragments.** Sarvam emitted `"Hmm"` then `"and
the call"` for one continuous utterance (99 ms gap in audio).
**Fix:** `SplitUtteranceMerger(FrameProcessor)` implements a debounce
pattern — hold each `TranscriptionFrame` for 2.0 s; if another
arrives first, compare at the word level:

- Identical words → ignore newer
- New extends pending → replace (progressive STT)
- Pending extends new → ignore shorter
- Neither extends → concatenate (genuine split)

Word-level comparison (not character-level) prevents false positives
like "cat" vs "category".

**Pattern C — progressive stacking.** The first version of the
merger concatenated `"Hello"` and `"Hello"` into `"Hello Hello"`,
then into `"Hello Hello Hello"`. Sarvam re-emits the same audio
progressively. **Fix:** word-level prefix comparison (6.1.b.fix).

## Phase 6.1.C — Assistant context instrumentation

`PlayedTextTracker(FrameProcessor)` placed between
`transport.output()` and `context_aggregator.assistant()`. Records
`TTSTextFrame`s for the current bot turn, stashes them on
`InterruptionFrame`. `on_assistant_turn_stopped` compares committed
vs. played text and logs a warning on mismatch.

**Current status:** the tracker receives 0 TTSTextFrames because the
output transport consumes them before our processor sees them. The
instrumentation is in place but not useful. Deferred — the tracker
placement needs architectural work.

## Phase 6.3 — Barge-in defense

**6.3.A** — Replaced `TranscriptionUserTurnStartStrategy` with
`MinWordsUserTurnStartStrategy(min_words=2, use_interim=False)`.
Requires 2+ committed words to interrupt when the bot is speaking.
When the bot is silent, 1 word is enough.

Verified in test call 3: single-word "Okay" and "Hello" during bot
speech were tracked but did not interrupt. Two-word "wait stop"
interrupted correctly.

**6.3.B** — Added `FunctionCallUserMuteStrategy` to
`user_mute_strategies`. Caller audio is dropped during Flows tool
execution. Prevents the LLM from responding to mid-tool utterances
instead of completing the tool's intent.

**6.3.C** — Raised `VADParams.confidence` from 0.6 to 0.65 and
`min_volume` from 0.3 to 0.4. `start_secs` (0.15) and `stop_secs`
(0.2) unchanged — the latter is a Smart Turn v3 training value.

## Unicode fix

The merger and deduplicator both used the regex character class
`[^\w\s]` to strip punctuation. In Python 3, `\w` matches Unicode
letters and digits but **not** Unicode combining marks (categories
Mn, Mc, Me). Devanagari matras (ा, ि, ी), anusvara (ं), and
visarga (ः) were stripped along with real punctuation. `"हाँ।"`
reduced to `"ह"`, which meant `"हाँ"` (yes) and `"हूँ"` (I am) were
treated as duplicates.

**Fix:** `_strip_punctuation_keep_marks(text)` — module-level helper
that uses `unicodedata.category` to preserve letters, marks,
digits, and whitespace, and strip only punctuation and symbols.

Caught by `test_compare_words_strips_punctuation` before any real
call was affected.

## Qualify node `respond_immediately`

Test call 3 showed three cases of the assistant going silent after
a tool call (15 s, 8 s, 15 s). The root cause: the qualify node had
`respond_immediately=False`, so Pipecat Flows did not trigger a
follow-up LLM call on the transition back to qualify after a tool
result. The LLM only re-ran when the caller spoke again.

**Fix:** `respond_immediately=True` on the qualify node, matching
every other node.

Test call 4 confirmed the fix: tool-to-LLM gap dropped from 15 s
to ~20 ms. The caller no longer has to repeat themselves.

## Phase 6.4 — Tests

`tests/unit/test_barge_in.py` covers 15 cases:

- `_strip_punctuation_keep_marks` preserves Devanagari marks
- `SplitUtteranceMerger` debounce: single fragment, concatenate,
  drop identical, replace progressive, keep longer, flush on
  `InterruptionFrame`, no merge across window
- `TranscriptionDeduplicator` case/punctuation normalization,
  distinct preservation, repeat preservation outside window
- `PlayedTextTracker` turn buffering, interrupt stash,
  consume-clears-state

`tests/integration/test_phase_6.py` is a subprocess orchestrator
matching `test_phase_5_7.py`.

## Design decisions

**Debounce with a word-level comparison.** The naive approach
(exact-match dedup) missed case and punctuation variants. The
naive fix (concatenate everything) produced "Hello Hello Hello".
Word-level prefix comparison is the middle ground that handles
both progressive STT and genuine splits.

**`MinWords` replaces `TranscriptionUserTurnStartStrategy`.**
Using both would defeat the purpose: `TranscriptionUserTurnStart`
fires on single words regardless of bot state.

**File-level `# mypy: disable-error-code="attr-defined"` for
`AggregationType`.** The name is not in `pipecat.frames.frames.__all__`.
Per-line ignore did not work on a single-name import in mypy 1.x.
The file-level directive is broader but scoped to one test file.

## Validation

Four test calls:

| # | Time | Key finding |
|---|---|---|
| 1 | 12:26 | "Speak twice" race observed; merger needed |
| 2 | 23:04 | Merger shipped; progressive stacking bug found |
| 3 | 21:09 | Barge-in defense worked; `respond_immediately` bug found |
| 4 | 21:44 | All fixes confirmed. Tool-to-LLM gap 20 ms. Full farewell played |

## Known gaps (at end of Phase 6)

- **PlayedTextTracker placement** — sees 0 TTSTextFrames. Deferred.
- **Single-word affirmatives** — `MinWords` blocks "Yes" / "हाँ"
  during bot speech even when `confirmation_pending=True`. UX
  trade-off; documented for Phase 7 polish.
- **Merger flush delay under load** — observed once (6.1 s instead
  of 2.0 s) when `push_frame` was blocked by audio playback. Not
  user-visible in test calls.
- **Caller latency** — 4–6 s end-to-end. Merger accounts for 2.0 s
  of that. Early-flush trigger (flush immediately on terminal
  punctuation or known refusal pattern) is a Phase 7 candidate.
