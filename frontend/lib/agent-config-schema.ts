import { z } from "zod";

/**
 * Client-side mirror of the backend's AgentConfigPayload in
 * src/voice_agent/api/schemas.py.
 *
 * The backend re-validates on every PUT. This schema exists only
 * for immediate feedback, a red message under a field instead of
 * a toast after a round trip. If the two schemas drift, the server
 * is authoritative and the UI will show the server's error.
 *
 * Cross-field rules:
 *   - primary_language must be in supported_languages
 *   - every voice_overrides key must be in supported_languages
 * Both are enforced here for instant feedback and again on the
 * backend for safety.
 */

export const LANGUAGE_CODES = ["hi-IN", "en-IN", "ta-IN"] as const;

export const VoiceOverrideSchema = z.object({
  tts_voice: z.string().optional(),
  tts_language_code: z.string().optional(),
  stt_locale: z.string().optional(),
});

export const AgentConfigSchema = z
  .object({
    agent_name: z
      .string()
      .min(1, "Agent name is required")
      .max(64, "Agent name must be 64 characters or fewer"),
    persona_gender: z.enum(["female", "male", "neutral"]),
    company_name: z
      .string()
      .min(1, "Company name is required")
      .max(128, "Company name must be 128 characters or fewer"),
    company_info: z
      .string()
      .max(4000, "Company info must be 4000 characters or fewer"),
    objective: z
      .string()
      .min(1, "Objective is required")
      .max(1000, "Objective must be 1000 characters or fewer"),
    personality: z
      .string()
      .min(1, "Personality is required")
      .max(1000, "Personality must be 1000 characters or fewer"),
    greeting_template: z
      .string()
      .min(1, "Greeting is required")
      .max(1000, "Greeting must be 1000 characters or fewer"),
    max_call_duration_seconds: z
      .number()
      .int()
      .min(30, "Minimum 30 seconds")
      .max(3600, "Maximum 60 minutes"),
    primary_language: z.string().min(2).max(10),
    supported_languages: z
      .array(z.string())
      .min(1, "Select at least one language")
      .max(10, "No more than 10 languages"),
    voice_overrides: z.record(z.string(), VoiceOverrideSchema),
  })
  .refine(
    (data) => data.supported_languages.includes(data.primary_language),
    {
      message: "Primary language must be one of the supported languages",
      path: ["primary_language"],
    },
  )
  .refine(
    (data) =>
      Object.keys(data.voice_overrides).every((key) =>
        data.supported_languages.includes(key),
      ),
    {
      message: "Voice override keys must be supported languages",
      path: ["voice_overrides"],
    },
  );

export type AgentConfigFormValues = z.infer<typeof AgentConfigSchema>;
