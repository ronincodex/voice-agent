# Phase 1–3 — Core Pipeline and Persistence

## Objective

Build a working multilingual voice pipeline (STT → LLM → TTS)
connected to real telephony, with persistent session state and a
database for call records and transcripts.

This phase laid the foundation every later phase builds on.

## Commits

| Hash | Title |
|---|---|
| 886d46d | feat(part-1): working multilingual voice pipeline (checkpoint) |
| ed608ae | fix(part-2): resolve critical bugs and add enterprise foundations |
| 21f75df | chore: remove ngrok installer tarball from tracking |
| d888def | feat(phase1): unicode normalization, loop breaker, Sarvam-105b-conversations migration |
| 9327004 | feat(phase1): duplicate of above (renamed commit) |
| afd2171 | feat(phase2): pipecat flows state machine with phase-gated tools |
| 2f5919f | chore(deps): add upstash-redis and supabase for Phase 3 |
| ee75f6c | feat(config): add Redis, Supabase, and R2 settings fields |
| 6d0c6fa | feat(state): add RedisSessionStore |
| eead2d7 | feat(db): add SupabaseStore for call persistence |
| c528121 | feat(pipeline): wire Redis and Supabase into FlowManager |
| e43a8b6 | feat(flows): persist node state to Redis |
| 443358b | feat(telephony): add inbound call handling |
| 8109c51 | fix(telephony): coerce Duration to str for int() |
| 76cf71a | feat(phase-3): Redis session state + Supabase persistence |
| 7bed6b5 | chore(tests): remove duplicate test file |
| 6102592 | fix(Phase-3): idempotent hangup and deduplicate user turns |

## What was built

### Telephony layer (`telephony/`)

- `VobizClient` — async HTTP adapter for Vobiz's Voice REST API.
  Auth headers `X-Auth-ID` / `X-Auth-Token`. Wrapped in
  `@retry_fast` for transient network failures.
- `CallState` — in-memory lifecycle tracker for each outbound call
  (initiated → ringing → in-progress → completed / no-answer /
  busy / failed / timeout / cancel).
- `server.py` — FastAPI app exposing `/call`, `/answer`, `/incoming`,
  `/ring`, `/hangup`, `/recording-ready`, `/recording-complete`, and
  the `/ws` WebSocket endpoint for Vobiz Media Streams.

### Pipeline (`pipeline/`)

- Pipecat 1.10 pipeline: `transport.input → stt → dedup → guard →
  user_aggregator → llm → sanitizer → tts → transport.output →
  assistant_aggregator`.
- Sarvam Saaras:v3 STT, Sarvam 105b-conversations LLM, Sarvam
  Bulbul:v3 TTS.
- Pipecat Flows state machine: `greeting → qualify → confirm →
  closing`. Each node has a scoped `role_message`, `task_messages`,
  and function list.
- `UtteranceTracker` — records the most recent user and assistant
  utterances into shared state so `hang_up_call` can validate
  intent against the caller's literal words.
- `TTSInputSanitizer` — strips non-speakable text (placeholders,
  tool narration) before TTS.

### Validators (`pipeline/validators.py`)

Regex-based gate for destructive tool calls. The design principle:
*the LLM proposes, the validator disposes*. Even if the model
hallucinates intent, the call cannot end unless the caller's literal
words authorize it.

- `GOODBYE_PATTERNS` — Hindi, English, Tamil, code-mixed
- `WRONG_NUMBER_PATTERNS` — same languages
- `_AFFIRMATIVE_TOKEN` — short yes-word detector with Indic base-character fallback
- `is_explicit_goodbye(user_text, last_assistant)` — two-turn goodbye flow
- `is_wrong_number(user_text)`

Uses Unicode NFC normalization and zero-width-character stripping so
Devanagari combining-mark order does not break matching.

### Language abstraction (`config/languages.py`)

`LanguageConfig` — a Pydantic model that captures everything one
language needs:

- `code`, `name`, `stt_locale`, `tts_voice`, `tts_language_code`
- `llm_prompt_suffix`
- `greeting`, `persona_name`, `persona_gender`
- `scope_redirect`, `farewell`, `farewell_wrong_number`
- `consent_disclosure`, `consent_decline_ack`, `guardrail_deflect`

Adding a new language is a config change, not a code change.

### Session state (`state/redis_store.py`)

`RedisSessionStore` — Upstash Redis hash per call, 1-hour TTL. Stores
`refusal_count`, `confirmation_pending`, `close_reason`, `interest`.
Survives process restarts.

### Persistence (`db/supabase_client.py`)

`SupabaseStore` — CRUD over the `calls` and `messages` tables.
`create_call`, `save_message`, `update_call`, `get_transcript`.

### Database (`docs/schema.sql`)

Supabase Postgres with two tables:

- `calls` — one row per phone call (uuid, direction, numbers,
  language, status, timestamps, duration, recording_url, summary)
- `messages` — one row per utterance (call_id, role, text, tool_name,
  tool_args, latency_ms)

Both have RLS enabled with service_role policies.

## Design decisions

**Idempotent hangup.** In early testing the LLM invoked
`hang_up_call` twice — once from `confirm`, once from `closing` — and
the second call overwrote `confirmation_pending` back to `True`. The
Phase 3 fix was a manual `close_reason` short-circuit inside
`hang_up_call`. Phase 5.6 later generalized this into a decorator.

**User-turn deduplication.** Pipecat fired `on_user_turn_stopped`
twice per turn (once per registered stop strategy), causing double
persistence. Fix: content+timestamp comparison with a 1-second
window in the handler.

**Inbound handling.** `/incoming` returns VobizXML that opens a
bidirectional WebSocket. The WebSocket handler reads a `direction`
query parameter to distinguish inbound from outbound.

## Validation

- Local Daily WebRTC test: pipeline connected, greeting played,
  STT transcription returned, LLM responded, TTS spoke.
- End-to-end Vobiz call: outbound call placed, conversation
  completed, hangup webhook persisted status and duration.
- Round-trip tests for `RedisSessionStore` and `SupabaseStore`.

## Known gaps (at end of Phase 3)

- No recording persistence (Phase 4)
- No AI summary (Phase 4)
- No latency metrics (Phase 5.2)
- No retry policy (Phase 5.3)
- No compliance layer (Phase 5.7)
