# Known Gaps

An honest accounting of what this project does not do, and why.

## Not Implemented

| Gap | Reason | Impact | Deferred to |
|---|---|---|---|
| ML-based prompt injection detection | Pipecat's synchronous frame processing prevents in-frame inference | Regex guard catches common cases; sophisticated attacks may bypass | Sidecar classifier (post-project) |
| Real-time PII masking | Pipeline latency budget cannot accommodate per-frame masking | PII is masked in the stored transcript, not during the call | Not planned |
| PlayedTextTracker placement | The tracker sits after `transport.output()`, which consumes `TTSTextFrame`s before our processor sees them | Assistant context-loss is instrumented but not detected | Requires Pipecat internals work |
| Cross-border transfer documentation | Requires data-flow mapping | DPDP compliance for international data transfer is undocumented | Phase 7 (business process) |
| Data principal request portal | Requires authenticated self-service UI | "Right to access" and "right to erasure" cannot be self-served | Phase 7 (business process) |
| Grievance redressal logging | Requires intake workflow | No formal complaint tracking | Phase 7 (business process) |
| Breach notification playbook | Requires incident response procedure | No documented process for a data breach | Phase 7 (business process) |
| DLT registration | Business process, not code | Outbound SMS/calls may be blocked by Indian carriers without DLT registration | Manual, outside code |
| 140/160-series numbers | Business process, not code | The current Vobiz number is a standard mobile-range number | Manual, outside code |
| Real-time provider fallback (Tier 2) | Requires Pipecat's `ServiceSwitcher`; not implemented | If Sarvam STT/LLM/TTS fails mid-call, the call fails | Phase 5.5b |
| Mobile-responsive sidebar | Sidebar is `hidden md:flex`; no drawer menu below 768px | Mobile users see no navigation | Phase 7.9 |
| Render cold start | Free tier spins down after 15 min idle | First call after idle waits ~60s for wake | Phase 9 (cron ping) |
| Cron-ping keepalive | Free external service not yet configured | Cold starts during demo | Phase 9 |
| OpenAPI-generated frontend types | Manual type mirroring between Pydantic and TypeScript | Type drift possible if a field is added on one side only | Post-project |
| Bulk language addition UI | Languages are added in `languages.py`, not from the config UI | Adding a new language requires a code change | Post-project |
| Per-language voice recording preview | The voice selector plays no sample before committing | Operator selects blind | Post-project |
| Callback scheduling | The agent records "call back at 10 AM" but no task is created | Follow-ups are manual | Post-project |

## Known Bugs

| Bug | Severity | Reproduction |
|---|---|---|
| LLM occasionally emits bracketed placeholders | Low | Observed once: "here is my question: (insert your repeated question here)". The `TTSInputSanitizer` catches whole-message placeholders only. | 
| Single-word affirmatives blocked during bot speech | Low | `MinWordsUserTurnStartStrategy(min_words=2)` blocks "yes"/"हाँ" while the bot is speaking. The caller must say two words. |

## Known Limitations

- **Prompt injection detection is regex-only.** No ML classifier. Sophisticated injections may bypass.
- **The transcript in the call detail page shows masked PII.** The original plaintext is never stored.
- **The `call_audit` table grows indefinitely.** DPDP Rules 2025 require retention for at least one year; we exceed that.
- **No automated tests for the frontend.** React components are verified manually.
- **Historical transcripts before the Phase 8 PII fix show only two messages per call.** The fix is forward-looking.
- **The agent cannot hang up without explicit caller authorization.** By design — see `validators.py`.
