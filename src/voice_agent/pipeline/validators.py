"""Deterministic guards for LLM-initiated tool calls.

The LLM cannot be trusted to reliably distinguish an off-topic question
from an explicit goodbye. These regex-based validators serve as the
final gate before a destructive tool call (hang_up_call) executes.

Design principle: the LLM proposes, the validator disposes. Even if the
model hallucinates intent, the call cannot end unless the caller's
literal words authorize it.
"""

import re
import unicodedata

# Zero-width characters that LLM/STT output sometimes injects. They break
# \b and \s matching because Python's re module treats them as neither
# word characters nor whitespace.
_ZW_CHARS = re.compile(r"[\u200b\u200c\u200d\ufeff]")


def _norm(text: str) -> str:
    """Normalize text before matching.

    Two issues found:
        1. Strip zero-width characters (ZWSP, ZWNJ, ZWJ, BOM).
        2. Apply NFC normalization so that Devanagri combining marks in
        non-canonical order (e.g. 'ह' + 'ं' + 'ा') match the canonical
         pattern form ('ह' + 'ा' + 'ं'). Without this, STT output for
         Hindi/Tamil words like "हां" fails to match literal regexes.
    """
    if not text:
        return text
    text = _ZW_CHARS.sub("", text)
    return unicodedata.normalize("NFC", text)


# Goodbye patterns - the caller explicitly wants to end the call.
# Matches across Hindi, English, Tamil, and code-mixed utterances.
GOODBYE_PATTERNS = re.compile(
    r"\b("
    r"bye|goodbye|good\s*bye|"
    r"गुड\s*बाय|गुडबाय|"
    r"अलविदा|फिर\s*मिलते\s*हैं|"
    r"பை|"
    r"end\s+(the\s+)?call|"
    r"hang\s+up|"
    r"cut\s+the\s+call|"
    r"फोन\s*रख|"
    r"कॉल\s*(काट|बंद|समाप्त(?:\s*कर)?)|"
    r"not\s+interested|"
    r"stop\s+calling|"
    r"मुझे\s*दिलचस्पी\s*नहीं"
    r")\b",
    re.IGNORECASE,
)

# =========================================================================
# Wrong-number patterns, the caller explicitly states this is not their
# number / they do not know the called party.
# =========================================================================
WRONG_NUMBER_PATTERNS = re.compile(
    r"\b("
    r"wrong\s+number|"
    r"गलत\s*नंबर|"
    r"not\s+the\s+(right|intended)\s+(number|person)|"
    r"don'?t\s+know\s+(you|this\s+person)|"
    r"never\s+heard\s+of|"
    r"मैं\s*इस\s*नंबर\s*को\s*नहीं\s*जानता|"
    r"मैं\s*इस\s*नंबर\s*को\s*नहीं\s*जानती"
    r")\b",
    re.IGNORECASE,
)

# New: token-based affirmative detector with a spoken-prefix tolerance.
_AFFIRMATIVE_TOKEN = re.compile(
    r"\b("
    r"yes|yeah|yep|yup|sure|okay|ok|fine|"
    r"absolutely|definitely|certainly|of\s+course|"
    r"haan|ha|han|हाँ|हां|हं|जी|ठीक|बिल्कुल|ज़रूर|जरूर|सही|"
    r"ஆம்|ஆமாம்|சரி|நிச்சயமாக|"
    r"please\s+do|go\s+ahead"
    r")\b",
    re.IGNORECASE,
)

# Regex-based: tolerates optional words between keywords (e.g. Hindi "अभी")
# and handles the many phrasings an LLM produces for the same question.
_CONFIRMATION_REGEX = re.compile(
    r"("
    r"would\s+you\s+like\s+(me\s+)?to\s+end"
    r"|do\s+you\s+want\s+(me\s+)?to\s+(end|hang\s*up)"
    r"|end\s+the\s+call"
    r"|hang\s+up\s+now"
    r"|call\s+end"  # English words in Hindi word order
    r"|call\s+ko\s+end"  # Hinglish
    r"|कॉल\s*(?:अभी\s*)?(?:समाप्त|बंद|काट)"
    r"|कॉल\s*(?:अभी\s*)?end"
    r"|फोन\s*रख"
    r"|अழைப்பை\s*முடி"
    r")",
    re.IGNORECASE,
)


def was_confirmation_question(assistant_text: str) -> bool:
    """True if the assistant just asked to confirm ending the call."""
    if not assistant_text:
        return False

    return bool(_CONFIRMATION_REGEX.search(_norm(assistant_text)))


def is_affirmative_reply(user_text: str) -> bool:
    """True if the caller's reply is a short affirmative (yes/हाँ/etc.).

    Robust to Indic combining-mark reordering (e.g. 'ह'+'ा'+'ँ' vs
    'ह'+'ँ'+'ा'). Falls back to base-character matching for scripts
    where NFC does not reorder combining marks.
    """
    if not user_text:
        return False
    normalized = _norm(user_text).strip()
    if len(normalized) > 50:
        return False

    # Path 1 — direct regex (works for Latin/English, and for Indic when
    # the codepoints match the pattern's canonical form).
    if _AFFIRMATIVE_TOKEN.search(normalized):
        return True

    # Path 2 — Indic base-character fallback. Strip all combining marks
    # (Mn/Mc/Me categories) then match against a small set of roots.
    # 'हा', 'हाँ', 'हां', 'हँ', 'हं' all reduce to base 'ह' after
    # combining-mark stripping.
    stripped_base = "".join(
        c for c in normalized if unicodedata.category(c) not in ("Mn", "Mc", "Me")
    ).strip()

    # Only consider very short replies — prevents false positives
    # from long sentences that happen to contain 'ह' as a syllable.
    if len(stripped_base) > 8:
        return False

    _INDIC_AFFIRMATIVE_BASES = (
        "ह",  # Hindi 'haa' (with any nasal variant)
        "ज",  # 'ji' → 'जी'
        "ठ",  # 'theek' → 'ठीक'
        "ब",  # 'bilkul' → 'बिल्कुल'
        "स",  # 'sahi' / 'sari' → सही / சரி
        "ஆ",  # Tamil 'aam' → ஆம்
        "ச",  # Tamil 'sari' → சரி
    )
    return any(base in stripped_base for base in _INDIC_AFFIRMATIVE_BASES)


def is_explicit_goodbye(
    user_text: str,
    last_assistant_text: str = "",
) -> bool:
    """Return True ONLY if the caller has explicitly authorized hangup."""
    if not user_text:
        return False

    user_norm = _norm(user_text)

    if GOODBYE_PATTERNS.search(user_norm):
        return True

    # Two-turn goodbye flow: assistant confirmed, user said "yes".
    if was_confirmation_question(last_assistant_text):
        stripped = user_norm.strip()
        # Length guard prevents false positives from long sentences that
        # happen to contain an affirmative word.
        if len(stripped) <= 50 and _AFFIRMATIVE_TOKEN.search(stripped):
            return True

    return False


def is_wrong_number(user_text: str) -> bool:
    """Return True ONLY if the caller has explicitly claimed wrong number."""
    if not user_text:
        return False
    return bool(WRONG_NUMBER_PATTERNS.search(_norm(user_text)))
