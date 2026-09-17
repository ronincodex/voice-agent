"""Language configuration for the voice agent pipeline.

Each language is defined as a LanguageConfig object that maps
the language to its STT locale, TTS voice, and LLM prompt modifier.

To add a new language, add a new entry to LANGUAGES dict.
No other code changes are needed.
"""

from pydantic import BaseModel, ConfigDict


class LanguageConfig(BaseModel):
    """Configuration for a single supported language."""

    model_config = ConfigDict(extra="forbid")

    code: str  # BCP-47 language code, e.g., "hi-IN"
    name: str  # Human-readable name, e.g., "Hindi"
    stt_locale: str  # Locale for STT, e.g., "hi-IN"
    tts_voice: str  # Voice ID for TTS, e.g., "ishita"
    tts_language_code: str  # Language code for TTS, e.g., "hi-IN"
    llm_prompt_suffix: str  # Instruction for the LLM, e.g., "Respond in Hindi."
    greeting: str  # Initial greeting template with {name} placeholder.
    persona_name: str  # Name the agent uses when introducing itself.
    persona_gender: str  # "female", "male", or "neutral"

    def get_greeting(self) -> str:
        """Return the greeting with the persona name substituted in.

        Keeping this as a method (rather than doing .format() at the
        call site) means any future changes to how greetings are
        rendered happen in exactly one place.
        """
        return self.greeting.format(name=self.persona_name)

    def get_system_prompt(self, base_prompt: str) -> str:
        """Compose the complete system prompt for the LLM.

        Combines the base prompt, persona identity (name + gender),
        and language-specific instructions. Gender agreement is
        critical for Hindi, Tamil, and other Indic languages where
        first-person verb forms must match the speaker's gender.
        """
        gender_agreement_hint = ""
        if self.persona_gender in ("female", "male"):
            hindi_example = (
                "say 'मैं समझती हूँ' (female), not 'मैं समझता हूँ' (male)"
                if self.persona_gender == "female"
                else "say 'मैं समझता हूँ' (male), not 'मैं समझती हूँ' (female)"
            )
            gender_agreement_hint = (
                f"\n- When speaking in a language with grammatical gender "
                f"(Hindi, Tamil, Marathi, Gujarati, Punjabi, Bengali, etc.), "
                f"always use {self.persona_gender} first-person forms for verbs, "
                f"adjectives, and pronouns. "
                f"For example (Hindi): {hindi_example}."
            )

        return (
            f"{base_prompt}\n\n"
            f"YOUR IDENTITY:\n"
            f"- Your name is {self.persona_name}.\n"
            f"- You are a {self.persona_gender} voice assistant."
            f"{gender_agreement_hint}\n\n"
            f"LANGUAGE INSTRUCTION:\n{self.llm_prompt_suffix}"
        )


LANGUAGES: dict[str, LanguageConfig] = {
    "hi-IN": LanguageConfig(
        code="hi-IN",
        name="Hindi",
        persona_name="इशिता",
        persona_gender="female",
        stt_locale="hi-IN",
        tts_voice="ishita",  # Dynamic and expressive
        tts_language_code="hi-IN",
        llm_prompt_suffix="Respond naturally in Hindi. Use Devanagari script.",
        greeting=(
            "नमस्ते! मैं IT-Webhut से {name} बोल रही हूँ। " "क्या अभी बात करने का सही समय है?"
        ),
    ),
    "en-IN": LanguageConfig(
        code="en-IN",
        name="English (India)",
        persona_name="Priya",
        persona_gender="female",
        stt_locale="en-IN",
        tts_voice="priya",
        tts_language_code="en-IN",
        llm_prompt_suffix="Respond naturally in English with an Indian context.",
        greeting=(
            "Hello! I'm {name} calling from IT-Webhut. " "Is this a good time to speak?"
        ),
    ),
    "ta-IN": LanguageConfig(
        code="ta-IN",
        name="Tamil",
        persona_name="கவிதா",
        persona_gender="female",
        stt_locale="ta-IN",
        tts_voice="kavitha",
        tts_language_code="ta-IN",
        llm_prompt_suffix="Respond naturally in Tamil. Use Tamil script.",
        greeting=(
            "வணக்கம்! நான் IT-Webhut-இல் இருந்து {name} பேசுகிறேன். "
            "இப்போது பேசுவதற்கு சரியான நேரமா?"
        ),
    ),
}


def get_language_config(language_code: str) -> LanguageConfig:
    """Get configuration for a language code.

    Raises:
        ValueError: If the language code is not supported.
    """
    if language_code not in LANGUAGES:
        supported = ", ".join(LANGUAGES.keys())
        raise ValueError(
            f"Unsupported language: {language_code}. "
            f"Supported languages: {supported}"
        )
    return LANGUAGES[language_code]
