# Compliance Documentation
## TRAI TCCCPR 2018
## DPDP Act 2023
## Prompt Injection Defense
## Audit Trail
## Known Gaps
## How to Add a New Language
## How to Export an Evidence Packet for an Auditor

# Compliance Documentation

This document maps each applicable regulatory obligation to the code
that implements it. It does not claim full compliance; it provides a
clear path from regulation to code.

**Last updated**: 2026-10-02
**Applicable regulations**: TRAI TCCCPR 2018, DPDP Act 2023
**Retention baseline**: 1 year (DPDP Rules 2025, Rule 8(3))

---

## TRAI TCCCPR 2018

| Requirement | Implementation | Evidence |
|---|---|---|
| Calling hours (9 AM - 9 PM IST) | `compliance/calling_window.py` `is_within_calling_window()`; checked in `api/server.py` `trigger_call` | `call_audit` table, `event_type='calling_hours_blocked'` |
| NDNC scrubbing | Enforced server-side by Vobiz (Vobiz integrates NDNC scrubbing into its outbound call path for Indian numbers) | Vobiz platform logs (external) |
| Local opt-out list | `dnd_optouts` table; `SupabaseStore.check_opt_out()` and `add_opt_out()` | `call_audit` table, `event_type='dnd_blocked'` or `'opt_out_requested'` |
| Consent records (6-month validity) | `calls.consent_captured_at` and `calls.disclosure_version`; captured via `LanguageConfig.consent_disclosure` | `call_audit` table, `event_type='consent_captured'` |
| Call logs | `messages` table (masked); `call_audit` table (compliance events) | Both tables queryable |
| Consent stack verification | `calls.disclosure_version` records which version of the disclosure script was played | `calls` table |
| 160-series numbers | Business setup (Vobiz dashboard) - outside code | N/A |

---

## DPDP Act 2023

| Requirement | Implementation | Evidence |
|---|---|---|
| Free, specific, informed, unconditional, unambiguous consent | `LanguageConfig.consent_disclosure` played immediately after greeting; `record_consent` tool handles accept/decline | `call_audit` table, `event_type='consent_captured'` or `'consent_declined'` |
| Consent logs (obtained, modified, withdrawn) | Every consent decision writes to `call_audit`; `calls.consent_captured_at` records timestamp | `call_audit` table |
| Processing activity records | `calls` table (language, direction, duration); `messages` table (transcript) | Supabase tables |
| Data retention schedule | `messages` table atomically replaced via RPC; `call_audit` table append-only | `docs/schema.sql` |
| Data principal requests (access, correction, erasure) | Local opt-out list via `request_opt_out` tool for immediate "do not call"; full request portal deferred to Phase 7 | `dnd_optouts` table |
| Breach notification | Deferred to Phase 7 (requires incident response playbook) | N/A |
| Cross-border transfers | Deferred to Phase 7 (data residency verification) | N/A |
| Grievance redressal | Deferred to Phase 7 | N/A |
| Children's data | Out of scope - B2B outbound only | N/A |
| Evidence packet | `call_audit` table exportable as evidence packet | See export queries below |

---

## Prompt Injection Defense

| Pattern family | Source |
|---|---|
| Instruction override (ignore/disregard/forget + prior instructions) | OWASP LLM Prompt Injection Prevention Cheat Sheet |
| New instructions marker | Same |
| System prompt extraction | Same |
| Role manipulation / jailbreak | Same |
| ChatML special-token injection | Same |
| Do-not-follow / supersede / void | Same |

**Implementation**: `pipeline/guardrail.py` `PromptInjectionGuard`. Pure regex, no I/O.

**Known gap**: Regex only; no ML classifier. Sophisticated injections may bypass. Mitigation is the Flows tool guard in `nodes.py` which validates caller intent against literal words before any destructive action.

---

## Audit Trail

`call_audit` table, append-only. Nine event types: `consent_captured`, `consent_declined`, `guardrail_prompt_injection`, `dnd_blocked`, `calling_hours_blocked`, `opt_out_requested`, `pii_masked`, `call_started`, `call_ended`.

**Query example**:

