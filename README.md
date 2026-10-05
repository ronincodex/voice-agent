# Voice Agent — IT-Webhut

A multilingual AI voice calling agent that makes and receives real phone calls in Hindi, English, and Tamil.

## Live Deployment

| Component | URL |
|---|---|
| Frontend | https://voice-agent-ochre-two.vercel.app |
| Backend | https://voice-agent-bhnm.onrender.com |
| GitHub | https://github.com/ronincodex/voice-agent |

## What It Does

- **Places outbound calls** from the Vobiz number +91 80654 80214
- **Receives inbound calls** and routes them to the language-specific agent
- **Conducts a real conversation** in Hindi, English, or Tamil with natural voice
- **Handles interruption** — the caller can cut off the bot mid-sentence
- **Captures DPDP consent** at call opening with a per-language disclosure
- **Masks PII** (Aadhaar, PAN, phone, email, card) in stored transcripts
- **Blocks prompt injection** before the LLM sees the input
- **Enforces a TRAI-compliant calling window** (9:00 AM – 8:45 PM IST; 15-minute buffer before the 9 PM cutoff) and a local opt-out list
- **Generates an AI summary** after each call with outcome and next action
- **Records and stores** every call in Cloudflare R2
- **Shows everything** in a Next.js dashboard

## Architecture

```text
Phone
  └─> Vobiz
        └─> VobizXML (/answer or /incoming)
              └─> WebSocket /ws
                    └─> Pipecat Pipeline (STT → LLM → TTS)
                          └─> Pipecat Flows State Machine
                                greeting → consent → qualify → confirm → closing → [terminate]
                    └─> Supabase (calls, messages, call_audit, dnd_optouts, agent_configs)
                    └─> Upstash Redis (session state)
                    └─> Cloudflare R2 (recordings)
```

## Stack

| Layer | Technology |
|---|---|
| Voice pipeline | Pipecat 1.12 |
| STT | Sarvam Saaras v3 |
| LLM (in-call) | Sarvam 105b-conversations |
| LLM (summaries) | Sarvam 105b → Groq gpt-oss-120b fallback |
| TTS | Sarvam Bulbul v3 |
| Telephony | Vobiz |
| Backend | FastAPI + uvicorn |
| Frontend | Next.js 16 + Tailwind v4 + shadcn/ui |
| Session state | Upstash Redis |
| Database | Supabase Postgres |
| Object storage | Cloudflare R2 |
| Backend hosting | Render |
| Frontend hosting | Vercel |

## Repository Layout

```text
.
├── src/voice_agent/
│   ├── api/                 # FastAPI app + WebSocket + webhooks
│   ├── compliance/          # calling_window, pii
│   ├── config/              # languages, settings
│   ├── db/                  # agent_config, audit, supabase_client
│   ├── observability/       # fallback, idempotency, logging, metrics, retry
│   ├── pipeline/            # agent_pipeline, guardrail, nodes, validators
│   ├── postcall/            # summarizer.py
│   ├── state/               # redis_store.py
│   ├── storage/             # r2_client.py
│   └── telephony/           # call_state, client
├── frontend/
│   ├── app/                 # Next.js App Router
│   ├── components/          # React components
│   └── lib/                 # api, types, search-params, voice-options
├── tests/
│   ├── unit/                # Unit tests
│   └── integration/         # Orchestrators
├── scripts/                 # Local dev runners
└── docs/
    ├── schema.sql           # Database schema
    ├── compliance.md        # Regulation-to-code mapping
    ├── provider-evaluation.md # Why each provider was chosen
    ├── cost-analysis.md     # Per-call and monthly cost
    ├── known-gaps.md        # Honest accounting of what is not done
    ├── fallback-design.md   # Provider fallback plan
    ├── samples/             # Sample transcript and recording
    └── dev-log/             # Per-phase development log
```

## Local Setup

### Prerequisites

- Python 3.11+
- Node.js 20.9+
- Accounts on: Sarvam, Groq, Vobiz, Supabase, Upstash, Cloudflare R2

