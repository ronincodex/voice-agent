"""PII detection and masking for Indian identifiers.

Masks Aadhaar, PAN, Indian phone numbers, emails, and credit cards.
Aadhaar is verified with the Verhoeff checksum; cards with Luhn.
Phone and email use regex only.

Mask formats follow Indian standards:
- Aadhaar: XXXX-XXXX-1234 (last 4 visible, per UIDAI/RBI)
- PAN: ABCDE1XXXX (first 6 visible, per RBI KYC Directions)
- Phone, email, card: [phone], [email], [card]

Source:
    https://uidai.gov.in/en/aadhaar-online-services (masked Aadhaar)
    https://www.kychub.com/blog/aadhaar-masking-rbi-regulated-entities
"""

import re
from enum import StrEnum


class PIIType(StrEnum):
    AADHAAR = "aadhaar"
    PAN = "pan"
    PHONE = "phone"
    EMAIL = "email"
    CARD = "card"


_AADHAAR_RE = re.compile(r"\b[2-9](?:[\s-]?\d){11}\b")
_PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
_PHONE_RE = re.compile(r"(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")

# Verhoeff tables (dihedral D5 group)
_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def _verhoeff_valid(digits: str) -> bool:
    """Validate a 12-digit Aadhaar using the Verhoeff checksum."""
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


def _luhn_valid(digits: str) -> bool:
    """Validate a card number using the Luhn mod-10 checksum."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def detect_and_mask(text: str) -> tuple[str, dict[str, int]]:
    """Mask Indian PII in text.

    Returns (masked_text, counts_by_type).
    """
    counts: dict[str, int] = {}

    def _bump(t: PIIType) -> None:
        counts[t.value] = counts.get(t.value, 0) + 1

    # Aadhaar (Verhoeff validated) - mask first 8, keep last 4
    def _mask_aadhaar(match: re.Match[str]) -> str:
        raw = match.group(0)
        digits = re.sub(r"[\s-]", "", raw)
        if len(digits) == 12 and _verhoeff_valid(digits):
            _bump(PIIType.AADHAAR)
            return f"XXXX-XXXX-{digits[-4:]}"
        return raw

    text = _AADHAAR_RE.sub(_mask_aadhaar, text)

    # PAN - mask last 4, keep first 6
    def _mask_pan(match: re.Match[str]) -> str:
        pan = match.group(0)
        _bump(PIIType.PAN)
        return f"{pan[:6]}XXXX"

    text = _PAN_RE.sub(_mask_pan, text)

    # Card (Luhn validated)
    def _mask_card(match: re.Match[str]) -> str:
        digits = re.sub(r"[ -]", "", match.group(0))
        if _luhn_valid(digits):
            _bump(PIIType.CARD)
            return "[card]"
        return match.group(0)

    text = _CARD_RE.sub(_mask_card, text)

    # Email
    def _mask_email(match: re.Match[str]) -> str:
        _bump(PIIType.EMAIL)
        return "[email]"

    text = _EMAIL_RE.sub(_mask_email, text)

    # Phone (last, after email)
    def _mask_phone(match: re.Match[str]) -> str:
        _bump(PIIType.PHONE)
        return "[phone]"

    text = _PHONE_RE.sub(_mask_phone, text)

    return text, counts