```sql
SELECT event_type, event_data, created_at
FROM call_audit
WHERE call_uuid = '<UUID>'
ORDER BY created_at;

---

## Known Gaps

The following table lists every compliance or safety feature that is
**not yet implemented**. Each row records the reason and the planned
phase that will address it.

| Gap | Reason | Future work |
|---|---|---|
| ML-based injection detection | Pipecat's synchronous frame-processing constraint prevents in-frame inference | Sidecar classifier (Phase 5.5b) |
| Real-time PII masking | Pipeline latency budget cannot accommodate a per-frame masking call | Deferred; post-call masking only |
| DLT registration | Business process, not code | Manual, outside code |
| 140/160-series numbers | Business process, not code | Manual, outside code |
| Data residency verification | Requires cloud-provider region audit | Phase 7 |
| Breach notification playbook | Requires incident response procedure | Phase 7 |
| Data principal request portal | Requires authenticated self-service UI | Phase 7 |
| Cross-border transfer documentation | Requires data-flow mapping | Phase 7 |
| Grievance redressal logging | Requires intake workflow | Phase 7 |
| Evidence packet export tooling | UI-level feature | Phase 7 |
| "Speak twice" interruption race | Pipecat playback/capture interaction | Phase 6 |

**Retention reminder**: DPDP Rules 2025, Rule 8(3) requires processing
logs to be retained for at least one year. The `call_audit` table
currently retains indefinitely, which exceeds the minimum.

---

## How to Add a New Language

Adding a language is a **configuration change**, not a code change.
Follow these four steps.

### Step 1 — Add a `LanguageConfig` entry

Open `src/voice_agent/config/languages.py` and add an entry to the
`LANGUAGES` dict. Populate every field, including the compliance
fields:

- `consent_disclosure` — the AI-and-recording disclosure played at
  call opening (DPDP Act 2023).
- `consent_decline_ack` — the farewell spoken when the caller
  declines consent.
- `guardrail_deflect` — the deflect message spoken when the prompt
  injection guard blocks an utterance.

Example skeleton:

\`\`\`python
"te-IN": LanguageConfig(
    code="te-IN",
    name="Telugu",
    persona_name="సిరి",
    persona_gender="female",
    stt_locale="te-IN",
    tts_voice="siri",
    tts_language_code="te-IN",
    llm_prompt_suffix="Respond naturally in Telugu. Use Telugu script.",
    greeting="నమస్కారం! నేను IT-Webhut నుండి {name} మాట్లాడుతున్నాను...",
    scope_redirect="క్షమించండి, ఈ విషయంలో నేను సహాయం చేయలేను...",
    farewell="ధన్యవాదాలు! మీ రోజు శుభంగా ఉండాలి.",
    farewell_wrong_number="తప్పు నంబర్ కోసం క్షమించండి. ధన్యవాదాలు.",
    consent_disclosure="ఈ కాల్ AI సహాయకుడిచే నిర్వహించబడుతోంది...",
    consent_decline_ack="అర్థమైంది. మీ రోజు శుభంగా ఉండాలి.",
    guardrail_deflect="దీనిలో నేను సహాయం చేయలేను. మన సంభాషణకు తిరిగి వెళ్దామా?",
),
\`\`\`

### Step 2 — Update the greeting placeholder

Confirm `greeting` contains the `{name}` placeholder. The
`LanguageConfig.get_greeting()` method substitutes `persona_name`
into it.

### Step 3 — Add a unit test

Open `tests/unit/test_languages.py`. Add an assertion that:

- The new code is present in `LANGUAGES`.
- `consent_disclosure`, `consent_decline_ack`, and `guardrail_deflect`
  are all non-empty.
- `get_greeting()` returns a string that does not contain `{name}`.

### Step 4 — Run quality checks

\`\`\`bash
ruff format src/voice_agent/ tests/ scripts/
ruff check src/voice_agent/ tests/ scripts/
mypy src/voice_agent/ tests/ scripts/
python -m compileall src/voice_agent/ tests/ scripts/ -q
\`\`\`

No other code changes are required. The pipeline reads the new
`LanguageConfig` automatically when a call is placed with the new
language code.

---

## How to Export an Evidence Packet for an Auditor

When a Data Protection Board or TRAI inquiry requires evidence for a
specific call, run the four queries below against Supabase. The
resulting rows form a complete, self-contained evidence packet.

### Query 1 — Full audit trail

\`\`\`sql
SELECT event_type, event_data, created_at
FROM call_audit
WHERE call_uuid = '<UUID>'
ORDER BY created_at;
\`\`\`

Returns every compliance-relevant event for the call: consent
capture, refusal classification, PII masking, opt-out request,
guardrail action, calling-hour block, and call lifecycle events.

### Query 2 — Call metadata

\`\`\`sql
SELECT call_uuid, direction, from_number, to_number, language,
       status, started_at, ended_at, duration_seconds,
       consent_captured_at, disclosure_version,
       recording_url, outcome
FROM calls
WHERE call_uuid = '<UUID>';
\`\`\`

Returns the call record: who called whom, when, how long, under
which consent version, and the AI-classified outcome.

### Query 3 — Masked transcript

\`\`\`sql
SELECT role, text
FROM messages
WHERE call_id = (SELECT id FROM calls WHERE call_uuid = '<UUID>')
ORDER BY created_at;
\`\`\`

Returns the transcript with all PII already masked
(`XXXX-XXXX-1234` for Aadhaar, `ABCDE1XXXX` for PAN, `[phone]`,
`[email]`, `[card]`). Plaintext PII is not stored.

### Query 4 — PII masking evidence

\`\`\`sql
SELECT event_data
FROM call_audit
WHERE call_uuid = '<UUID>' AND event_type = 'pii_masked';
\`\`\`

Returns a JSON object of the form
`{"counts": {"aadhaar": N, "phone": M, ...}}` proving that PII was
detected and masked on this call.

### Exporting the packet

To bundle all four queries into a single JSON file:

\`\`\`bash
psql "\$SUPABASE_DB_URL" -c "
  SELECT json_build_object(
    'audit',     (SELECT json_agg(call_audit)     FROM call_audit     WHERE call_uuid = '<UUID>'),
    'call',      (SELECT row_to_json(calls)        FROM calls          WHERE call_uuid = '<UUID>'),
    'messages',  (SELECT json_agg(messages)        FROM messages       WHERE call_id IN (SELECT id FROM calls WHERE call_uuid = '<UUID>')),
    'pii_event', (SELECT json_agg(call_audit)      FROM call_audit     WHERE call_uuid = '<UUID>' AND event_type = 'pii_masked')
  );
" > evidence_<UUID>.json
\`\`\`

### Retention

The `call_audit` table is append-only and retained indefinitely.
DPDP Rules 2025, Rule 8(3) requires at least one year. Beyond that,
Supabase's automatic backup window applies.

### Reproducibility

The four queries above are deterministic. Re-running them produces
the same output. This satisfies the Data Protection Board's
expectation that evidence can be produced on request within a
reasonable time.
