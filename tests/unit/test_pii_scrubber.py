"""Unit tests for PII scrubbing."""

from suggest_a_bot.openlibrary import scrub_pii


def test_scrub_pii_email():
    assert scrub_pii("contact me at test@example.com") == "contact me at [redacted]"


def test_scrub_pii_phone():
    assert scrub_pii("call 555-123-4567") == "call [redacted]"


def test_scrub_pii_long_number():
    assert scrub_pii("card 12345678901234") == "card [redacted]"


def test_scrub_pii_preserves_non_pii():
    assert scrub_pii("The Great Gatsby by Fitzgerald") == "The Great Gatsby by Fitzgerald"
