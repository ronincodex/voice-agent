# Fallback Design

## Tier 1: Batch operations (implemented, Phase 5.5)

Provider mapping:
- Sarvam 105b -> Groq Llama 3.3 70B (summariser)

Mechanism: `voice_agent.observability.fallback.with_fallback()`.
Transient exceptions that trigger fallback: TimeoutError, ConnectionError,
httpx.TransportError, httpx.TimeoutException.

Structured log events:
- `fallback_triggered from=<primary> to=<fallback> error=<class> msg=<text>`
- `fallback_success provider=<fallback>`
- `primary_failed fallback_disabled provider=<primary>` when disabled

Client errors (4xx other than 429) are NOT retried, they will fail
identically on the fallback provider. This is enforced by only catching
the transient exceptions listed above.

## Tier 2: Real-time pipeline (Phase 5.5b, not implemented)

STT, LLM, and TTS run mid-call over WebSockets. A naive try/except
cannot switch providers mid-stream without losing buffered audio and
conversation context. Pipecat 1.10 provides:

- `pipecat.pipeline.service_switcher.ServiceSwitcher`
- `ServiceSwitcherStrategyFailover`:  auto-switch on service error

Before implementing, verify the exact API surface:

    python -c "from pipecat.pipeline.service_switcher import ServiceSwitcher, ServiceSwitcherStrategyFailover; import inspect; print(inspect.signature(ServiceSwitcher))"
    python -c "from pipecat.pipeline.service_switcher import ServiceSwitcherStrategyFailover; import inspect; print(inspect.signature(ServiceSwitcherStrategyFailover))"

Planned provider mapping:
- STT: Sarvam Saaras -> Groq Whisper
- LLM: Sarvam 105b-conversations -> Groq Llama 3.3 70B
- TTS: no fallback (voice consistency across a single call is more
  important than availability; if Sarvam Bulbul is down the call
  degrades to silence rather than to a different voice mid-sentence)

Tier 2 also addresses the intermittent SarvamSTTService keepalive
timeout observed in Phase 5.4 testing (13:13 log). The strategy
failover would switch to Groq Whisper after the first keepalive
failure instead of waiting for Pipecat's silent reconnect.
