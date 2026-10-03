# Phase 4 — Recording Storage and AI Summaries

## Objective

After every call ends, download the MP3 from Vobiz, upload it to
Cloudflare R2, and generate a structured AI summary of the
transcript.

## Commits

| Hash | Title |
|---|---|
| 0d9408b | chore(phase-4): scaffold storage/ and postcall/ directories |
| fc14ace | docs(env): document R2 credential in .env.example |
| 1828ab7 | feat(storage): add R2Storage client |
| 255fa01 | feat(storage): wire /recording-ready to download and upload to R2 |
| 5b39bde | feat(postcall): add Sarvam 105b AI summariser |
| b33e9f8 | feat(postcall): trigger AI summary after pipeline closes |
| 8f4119b | feat(recording): fetch authenticated Vobiz recording and store in R2 |
| 7ba2643 | feat(phase-4): recording storage in R2 and AI call summaries |

## What was built

### Storage (`storage/r2_client.py`)

`R2Storage` — S3-compatible upload via boto3.

- `upload_recording(call_uuid, audio_bytes)` — writes to
  `recordings/{call_uuid}.mp3`
- `generate_presigned_url(key, expires_in)` — time-limited public URL
  for dashboard playback without exposing credentials
- `delete_recording(key)` — for DPDP retention compliance

Zero egress fees on R2 make dashboard playback effectively free.

### Post-call summariser (`postcall/summarizer.py`)

Calls Sarvam 105b with a strict prompt asking for JSON of the form:

```json
{
  "outcome": "interested | not_interested | call_back | wrong_number | completed | other",
  "summary": "3-5 sentence natural language summary in English",
  "next_action": "concise action recommendation for the sales team"
}

Returns a safe fallback dict on any failure so the call record still
persists.

Recording flow (api/server.py)
Two endpoints, deliberately separate:

/recording-ready — Vobiz fires this when recording STARTS.
We log only; the file does not exist yet.

/recording-complete — Vobiz fires this when the MP3 is ready.
We fetch metadata from the Vobiz API, download the audio with
auth headers, upload to R2, and persist the R2 key to
calls.recording_url.

Summary trigger
_generate_and_persist_summary is a fire-and-forget background task
scheduled in the WebSocket finally block. It:

Reads the transcript from Supabase

Calls the summariser

Persists summary (JSONB) and outcome to the calls row

Errors are logged but never raised — the WebSocket close must not
block on a summariser failure.

Design decisions
Split the recording webhooks. Vobiz fires recording-ready before
the file exists. Downloading there yields an empty payload. The
recording-complete callbackUrl is the correct trigger.

Fire-and-forget summary. The summary takes 5–15 seconds at
Sarvam. Blocking the WebSocket close would delay Vobiz's hangup
callback and could cause cascading retries.

Fallback dict on failure. If both the primary and any future
fallback fail, we still want the call record to have a valid
summary field. Better a placeholder than a NULL that breaks the
dashboard.

Validation
R2 round-trip test: upload 1 KB payload, generate presigned URL,
delete.

Summariser test: mixed Hindi/English transcript produces valid
JSON with outcome in the expected enum.

End-to-end call: recording uploaded, summary persisted,
calls.outcome set.

Known gaps (at end of Phase 4)
No retry on transient failures (Phase 5.3)

No fallback provider for summariser (Phase 5.5)

No PII masking before summary (Phase 5.7.4)
