# Phase 6 — Interruption Handling

## Scope
Fix the "speak twice" race, farewell audio race, and barge-in
false-positive defense.

## Commits
| Hash | Title | What it did |
|---|---|---|
| 348d6f4 | 6.1.A | Normalized dedup |
| fcd7001 | 6.1.B | Split-utterance merger |
| e43829d | 6.1.b.fix | Progressive STT fix |
| 509763d | 6.1.C | Assistant context-loss instrumentation |
| 12dcc40 | 6.3 | Barge-in defense |
| 2c9343d | 6.4 | 15 unit tests + orchestrator |
| c63c4ca | flows | Qualify node respond_immediately |

## Test calls
Four calls. The fourth (21:44, 109s) validates the full stack.
Tool-to-LLM gap dropped from 15 s to 20 ms after the
`respond_immediately` fix.

## Known gaps (deferred to Phase 7+)
- PlayedTextTracker placed after transport.output() sees 0
  TTSTextFrames; deferred.
- Single-word affirmatives ("Yes") blocked by MinWords defense
  when bot is speaking; deferred to UX polish.
- Merger flush task occasionally runs late (~6 s) if push_frame
  is blocked by audio playback; observed once, not urgent.
