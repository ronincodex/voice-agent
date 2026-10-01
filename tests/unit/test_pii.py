"""PII detection and masking tests."""

from voice_agent.compliance.pii import detect_and_mask


def main() -> None:
    # Valid Aadhaar (Verhoeff-valid) -> XXXX-XXXX-0124
    text, counts = detect_and_mask("My Aadhaar is 2345 6789 0124.")
    assert "XXXX-XXXX-0124" in text, f"Aadhaar not masked: {text}"
    assert counts.get("aadhaar") == 1

    # Invalid Aadhaar (bad checksum) -> not masked
    text, counts = detect_and_mask("Order ID is 2345 6789 0123.")
    assert "2345 6789 0123" in text, f"Invalid Aadhaar was masked: {text}"
    assert "aadhaar" not in counts

    # PAN -> ABCDE1XXXX
    text, counts = detect_and_mask("My PAN is ABCDE1234F.")
    assert "ABCDE1XXXX" in text, f"PAN not masked: {text}"
    assert counts.get("pan") == 1

    # Phone -> [phone]
    text, counts = detect_and_mask("Call me at 9876543210.")
    assert "[phone]" in text
    assert counts.get("phone") == 1

    # Phone with +91 -> [phone]
    text, counts = detect_and_mask("Call me at +91 98765 43210.")
    assert "[phone]" in text

    # Email -> [email]
    text, counts = detect_and_mask("Email me at foo.bar@example.com.")
    assert "[email]" in text
    assert counts.get("email") == 1

    # Valid card (Luhn) -> [card]
    text, counts = detect_and_mask("My card is 4111 1111 1111 1111.")
    assert "[card]" in text
    assert counts.get("card") == 1

    # Invalid card -> not masked
    text, counts = detect_and_mask("Order 1234 5678 9012 3456.")
    assert "1234 5678 9012 3456" in text, f"Invalid card was masked: {text}"

    # Aadhar with digit-by-digit spacing -> XXXX-XXXX-0124
    text, counts = detect_and_mask("My Aadhaar is   2 3 4 5 6 7 8 9 0 1 2 4.")
    assert "XXXX-XXXX-0124" in text, f"Spaced Aadhar not masked: {text}"
    assert counts.get("aadhaar") == 1

    # Mixed identifiers
    text, counts = detect_and_mask(
        "Aadhaar 2345 6789 0124, PAN ABCDE1234F, phone 9876543210."
    )
    assert "XXXX-XXXX-0124" in text
    assert "ABCDE1XXXX" in text
    assert "[phone]" in text
    assert counts == {"aadhaar": 1, "pan": 1, "phone": 1}

    print("PII tests passed")


if __name__ == "__main__":
    main()
