# Cost Analysis

Every service the project uses, with the free-tier boundaries, the
paid pricing, and a per-call cost calculation.

## Per-Call Cost

Assume an average call of 2 minutes. The agent speaks ~1,200 characters, the caller speaks ~800 characters (transcribed).

| Component | Quantity per call | Unit price | Cost per call |
|---|---|---|---|
| STT (Sarvam Saaras v3) | 2 min audio | ₹30/hr | **₹1.00** |
| TTS (Sarvam Bulbul v3) | 1,200 chars | ₹30/10K chars | **₹3.60** |
| LLM (Sarvam 105b) | ~8K tokens in, ~2K out | ₹29.28/₹73.2 per 1M | **₹0.39** |
| Telephony (Vobiz) | 2 min | ₹0.65/min | **₹1.30** |
| Storage (R2) | 500 KB recording | $0.015/GB-mo | **₹0.00001** |
| Database (Supabase) | ~30 rows | Free tier | **₹0** |
| Cache (Upstash) | ~50 commands | Free tier | **₹0** |
| **Total per call** | | | **₹6.29** |

**At scale, one thousand calls per month costs approximately ₹6,290.**

The dominant cost is TTS. A caller who talks less and the agent talks more increases the LLM cost slightly but TTS dominates.

## Free Tier Boundaries

| Service | Free tier limit | What happens when exceeded |
|---|---|---|
| Sarvam | ₹100 signup credit | Pay per API call |
| Groq | Rate-limited free tier | Rate limit errors; fallback disabled |
| Vobiz | No free tier; prepaid balance | Calls fail on zero balance |
| Supabase | 500 MB DB, 1 GB storage, 50K MAU | Paused after 1 week idle; upgrade to Pro $25/mo |
| Upstash Redis | 256 MB, 500K commands/month | $0.20 per 100K commands |
| Cloudflare R2 | 10 GB storage, unlimited egress | $0.015/GB-mo beyond |
| Render | 750 instance-hours/workspace/mo | Free tier only; no paid overage |
| Vercel | 100 GB transfer, 1M invocations | Paused; upgrade to Pro $20/user/mo |
| ngrok | 1 GB transfer, 20K requests/mo | Tunnel stops |

## Monthly Cost at Different Volumes

| Volume | STT | TTS | LLM | Vobiz | Infra | Total |
|---|---|---|---|---|---|---|
| 100 calls | ₹100 | ₹360 | ₹39 | ₹130 | ₹0 | **₹629** |
| 1,000 calls | ₹1,000 | ₹3,600 | ₹390 | ₹1,300 | ₹0 | **₹6,290** |
| 10,000 calls | ₹10,000 | ₹36,000 | ₹3,900 | ₹13,000 | ₹1,500 | **₹64,400** |
| 100,000 calls | ₹100,000 | ₹360,000 | ₹39,000 | ₹130,000 | ₹15,000 | **₹644,000** |

## Paid Tiers — When to Upgrade

| Trigger | Current | Upgrade to | Cost |
|---|---|---|---|
| Supabase DB approaches 500 MB | Free | Pro | $25/mo |
| Redis exceeds 500K commands/mo | Free | Pay-as-you-go | $0.20/100K |
| R2 exceeds 10 GB | Free | Pay-as-you-go | $0.015/GB-mo |
| Render cold start impairs demo | Free | Starter | $7/mo |
| Vercel bandwidth exceeds 100 GB | Hobby | Pro | $20/user/mo |

## Cost Comparison — Why This Stack

| Alternative Stack | Cost per 2-min call | Notes |
|---|---|---|
| **Current stack (Sarvam + Vobiz)** | **₹6.29** | Native Indian languages |
| OpenAI + Twilio | ~₹21.80 | 3.5× more expensive |
| ElevenLabs + Twilio | ~₹38.50 | 6× more expensive; TTS alone is ₹32 |
| Google + Plivo | ~₹15.40 | 2.4× more expensive |

The Sarvam + Vobiz combination is the cheapest viable stack for Indian-language voice AI at this quality level.
