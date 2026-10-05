# Provider Evaluation — Indian Language Voice AI

The PDF requires documenting which STT, TTS, and LLM providers were
evaluated for Indian language support, and why the final choice was
made.

## Evaluation Criteria

| Criterion | Weight | Why |
|---|---|---|
| Indian language coverage | Highest | The project must support Hindi, English, and at least one regional language from day one |
| Voice naturalness | High | Callers judge the agent by how it sounds, not by how clever it is |
| Latency | High | Turn-taking in a phone call requires sub-second response |
| Code-mixing support | Medium | Indian callers mix Hindi and English mid-sentence |
| Cost | Medium | The demo must be affordable to run |
| API stability | Medium | Downtime ruins a live demo |

## STT (Speech-to-Text)

| Provider | Hindi | Tamil | Code-Mix | Latency | Cost | Verdict |
|---|---|---|---|---|---|---|
| **Sarvam Saaras v3** | ✅ Native | ✅ Native | ✅ Hinglish, Tanglish | ~200 ms | ₹30/hr | **Chosen** |
| OpenAI Whisper Large v3 | ✅ | ✅ | ⚠️ Poor code-mix | ~800 ms | $0.006/min | Rejected: latency |
| Deepgram Nova-2 | ✅ | ✅ | ⚠️ | ~300 ms | $0.0043/min | Rejected: Hindi accuracy below Sarvam |
| Google Speech-to-Text v2 | ✅ | ✅ | ⚠️ | ~400 ms | $0.016/min | Rejected: cost, no code-mix |
| Azure Speech | ✅ | ✅ | ⚠️ | ~500 ms | $0.0093/min | Rejected: latency |

**Why Sarvam Saaras v3:** Built from scratch on Indian speech data. Handles Hinglish (Hindi+English) and Tanglish (Tamil+English) natively, which is how real Indian callers actually speak. Latency of ~200 ms is the lowest of any provider tested.

## TTS (Text-to-Speech)

| Provider | Hindi | Tamil | Naturalness | Cost | Verdict |
|---|---|---|---|---|---|
| **Sarvam Bulbul v3** | ✅ 30+ voices | ✅ | Excellent | ₹30/10K chars | **Chosen** |
| ElevenLabs Multilingual v2 | ✅ | ✅ | Excellent | $0.30/1K chars | Rejected: cost (10× Sarvam) |
| OpenAI TTS-1 | ✅ | ⚠️ Accented | Good | $15/1M chars | Rejected: Tamil accent |
| Google Cloud TTS | ✅ | ✅ | Good | $16/1M chars | Rejected: unnatural on Hindi |
| Cartesia Sonic | ✅ | ⚠️ | Very good | $0.065/1K chars | Rejected: limited Tamil voices |

**Why Sarvam Bulbul v3:** The only provider with native, natural voices in all three target languages. 30+ speaker options per language, with per-language quality ratings published in the docs. Code-mixing works — "meeting schedule" stays English within a Hindi sentence.

## LLM (Conversation)

| Provider | Hindi | Tamil | Tool Calling | Latency | Cost | Verdict |
|---|---|---|---|---|---|---|
| **Sarvam 105b-conversations** | ✅ Native | ✅ Native | ✅ OpenAI-compatible | ~600 ms | ₹29.28/1M in | **Chosen** |
| Groq Llama 3.3 70B | ✅ | ✅ | ✅ | ~200 ms | $0.59/1M in | Fallback only |
| **Groq gpt-oss-120b** | ✅ | ✅ | ✅ | ~250 ms | $0.15/1M in | **Fallback (summaries)** |
| OpenAI GPT-4o | ✅ | ✅ | ✅ | ~900 ms | $2.50/1M in | Rejected: cost |
| Anthropic Claude | ✅ | ✅ | ✅ | ~700 ms | $3.00/1M in | Rejected: cost |
| Google Gemini 1.5 Pro | ✅ | ✅ | ✅ | ~800 ms | $1.25/1M in | Rejected: cost, latency |

**Why Sarvam 105b-conversations:** Specifically tuned for Indic language conversations. Understands code-mixed input. OpenAI-compatible API means it works with Pipecat's standard LLM service interface without a custom adapter. Cost is 10× cheaper than GPT-4o.

**Why Groq as fallback:** For batch summarisation, latency matters less than reliability. Groq's gpt-oss-120b is fast and cheap. The fallback fires on transient transport errors only — never on business logic errors.

## Telephony

| Provider | India Numbers | Inbound | Outbound | WebSocket | Cost | Verdict |
|---|---|---|---|---|---|---|
| **Vobiz** | ✅ | ✅ | ✅ | ✅ Bidirectional | ₹0.65/min | **Chosen** |
| Twilio | ⚠️ Requires regulatory bundle | ✅ | ✅ | ✅ | ~₹1.08/min | Rejected: 2.4× cost, India compliance overhead |
| Plivo | ✅ | ✅ | ✅ | ✅ | ~₹0.83/min | Rejected: cost |
| Exotel | ✅ | ✅ | ✅ | ✅ | Custom | Rejected: enterprise sales cycle |
| Telnyx | ⚠️ India coverage varies | ✅ | ✅ | ✅ | Variable | Rejected: India reliability |

**Why Vobiz:** Indian company, India-denominated pricing, no forex exposure, direct support for Indian DLT registration. Flat ₹0.65/min for both directions. Vobiz also handles NDNC scrubbing server-side, which offloads TRAI compliance work.

## Storage, Database, Cache

| Service | Purpose | Chosen | Alternatives Considered |
|---|---|---|---|
| Cloudflare R2 | Call recordings | Zero egress fees | AWS S3 (egress costs), Backblaze B2 |
| Supabase | Postgres + RLS + RPC | Free tier generous, built-in auth | Neon, Railway Postgres |
| Upstash Redis | Session state | Serverless, pay-per-request | Redis Cloud, self-hosted |
| Render | Backend hosting | Free tier, WebSocket support | Railway, Fly.io, AWS ECS |
| Vercel | Frontend hosting | Zero-config Next.js | Netlify, Cloudflare Pages |

## Summary

The final stack is unified by one theme: **Indian-language-first**. Sarvam for STT, LLM, and TTS because it is the only provider with native, natural support for all three target languages. Vobiz for telephony because it is the only Indian provider with transparent INR pricing and no regulatory friction. Everything else is chosen for reliability, free-tier generosity, or integration simplicity.
