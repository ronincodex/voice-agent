-- Voice Agent Database Schema

-- This schema is deployed to Supabase Postgres.
-- To rebuild the database:
--  1. Open Supabase SQL Editor
--  2. Paste this entire file
--  3. Click Run
--
-- Tables:
--  calls - One row per phone call (metadata, recording, summary)
-- messages - one row per utterance (transcript, tool calls)
--
-- RLS: enabled with service_role policies for  backend access.

-- Phase 3: Call records and transcripts

-- Calls table: one row per phone call
CREATE TABLE calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_uuid TEXT UNIQUE NOT NULL,
    direction TEXT CHECK (direction IN ('inbound', 'outbound')) NOT NULL,
    from_number TEXT NOT NULL,
    to_number TEXT NOT NULL,
    language TEXT NOT NULL,
    status TEXT DEFAULT 'initiated',
    started_at TIMESTAMPTZ DEFAULT now(),
    answered_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    duration_seconds INT,
    recording_url TEXT,
    summary JSONB,
    outcome TEXT,
    failure_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Messages table: one row per utterance
CREATE TABLE messages (
    id BIGSERIAL PRIMARY KEY,
    call_id UUID REFERENCES calls(id) ON DELETE CASCADE,
    role TEXT CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    text TEXT NOT NULL,
    tool_name TEXT,
    tool_args JSONB,
    latency_ms INT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes for fast lookups
CREATE INDEX idx_calls_call_uuid ON calls(call_uuid);
CREATE INDEX idx_messages_call ON messages(call_id, created_at);

-- Row Level Security (RLS) — enable from day one
ALTER TABLE calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;

-- Service role gets full access (backend uses this key)
CREATE POLICY "Service role full access" ON calls
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Service role full access" ON messages
    FOR ALL USING (auth.role() = 'service_role');

-- Phase 5.2: latency metrics
ALTER TABLE calls
ADD COLUMN IF NOT EXISTS metrics JSONB;

-- Phase 5.7.1: Compliance audit trail
CREATE TABLE IF NOT EXISTS call_audit (
    id BIGSERIAL PRIMARY KEY,
    call_uuid TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_data JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_call_audit_call_uuid
    ON call_audit(call_uuid, created_at);

ALTER TABLE call_audit ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access" ON call_audit
    FOR ALL USING (auth.role() = 'service_role');

-- Phase 5.7.2: DPDP consent capture
ALTER TABLE calls
ADD COLUMN IF NOT EXISTS consent_captured_at TIMESTAMPTZ;

ALTER TABLE calls
ADD COLUMN IF NOT EXISTS disclosure_version TEXT;

-- Phase 5.7.3: DND out-put list.
CREATE TABLE IF NOT EXISTS dnd_optouts (
    phone_number TEXT PRIMARY KEY,
    reason TEXT,
    source_call_uuid TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE dnd_optouts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access" ON dnd_optouts
    FOR ALL USING (auth.role() = 'service_role');


-- Phase 5.7.4: Atomic transcript replacement
CREATE OR REPLACE FUNCTION public.replace_call_messages(
    p_call_id UUID,
    p_messages JSONB
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    DELETE FROM public.messages WHERE call_id = p_call_id;
    INSERT INTO public.messages (call_id, role, text)
    SELECT
        p_call_id,
        (elem->>'role')::text,
        (elem->>'text')::text
    FROM jsonb_array_elements(p_messages) AS elem;
END;
$$;

REVOKE ALL ON FUNCTION public.replace_call_messages(uuid, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.replace_call_messages(uuid, jsonb) TO service_role;

-- Phase 7.2: Agent configuration
-- Singleton row holding the runtime config for the calling agent.
-- The CHECK constraint pins config_key to the literal 'default',
-- so a second row is impossible even by accident. The primary key
-- gives Supabase's upsert() a conflict target.
--
-- Typed columns hold the fields the frontend form edits directly.
-- The voice_overrides JSONB holds per-language TTS voice and STT
-- locale selections, keyed by BCP-47 code, so adding a language is
-- a data change, not a schema migration.

CREATE TABLE IF NOT EXISTS agent_configs (
    config_key TEXT PRIMARY KEY DEFAULT 'default'
        CHECK (config_key = 'default'),
    agent_name TEXT NOT NULL DEFAULT 'Priya',
    company_name TEXT NOT NULL DEFAULT 'IT-Webhut',
    company_info TEXT NOT NULL DEFAULT '',
    objective TEXT NOT NULL DEFAULT 'Qualify inbound leads and schedule follow-ups.',
    personality TEXT NOT NULL DEFAULT
        'Professional, friendly, empathetic and conversational.',
    greeting_template TEXT NOT NULL DEFAULT
        'Hello! I''m {name} calling from {company}. Is this a good time to speak?',
    max_call_duration_seconds INT NOT NULL DEFAULT 600
        CHECK (max_call_duration_seconds BETWEEN 30 AND 3600),
    primary_language TEXT NOT NULL DEFAULT 'en-IN',
    supported_languages TEXT[] NOT NULL DEFAULT ARRAY['hi-IN', 'en-IN', 'ta-IN'],
    voice_overrides JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed the singleton row if the table is empty. ON CONFLICT DO NOTHING
-- keeps this idempotent.
INSERT INTO agent_configs (config_key) VALUES ('default')
ON CONFLICT (config_key) DO NOTHING;

ALTER TABLE agent_configs ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'agent_configs'
          AND policyname = 'Service role full access'
    ) THEN
        CREATE POLICY "Service role full access" ON agent_configs
            FOR ALL USING (auth.role() = 'service_role');
    END IF;
END $$;
