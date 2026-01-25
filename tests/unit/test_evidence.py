"""Tests for evidence packet builder."""

import json

import pytest

from suggest_a_bot.evidence import (
    SCHEMA_VERSION,
    EvidencePacket,
    EvidencePacketBuilder,
)


class TestEvidencePacketBuilder:
    """Test EvidencePacketBuilder."""

    def test_build_basic_packet(self):
        """Should build a basic evidence packet."""
        builder = EvidencePacketBuilder(omni_input="The Women by Kristin Hannah")
        packet = builder.build()

        assert packet.schema_version == SCHEMA_VERSION
        assert packet.inputs.omni_input == "The Women by Kristin Hannah"
        assert packet.created_utc is not None

    def test_build_with_format_preference(self):
        """Should include format preference in structured hints."""
        builder = EvidencePacketBuilder(
            omni_input="Some Book",
            format_preference="paperback",
        )
        packet = builder.build()

        assert packet.inputs.structured_hints.get("format_preference") == "paperback"
        assert "paperback" in packet.extracted.format_hints

    def test_build_with_patron_notes(self):
        """Should include patron notes as narrative context."""
        builder = EvidencePacketBuilder(
            omni_input="Some Book",
            patron_notes="Saw this on Goodreads",
        )
        packet = builder.build()

        assert packet.inputs.narrative_context == "Saw this on Goodreads"

    def test_extract_isbn(self):
        """Should extract ISBN from input."""
        builder = EvidencePacketBuilder(omni_input="ISBN: 978-0-306-40615-7")
        packet = builder.build()

        assert "9780306406157" in packet.identifiers.isbn
        assert packet.quality.signals.valid_isbn_present is True

    def test_extract_isbn_from_notes(self):
        """Should extract ISBN from patron notes too."""
        builder = EvidencePacketBuilder(
            omni_input="Looking for a book",
            patron_notes="ISBN 9780306406157",
        )
        packet = builder.build()

        assert "9780306406157" in packet.identifiers.isbn

    def test_extract_url(self):
        """Should extract and classify URLs."""
        builder = EvidencePacketBuilder(
            omni_input="https://www.amazon.com/dp/0306406152"
        )
        packet = builder.build()

        assert len(packet.identifiers.urls) == 1
        assert packet.identifiers.urls[0]["classified_as"] == "retailer"
        assert packet.quality.signals.url_present is True

    def test_detect_title_like_text(self):
        """Should detect title-like text."""
        builder = EvidencePacketBuilder(omni_input="The Women: A Novel")
        packet = builder.build()

        assert packet.quality.signals.title_like_text_present is True

    def test_detect_author_like_text(self):
        """Should detect author-like text."""
        builder = EvidencePacketBuilder(omni_input="by Kristin Hannah")
        packet = builder.build()

        assert packet.quality.signals.author_like_text_present is True

    def test_extract_title_guess(self):
        """Should extract title guess from input."""
        builder = EvidencePacketBuilder(omni_input='"The Women" by Kristin Hannah')
        packet = builder.build()

        assert packet.extracted.title_guess == "The Women"

    def test_extract_author_guess(self):
        """Should extract author guess from input."""
        builder = EvidencePacketBuilder(omni_input="The Women by Kristin Hannah")
        packet = builder.build()

        assert packet.extracted.author_guess == "Kristin Hannah"

    def test_extract_year_guess(self):
        """Should extract publication year guess."""
        builder = EvidencePacketBuilder(omni_input="Looking for a 2024 release")
        packet = builder.build()

        assert packet.extracted.year_guess == 2024

    def test_extract_format_hints(self):
        """Should extract format hints from text."""
        builder = EvidencePacketBuilder(omni_input="Need the audiobook version")
        packet = builder.build()

        assert "audiobook" in packet.extracted.format_hints

    def test_extract_language_hints(self):
        """Should extract language hints from text."""
        builder = EvidencePacketBuilder(omni_input="Spanish edition please")
        packet = builder.build()

        assert "es" in packet.extracted.language_hints

    def test_warning_for_unclear_input(self):
        """Should warn when input lacks ISBN and clear title."""
        builder = EvidencePacketBuilder(omni_input="abc")
        packet = builder.build()

        assert any("ISBN" in w for w in packet.quality.warnings)

    def test_error_for_too_short_input(self):
        """Should error when input is too short."""
        builder = EvidencePacketBuilder(omni_input="ab")
        packet = builder.build()

        assert any("too short" in e for e in packet.quality.errors)


