# Voice Agent — IT-Webhut

A multilingual AI voice calling agent that makes and receives real
phone calls in Hindi, English, and Tamil.

## Live deployment

- **Frontend**: https://voice-agent-ochre-two.vercel.app
- **Backend**: https://voice-agent-bhnm.onrender.com

## Status

Phase 7 (frontend) complete. Backend deployment to Render is the
next step.

## Stack

| Layer | Technology |
|---|---|
| Voice pipeline | Pipecat 1.10 |
| STT | Sarvam Saaras v3 |
| LLM (in-call) | Sarvam 105b-conversations |
| TTS | Sarvam Bulbul v3 |
| Telephony | Vobiz |
| Backend | FastAPI + uvicorn |
| Frontend | Next.js 16 + Tailwind v4 + shadcn/ui |
| Session state | Upstash Redis |
| Database | Supabase Postgres |
| Object storage | Cloudflare R2 |
| Frontend hosting | Vercel |

## Repository layout
src/voice_agent/ FastAPI backend, Pipecat pipeline
frontend/ Next.js dashboard
tests/ Unit and integration tests
scripts/ Local dev runners
docs/
├── schema.sql Database schema
├── compliance.md Regulation-to-code mapping
├── fallback-design.md Provider fallback plan
└── dev-log/ Per-phase development log


## Development

Backend:

```bash
python -m uvicorn voice_agent.api.server:app --host 0.0.0.0 --port 8000

## Frontend:
cd frontend
npm run dev

Environment variables are documented in .env.example.

## Full documentation:
Detailed setup and deployment instructions are being written in
Phase 9. Until then, docs/dev-log/ records the decisions behind
each phase of the build.
