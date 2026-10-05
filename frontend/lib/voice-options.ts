/**
 * Curated voice options for each supported language.
 *
 * Source: Sarvam Bulbul v3 documentation
 * (docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/voices)
 *
 * Voice quality varies by language. The docs publish per-language
 * speaker recommendations. We surface only the recommended voices
 * (Tier 1 and Tier 2) rather than all 30+ options, so an operator
 * cannot accidentally pick a voice that performs poorly in that
 * language.
 *
 * Speaker names must be lowercase. The API rejects 'Priya' but
 * accepts 'priya'.
 *
 * To add a voice: append an entry with the exact lowercase ID from
 * the Sarvam docs. The backend pipeline reads voice_overrides and
 * passes the value to SarvamTTSService.Settings(voice=...).
 */

export interface VoiceOption {
  id: string;
  label: string;
  gender: "male" | "female";
}

export const VOICE_OPTIONS: Record<string, VoiceOption[]> = {
  "hi-IN": [
    { id: "priya", label: "Priya — Cheerful & Engaging", gender: "female" },
    { id: "ishita", label: "Ishita — Polished & Articulate", gender: "female" },
    { id: "shubh", label: "Shubh — Confident & Bold", gender: "male" },
  ],
  "en-IN": [
    { id: "priya", label: "Priya — Cheerful & Engaging", gender: "female" },
    { id: "ishita", label: "Ishita — Polished & Articulate", gender: "female" },
    { id: "ratan", label: "Ratan — Rich & Mature", gender: "male" },
  ],
  "ta-IN": [
    { id: "priya", label: "Priya — Cheerful & Engaging", gender: "female" },
    { id: "ishita", label: "Ishita — Polished & Articulate", gender: "female" },
    { id: "ratan", label: "Ratan — Rich & Mature", gender: "male" },
  ],
};

/**
 * Default voice per language, matching the values in the backend's
 * languages.py. Duplicated here because the frontend cannot import
 * Python. If the backend defaults change, update both files.
 */
export const DEFAULT_VOICES: Record<string, string> = {
  "hi-IN": "ishita",
  "en-IN": "priya",
  "ta-IN": "kavitha",
};

export function getDefaultVoice(langCode: string): string {
  return DEFAULT_VOICES[langCode] ?? "priya";
}