class TestEvidencePacketSerialization:
    """Test EvidencePacket serialization."""

    def test_to_dict(self):
        """Should convert to dictionary."""
        builder = EvidencePacketBuilder(omni_input="Test Book")
        packet = builder.build()
        d = packet.to_dict()

        assert d["schema_version"] == SCHEMA_VERSION
        assert d["inputs"]["omni_input"] == "Test Book"
        assert "identifiers" in d
        assert "extracted" in d
        assert "quality" in d

    def test_to_json(self):
        """Should serialize to JSON."""
        builder = EvidencePacketBuilder(omni_input="Test Book")
        packet = builder.build()
        json_str = packet.to_json()

        # Should be valid JSON
        parsed = json.loads(json_str)
        assert parsed["schema_version"] == SCHEMA_VERSION

    def test_from_dict(self):
        """Should deserialize from dictionary."""
        builder = EvidencePacketBuilder(
            omni_input="Test Book",
            format_preference="paperback",
        )
        original = builder.build()
        d = original.to_dict()

        restored = EvidencePacket.from_dict(d)

        assert restored.schema_version == original.schema_version
        assert restored.inputs.omni_input == original.inputs.omni_input
        assert (
            restored.inputs.structured_hints.get("format_preference")
            == "paperback"
        )

    def test_from_json(self):
        """Should deserialize from JSON."""
        builder = EvidencePacketBuilder(omni_input="Test Book")
        original = builder.build()
        json_str = original.to_json()

        restored = EvidencePacket.from_json(json_str)

        assert restored.schema_version == original.schema_version
        assert restored.inputs.omni_input == original.inputs.omni_input

    def test_roundtrip_with_identifiers(self):
        """Should preserve identifiers through serialization roundtrip."""
        builder = EvidencePacketBuilder(
            omni_input="ISBN 978-0-306-40615-7 https://goodreads.com/book/123"
        )
        original = builder.build()
        json_str = original.to_json()
        restored = EvidencePacket.from_json(json_str)

        assert restored.identifiers.isbn == original.identifiers.isbn
        assert len(restored.identifiers.urls) == len(original.identifiers.urls)

    def test_roundtrip_with_quality_signals(self):
        """Should preserve quality signals through roundtrip."""
        builder = EvidencePacketBuilder(omni_input="ISBN 978-0-306-40615-7")
        original = builder.build()
        restored = EvidencePacket.from_json(original.to_json())

        assert (
            restored.quality.signals.valid_isbn_present
            == original.quality.signals.valid_isbn_present
        )


class TestEvidencePacketSchemaConformance:
    """Test that evidence packets conform to the JSON schema."""

    def test_required_fields_present(self):
        """Should include all required fields."""
        builder = EvidencePacketBuilder(omni_input="Test")
        packet = builder.build()
        d = packet.to_dict()

        # Required top-level fields
        assert "schema_version" in d
        assert "created_utc" in d
        assert "inputs" in d
        assert "identifiers" in d
        assert "extracted" in d
        assert "quality" in d

        # Required nested fields
        assert "omni_input" in d["inputs"]
        assert "signals" in d["quality"]

    def test_schema_version_format(self):
        """Schema version should match pattern ^1\\.0(\\.[0-9]+)?$."""
        builder = EvidencePacketBuilder(omni_input="Test")
        packet = builder.build()

        import re

        assert re.match(r"^1\.0(\.[0-9]+)?$", packet.schema_version)

    def test_created_utc_is_iso_format(self):
        """created_utc should be ISO 8601 format."""
        builder = EvidencePacketBuilder(omni_input="Test")
        packet = builder.build()

        from datetime import datetime

        # Should parse without error
        datetime.fromisoformat(packet.created_utc.replace("Z", "+00:00"))

    def test_url_objects_have_required_fields(self):
        """URL objects should have required 'url' field."""
        builder = EvidencePacketBuilder(omni_input="https://example.com/book")
        packet = builder.build()
        d = packet.to_dict()

        for url_obj in d["identifiers"].get("urls", []):
            assert "url" in url_obj

    def test_signals_are_booleans(self):
        """Quality signals should be booleans."""
        builder = EvidencePacketBuilder(omni_input="Test Book")
        packet = builder.build()
        d = packet.to_dict()

        signals = d["quality"]["signals"]
        for key, value in signals.items():
            assert isinstance(value, bool), f"{key} should be bool, got {type(value)}"


class TestEdgeCases:
    """Test edge cases and unusual inputs."""

    def test_empty_string_handling(self):
        """Should handle empty input gracefully."""
        builder = EvidencePacketBuilder(omni_input="")
        packet = builder.build()

        assert packet.inputs.omni_input == ""
        assert len(packet.quality.errors) > 0

    def test_unicode_handling(self):
        """Should handle unicode characters."""
        builder = EvidencePacketBuilder(omni_input="日本語の本 by 著者名")
        packet = builder.build()

        assert "日本語の本" in packet.inputs.omni_input

    def test_very_long_input(self):
        """Should handle very long input."""
        long_text = "Looking for a book " * 100
        builder = EvidencePacketBuilder(omni_input=long_text)
        packet = builder.build()

        assert len(packet.inputs.omni_input) == len(long_text)

    def test_multiple_isbns(self):
        """Should extract multiple ISBNs."""
        builder = EvidencePacketBuilder(
            omni_input="Either 978-0-306-40615-7 or 978-1-234-56789-7"
        )
        packet = builder.build()

        assert len(packet.identifiers.isbn) == 2

    def test_malformed_url(self):
        """Should handle malformed URLs gracefully."""
        builder = EvidencePacketBuilder(omni_input="Check out http://[invalid url")
        packet = builder.build()

        # Should not crash, may or may not extract URL
        assert packet.inputs.omni_input is not None

    def test_special_characters_in_title(self):
        """Should handle special characters in title."""
        builder = EvidencePacketBuilder(
            omni_input='"Harry Potter & the Philosopher\'s Stone"'
        )
        packet = builder.build()

        assert "Harry Potter" in (packet.extracted.title_guess or "")
