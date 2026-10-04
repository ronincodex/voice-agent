/**
 * TypeScript mirrors of the Pydantic models in
 * src/voice_agent/api/schemas.py.
 *
 * Keep these in sync manually. A drift here surfaces as a runtime
 * `undefined` in the frontend, not as a compile error, which is
 * why every field has an explicit type and every optional field
 * uses `| null` rather than `?`.
 */

export interface ApiResponse<T> {
  success: boolean;
  data: T;
}

export interface PaginatedResponse<T> {
  success: boolean;
  data: T[];
  total: number;
  page: number;
  limit: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface CallStats {
  total: number;
  completed: number;
  failed: number;
  in_progress: number;
}

export interface CallSummary {
  call_uuid: string;
  direction: "inbound" | "outbound";
  from_number: string;
  to_number: string;
  language: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  outcome: string | null;
  recording_url: string | null;
}

export interface TranscriptMessage {
  role: "user" | "assistant" | "system" | "tool";
  text: string;
  created_at: string;
}

export interface CallSummaryData {
  outcome: string;
  summary: string;
  next_action: string;
}

export interface CallDetail extends CallSummary {
  answered_at: string | null;
  failure_reason: string | null;
  consent_captured_at: string | null;
  disclosure_version: string | null;
  summary: CallSummaryData | null;
  messages: TranscriptMessage[];
}

export interface RecordingUrl {
  url: string;
  expires_in: number;
}

export interface VoiceOverride {
  tts_voice?: string;
  tts_language_code?: string;
  stt_locale?: string;
}

export interface AgentConfig {
  agent_name: string;
  company_name: string;
  company_info: string;
  objective: string;
  personality: string;
  greeting_template: string;
  max_call_duration_seconds: number;
  primary_language: string;
  supported_languages: string[];
  voice_overrides: Record<string, VoiceOverride>;
  config_key: string;
  updated_at: string | null;
}
