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
    scope_redirect: str  # Language-specific scope boundary message
    farewell: str  # Said immediately before ending the call.
    farewell_wrong_number: str  # Said when ending due to wrong number.
    consent_disclosure: str  # DPDP disclosure played at call opening.
    consent_decline_ack: str  # Farewell when the caller declines consent.

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
                f"\n- GENDER RULES (critical for Hindi, Tamil, Marathi, "
                f"Gujarati, Punjabi, Bengali, and other Indic languages):\n"
                f"  * FIRST-PERSON (I / मैं / நான்): Always use "
                f"{self.persona_gender} forms. "
                f"For example (Hindi): {hindi_example}.\n"
                f"  * SECOND-PERSON (you / आप / நீங்கள்): Do NOT apply "
                f"your own gender to the caller. Match the caller's gender "
                f"based on how they speak.\n"
                f"  * GENDER DETECTION FROM CALLER SPEECH:\n"
                f"    - If the caller uses masculine first-person forms "
                f"(e.g., 'मैं चाहता हूँ', 'मैं करूंगा'), respond with "
                f"masculine second-person forms (e.g., 'आप चाहते हैं', "
                f"'आप करेंगे').\n"
                f"    - If the caller uses feminine forms (e.g., "
                f"'मैं चाहती हूँ'), respond with feminine second-person "
                f"forms ('आप चाहती हैं').\n"
                f"    - If the caller's gender is unclear, use NEUTRAL or "
                f"PLURAL forms. For example: prefer 'आप क्या चाहेंगे' "
                f"(neutral) over 'चाहेंगी' (feminine) or 'चाहेंगे' "
                f"(masculine singular). When in doubt, err on the side of "
                f"neutral.\n"
                f"  * NEVER assume the caller's gender from your own persona.\n"
                f"  * IMPORTANT DEFAULT: Until the caller reveals their "
                f"gender through a first-person form, use NEUTRAL forms for "
                f"the second person. In Hindi, this means preferring "
                f"'आप क्या चाहेंगे' (neutral) over both 'चाहेंगी' (feminine) "
                f"and 'चाहेंगे' (masculine singular). In Tamil, use "
                f"'நீங்கள் என்ன செய்ய விரும்புகிறீர்கள்' (neutral) rather "
                f"than gendered alternatives.\n"
                f"  * If you are unsure, do NOT guess. Use the neutral form."
            )

        scope_boundaries = (
            "SCOPE BOUNDARIES:\n"
            f"- You are calling about a specific objective in {self.name}.\n"
            "- If the caller asks about anything unrelated to that objective "
            "(food orders, weather, jokes, general chit-chat), politely "
            f"redirect using the exact phrase: '{self.scope_redirect}'\n"
            "- After the redirect, IMMEDIATELY continue the conversation "
            "by asking a relevant question about your objective. Do NOT "
            "end the call because the caller went off-topic.\n"
            "\n"
            "*** REFUSAL SIGNALS ARE NOT OFF-TOPIC ***\n"
            "The following caller statements are REFUSALS. Do NOT apply "
            "the redirect phrase to them. Instead, call the "
            "`record_refusal` tool with a short reason:\n"
            "- English: 'I'm busy', 'I am busy', 'busy right now', "
            "'not interested', 'no thanks', 'call me later', "
            "'call back later'\n"
            "- Hindi: 'व्यस्त हूँ', 'बिज़ी हूँ', 'अभी बिज़ी हूँ', "
            "'अभी व्यस्त हूँ', 'नहीं धन्यवाद', 'दिलचस्पी नहीं है', "
            "'बाद में कॉल करें'\n"
            "- Tamil: 'பிஸியாக இருக்கிறேன்', 'விருப்பம் இல்லை'\n"
            "Call `record_refusal` on EVERY refusal — the system counts "
            "them and decides when to transition. Do not wait for a "
            "second refusal before calling the tool.\n"
            "\n"
            "- Never pretend to place orders, book appointments, or perform "
            "actions you cannot actually perform via your tools.\n\n"
        )

        return (
            f"{base_prompt}\n\n"
            f"YOUR IDENTITY:\n"
            f"- Your name is {self.persona_name}.\n"
            f"- You are a {self.persona_gender} voice assistant."
            f"{gender_agreement_hint}\n\n"
            f"{scope_boundaries}\n\n"
            f"TOOLS:\n"
            f"- You have a `hang_up_call` tool. There is only ONE valid "
            f"reason to invoke it: the caller has explicitly ended the "
            f"conversation.\n"
            f"- INVOKE this tool ONLY when ONE of these is literally true:\n"
            f"  * The caller clearly said goodbye ('bye', 'goodbye', "
            f"'अलविदा', 'பை', 'फिर मिलते हैं').\n"
            f"  * The caller explicitly asked to end the call ('end the "
            f"call', 'hang up', 'फोन रख दीजिए', 'cut the call').\n"
            f"  * The caller explicitly said they are not interested and "
            f"want to stop ('not interested', 'stop calling me', "
            f"'मुझे दिलचस्पी नहीं है').\n"
            f"  * The caller confirmed this is the wrong number.\n"
            f"- ABSOLUTELY DO NOT invoke this tool for:\n"
            f"  * An off-topic question. Redirect and CONTINUE.\n"
            f"  * A caller who is confused or says 'I don't know'.\n"
            f"  * A caller who goes silent or says 'hmm' / 'okay' / 'haan'.\n"
            f"  * A caller who asks you to explain or repeat.\n"
            f"  * A conversation where you feel the objective cannot be "
            f"met. Off-topic discussion is NOT a reason to end.\n"
            f"  * Your own judgement that the conversation seems over.\n"
            f"  * You have said the redirect phrase (this is a redirect, "
            f"NOT a goodbye).\n"
            f"- Before invoking, if the request is ambiguous, ASK: "
            f"'Would you like me to end the call now?' and WAIT for the "
            f"caller's reply. Do NOT invoke the tool on the same turn "
            f"that you asked this question.\n"
            f"- Do NOT say 'I'm ending the call' or 'goodbye' without "
            f"actually invoking the tool.\n\n"
            f"CODE-MIXING BEHAVIOR:\n"
            f"- The caller may speak in {self.name} mixed with English words "
            f"(Hinglish, Tanglish, etc.). This is natural and expected.\n"
            f"- Respond in the same style: use {self.name} as the primary "
            f"language, but keep English technical terms, brand names, and "
            f"common English words in English. For example, say 'meeting', "
            f"'project', 'website', 'email', 'update' in English rather than "
            f"translating them.\n"
            f"- Do NOT force the caller to use only one language. Match "
            f"their style.\n\n"
            f"CONVERSATION RULES:\n"
            f"- The greeting has already been spoken by the system. Do NOT "
            f"greet the caller again, ever. Never say 'नमस्ते' / 'Hello' / "
            f"'வணக்கம்' as the opening of your first response.\n"
            f"- If the caller says 'hello', 'hi', or 'हेलो' again, treat it "
            f"as a continuation, not a new conversation.\n"
            f"- Never repeat your introduction or greeting.\n"
            f"- If the caller seems to be testing you (repeating the same "
            f"word), respond naturally and move the conversation forward.\n\n"
            f"LANGUAGE INSTRUCTION:\n"
            f"{self.llm_prompt_suffix}\n"
            f"Respond ONLY in {self.name}. Do not switch languages mid-call."
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
            "नमस्ते! मैं IT-Webhut से {name} बोल रही हूँ। क्या अभी बात करने का सही समय है?"
        ),
        scope_redirect=(
            "क्षमा करें, मैं इस विषय में सहायता नहीं कर सकती। क्या हम अपनी बात पर वापस आ सकते हैं?"
        ),
        # Hindi
        farewell="धन्यवाद! आपका दिन शुभ हो।",
        farewell_wrong_number="क्षमा करें, गलत नंबर के लिए धन्यवाद।",
        consent_disclosure=(
            "यह कॉल AI सहायक द्वारा संचालित है और गुणवत्ता तथा सेवा "
            "उद्देश्यों के लिए रिकॉर्ड की जा सकती है। क्या आप जारी रखना चाहेंगे?"
        ),
        consent_decline_ack="समझ गई। आपका दिन शुभ हो।",
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
            "Hello! I'm {name} calling from IT-Webhut. Is this a good time to speak?"
        ),
        scope_redirect=(
            "I'm sorry, I can't help with that topic. Could we return to our conversation?"
        ),
        # English
        farewell="Thank you! Have a great day.",
        farewell_wrong_number="Sorry for the wrong number. Thank you.",
        consent_disclosure=(
            "This call is handled by an AI assistant and may be recorded "
            "for quality and service purposes. Would you like to continue?"
        ),
        consent_decline_ack="Understood. Have a great day.",
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
        scope_redirect=(
            "மன்னிக்கவும், இந்த விஷயத்தில் என்னால் உதவ முடியாது. நமது உரையாடலுக்குத் திரும்பலாமா?"
        ),
        # Tamil
        farewell="நன்றி! உங்கள் நாள் நன்றாக இருக்கட்டும்.",
        farewell_wrong_number="தவறான எண்ணுக்கு மன்னிக்கவும். நன்றி.",
        consent_disclosure=(
            "இந்த அழைப்பு ஒரு AI உதவியாளரால் நடத்தப்படுகிறது, தரம் மற்றும் "
            "சேவை நோக்கங்களுக்காக பதிவு செய்யப்படலாம். தொடர விரும்புகிறீர்களா?"
        ),
        consent_decline_ack="புரிந்தது. உங்கள் நாள் நன்றாக இருக்கட்டும்.",
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
            f"Unsupported language: {language_code}. Supported languages: {supported}"
        )
    return LANGUAGES[language_code]