### 1. Clone and create the environment

```bash
git clone git@github.com:ronincodex/voice-agent.git
cd voice-agent
conda create -n voice-agent python=3.11
conda activate voice-agent
pip install -e ".[dev]"
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Fill in every value. See `.env.example` for the complete list with comments.

### 3. Set up the database

Open the Supabase SQL Editor and paste the contents of `docs/schema.sql`. Click **Run**.

### 4. Run locally

Backend:

```bash
python -m uvicorn voice_agent.api.server:app --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>. The dashboard should load with live counters.

### 5. Expose the backend publicly (for telephony)

Vobiz needs to reach your backend. Use ngrok:

```bash
ngrok http 8000
```

Copy the ngrok URL into `PUBLIC_BASE_URL` in `.env` and restart uvicorn.

## Deployment

### Backend — Render

1. Push the repo to GitHub.
2. In Render: **New +** → **Blueprint** → connect the repo.
3. Render reads `render.yaml` and provisions the web service.
4. Add secrets in the Render dashboard: every `sync: false` variable from `render.yaml`.
5. After first deploy, set `PUBLIC_BASE_URL` to the `onrender.com` URL and `FRONTEND_ORIGINS` to include both localhost and the Vercel URL.

- Python version: pinned via `.python-version` to `3.11.9`.
- Build command: `pip install --upgrade pip && pip install -r requirements.txt && pip install -e .`
- The `-e .` is required — the project uses a `src` layout.

### Frontend — Vercel

1. In Vercel: **Add New** → **Project** → import the repo.
2. Set **Root Directory** to `frontend/`.
3. Set Environment Variable `NEXT_PUBLIC_API_BASE_URL` to the Render URL for Production, Preview, and Development.
4. Deploy.

## Environment Variables

See `.env.example` for the complete list with comments. Categories:

- AI services: Sarvam, Groq
- Telephony: Vobiz
- Database: Supabase
- Cache: Upstash Redis
- Storage: Cloudflare R2
- Application: language defaults, fallback flags
- Compliance: calling-hour bypass, frontend origins, public base URL

## Testing

```bash
# Unit tests
pytest tests/unit/test_pii.py
pytest tests/unit/test_guardrail.py
pytest tests/unit/test_barge_in.py
pytest tests/unit/test_bulbul.py
pytest tests/unit/test_audit.py
pytest tests/unit/test_redis_store.py
pytest tests/unit/test_settings.py
pytest tests/unit/test_summarizer.py
pytest tests/unit/test_supabase.py
pytest tests/unit/test_idempotency.py

# Full suite
pytest tests/integration/test_phase_5_7.py
pytest tests/integration/test_phase_6.py
```

## Compliance

Compliance with TRAI TCCCPR 2018 and DPDP Act 2023 is implemented at the code level. See `docs/compliance.md` for the full regulation-to-code mapping.

Highlights:

- **Consent:** AI and recording disclosure in each language.
- **Calling hours:** 9:00 AM – 8:45 PM IST enforced server-side (15-minute buffer before the TRAI 9 PM cutoff).
- **Opt-out:** Local `dnd_optouts` table, E.164 normalized.
- **PII:** Aadhaar, PAN, phone, email, card masked in stored transcripts.
- **Audit:** Every compliance event written to `call_audit`.
- **Prompt injection:** Six regex families blocked before the LLM.

## Provider Choices

See `docs/provider-evaluation.md` for the full evaluation. Summary: Sarvam for STT, LLM, and TTS because it is one of the few providers with native Indian-language support and strong code-switching performance. Vobiz for telephony because of its flat INR pricing and NDNC integration.

## Cost

Per-call cost is approximately ₹6.29 for a 2-minute call. See `docs/cost-analysis.md` for the breakdown and monthly projections.

## Known Gaps

See `docs/known-gaps.md` for an honest accounting of what is not implemented and why.

## License

Proprietary. IT-Webhut internal project.
