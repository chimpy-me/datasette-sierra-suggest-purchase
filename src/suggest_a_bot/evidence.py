"""
Evidence packet builder for suggest-a-bot.

Creates structured evidence packets from patron input following
the schema defined in llore/09_bot-artifacts-json-schemas.md.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from .identifiers import ExtractedUrl, extract_identifiers

SCHEMA_VERSION = "1.0.0"


@dataclass
class EvidenceInputs:
    """Input data captured from patron submission."""

    omni_input: str
    narrative_context: str | None = None
    structured_hints: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceIdentifiers:
    """Structured identifiers extracted from input."""

    isbn: list[str] = field(default_factory=list)
    issn: list[str] = field(default_factory=list)
    doi: list[str] = field(default_factory=list)
    wikidata_qid: list[str] = field(default_factory=list)
    urls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EvidenceExtracted:
    """Best-effort extracted metadata from input."""

    title_guess: str | None = None
    author_guess: str | None = None
    series_guess: str | None = None
    volume_guess: str | None = None
    publisher_guess: str | None = None
    year_guess: int | None = None
    edition_guess: str | None = None
    format_hints: list[str] = field(default_factory=list)
    language_hints: list[str] = field(default_factory=list)
    llm_extraction: dict[str, Any] | None = None


@dataclass
class EvidenceQualitySignals:
    """Quality signals about the input."""

    valid_isbn_present: bool = False
    valid_issn_present: bool = False
    doi_present: bool = False
    url_present: bool = False
    title_like_text_present: bool = False
    author_like_text_present: bool = False


@dataclass
class EvidenceQuality:
    """Quality assessment of the input."""

    signals: EvidenceQualitySignals = field(default_factory=EvidenceQualitySignals)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class EvidencePacket:
    """
    Structured evidence packet for a purchase request.

    Schema version: 1.0.0
    See llore/09_bot-artifacts-json-schemas.md for full schema.
    """

    schema_version: str
    created_utc: str
    inputs: EvidenceInputs
    identifiers: EvidenceIdentifiers
    extracted: EvidenceExtracted
    quality: EvidenceQuality

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return _dataclass_to_dict(self)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=None)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidencePacket":
        """Create from dictionary."""
        return cls(
            schema_version=data["schema_version"],
            created_utc=data["created_utc"],
            inputs=EvidenceInputs(
                omni_input=data["inputs"]["omni_input"],
                narrative_context=data["inputs"].get("narrative_context"),
                structured_hints=data["inputs"].get("structured_hints", {}),
            ),
            identifiers=EvidenceIdentifiers(
                isbn=data["identifiers"].get("isbn", []),
                issn=data["identifiers"].get("issn", []),
                doi=data["identifiers"].get("doi", []),
                wikidata_qid=data["identifiers"].get("wikidata_qid", []),
                urls=data["identifiers"].get("urls", []),
            ),
            extracted=EvidenceExtracted(
                title_guess=data["extracted"].get("title_guess"),
                author_guess=data["extracted"].get("author_guess"),
                series_guess=data["extracted"].get("series_guess"),
                volume_guess=data["extracted"].get("volume_guess"),
                publisher_guess=data["extracted"].get("publisher_guess"),
                year_guess=data["extracted"].get("year_guess"),
                edition_guess=data["extracted"].get("edition_guess"),
                format_hints=data["extracted"].get("format_hints", []),
                language_hints=data["extracted"].get("language_hints", []),
                llm_extraction=data["extracted"].get("llm_extraction"),
            ),
            quality=EvidenceQuality(
                signals=EvidenceQualitySignals(
                    valid_isbn_present=data["quality"]["signals"].get("valid_isbn_present", False),
                    valid_issn_present=data["quality"]["signals"].get("valid_issn_present", False),
                    doi_present=data["quality"]["signals"].get("doi_present", False),
                    url_present=data["quality"]["signals"].get("url_present", False),
                    title_like_text_present=data["quality"]["signals"].get(
                        "title_like_text_present", False
                    ),
                    author_like_text_present=data["quality"]["signals"].get(
                        "author_like_text_present", False
                    ),
                ),
                warnings=data["quality"].get("warnings", []),
                errors=data["quality"].get("errors", []),
            ),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "EvidencePacket":
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))


def _dataclass_to_dict(obj: Any) -> Any:
    """Recursively convert dataclass to dict, omitting None values in nested objects."""
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for key, value in asdict(obj).items():
            # Always include required fields and non-None values
            if value is not None:
                result[key] = _dataclass_to_dict(value)
            elif key in ("omni_input", "schema_version", "created_utc", "signals"):
                result[key] = value
        return result
    elif isinstance(obj, list):
        return [_dataclass_to_dict(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: _dataclass_to_dict(v) for k, v in obj.items() if v is not None}
    return obj


# =============================================================================
# Heuristic text analysis for title/author detection
# =============================================================================

# Common author indicators
# Pattern captures: FirstName LastName, with optional middle initial (F. or F)
AUTHOR_PATTERNS = [
    r"\bby\s+([A-Z][a-z]+(?:\s+[A-Z]\.?\s+)?[A-Z][a-z]+(?:\s+(?:Jr|Sr|III|IV)\.?)?)",
    r"\bby\s+([A-Z][a-z]+\s+[A-Z][a-z]+)",  # Simple "FirstName LastName"
    r"[-\u2013\u2014]\s*([A-Z][a-z]+\s+[A-Z][a-z]+)",
    r"\bauthor[:\s]+([A-Z][a-z]+\s+[A-Z][a-z]+)",
]

# Title-like patterns (capitalized words, quoted text)
TITLE_PATTERNS = [
    r'^"([^"]+)"',  # Quoted at start
    r"^'([^']+)'",  # Single quoted at start
    r"^([A-Z][^,\n]{2,50})",  # Capitalized phrase at start (up to 50 chars)
]

# Format keywords
FORMAT_KEYWORDS = {
    "hardcover": "hardcover",
    "hardback": "hardcover",
    "paperback": "paperback",
    "softcover": "paperback",
    "ebook": "ebook",
    "e-book": "ebook",
    "kindle": "ebook",
    "audiobook": "audiobook",
    "audio book": "audiobook",
    "audio": "audiobook",
    "cd": "audiobook",
    "mp3": "audiobook",
    "large print": "large_print",
    "largeprint": "large_print",
    "dvd": "dvd",
    "blu-ray": "bluray",
    "bluray": "bluray",
}

# Language keywords
LANGUAGE_KEYWORDS = {
    "english": "en",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "portuguese": "pt",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
    "russian": "ru",
    "arabic": "ar",
    "hebrew": "he",
}

# Year pattern (4 digits that look like years)
YEAR_PATTERN = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")


def _looks_like_title(text: str) -> bool:
    """Check if text looks like it contains a title."""
    # Strip identifiers and URLs first
    stripped = re.sub(r"https?://\S+", "", text)
    stripped = re.sub(r"\b\d{10,13}\b", "", stripped)
    stripped = re.sub(r"\b\d{4}-\d{4}\b", "", stripped)

    # Check for quoted text
    if re.search(r'["\'][^"\']{3,}["\']', stripped):
        return True

    # Check for capitalized words (at least 2 words starting with caps)
    words = stripped.split()
    cap_words = [w for w in words if w and w[0].isupper() and len(w) > 1]
    return len(cap_words) >= 2


def _looks_like_author(text: str) -> bool:
    """Check if text looks like it contains an author name."""
    for pattern in AUTHOR_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    # Check for "by" keyword
    return bool(re.search(r"\bby\s+\w", text, re.IGNORECASE))


def _extract_author_guess(text: str) -> str | None:
    """Try to extract author name from text."""
    for pattern in AUTHOR_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None


def _extract_title_guess(text: str) -> str | None:
    """Try to extract title from text."""
    # First try quoted text
    for pattern in [r'"([^"]{3,})"', r"'([^']{3,})'"]:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()

    # Otherwise, try to find a title-like phrase at the start
    # Strip author patterns first
    cleaned = text
    for pattern in AUTHOR_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bby\s+\w.*$", "", cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = cleaned.strip()

    if cleaned:
        # Take first line/sentence
        first_part = re.split(r"[.\n]", cleaned)[0].strip()
        if len(first_part) >= 3:
            return first_part[:100]  # Limit length

    return None


def _extract_year_guess(text: str) -> int | None:
    """Try to extract publication year from text."""
    matches = YEAR_PATTERN.findall(text)
    if matches:
        # Return the most recent year found
        years = [int(y) for y in matches]
        return max(years)
    return None


def _extract_format_hints(text: str) -> list[str]:
    """Extract format hints from text."""
    hints = []
    text_lower = text.lower()
    seen = set()

    for keyword, normalized in FORMAT_KEYWORDS.items():
        if keyword in text_lower and normalized not in seen:
            hints.append(normalized)
            seen.add(normalized)

    return hints


def _extract_language_hints(text: str) -> list[str]:
    """Extract language hints from text."""
    hints = []
    text_lower = text.lower()
    seen = set()

    for keyword, code in LANGUAGE_KEYWORDS.items():
        if keyword in text_lower and code not in seen:
            hints.append(code)
            seen.add(code)

    return hints


def _url_to_dict(url: ExtractedUrl) -> dict[str, Any]:
    """Convert ExtractedUrl to dictionary for evidence packet."""
    result: dict[str, Any] = {
        "url": url.url,
        "domain": url.domain,
        "classified_as": url.classified_as,
    }
    if url.normalized_url != url.url:
        result["normalized_url"] = url.normalized_url
    if url.extracted_ids:
        result["extracted_ids"] = url.extracted_ids
    return result


class EvidencePacketBuilder:
    """
    Builder for creating evidence packets from patron input.

    Usage:
        builder = EvidencePacketBuilder(
            omni_input="The Women by Kristin Hannah",
            format_preference="paperback",
            patron_notes="Saw this on Goodreads"
        )
        packet = builder.build()
    """

    def __init__(
        self,
        omni_input: str,
        format_preference: str | None = None,
        patron_notes: str | None = None,
    ):
        self.omni_input = omni_input
        self.format_preference = format_preference
        self.patron_notes = patron_notes
        self._warnings: list[str] = []
        self._errors: list[str] = []

    def build(self) -> EvidencePacket:
        """Build the evidence packet."""
        # Extract identifiers from all input sources
        combined_text = self.omni_input
        if self.patron_notes:
            combined_text += " " + self.patron_notes

        identifiers = extract_identifiers(combined_text)

        # Build structured hints
        structured_hints: dict[str, Any] = {}
        if self.format_preference:
            structured_hints["format_preference"] = self.format_preference

        # Build quality signals
        signals = EvidenceQualitySignals(
            valid_isbn_present=identifiers.valid_isbn_present,
            valid_issn_present=identifiers.valid_issn_present,
            doi_present=identifiers.doi_present,
            url_present=identifiers.url_present,
            title_like_text_present=_looks_like_title(self.omni_input),
            author_like_text_present=_looks_like_author(self.omni_input),
        )

        # Extract metadata guesses
        title_guess = _extract_title_guess(self.omni_input)
        author_guess = _extract_author_guess(self.omni_input)
        year_guess = _extract_year_guess(combined_text)
        format_hints = _extract_format_hints(combined_text)
        language_hints = _extract_language_hints(combined_text)

        # Add format preference to hints if not already present
        if self.format_preference:
            normalized_format = FORMAT_KEYWORDS.get(
                self.format_preference.lower(), self.format_preference.lower()
            )
            if normalized_format not in format_hints:
                format_hints.insert(0, normalized_format)

        # Generate warnings
        if not identifiers.isbn and not signals.title_like_text_present:
            self._warnings.append(
                "No ISBN found and input does not appear to contain a clear title"
            )

        if len(self.omni_input.strip()) < 3:
            self._errors.append("Input too short to process")

        return EvidencePacket(
            schema_version=SCHEMA_VERSION,
            created_utc=datetime.now(UTC).isoformat(),
            inputs=EvidenceInputs(
                omni_input=self.omni_input,
                narrative_context=self.patron_notes,
                structured_hints=structured_hints if structured_hints else {},
            ),
            identifiers=EvidenceIdentifiers(
                isbn=identifiers.isbn,
                issn=identifiers.issn,
                doi=identifiers.doi,
                urls=[_url_to_dict(u) for u in identifiers.urls],
            ),
            extracted=EvidenceExtracted(
                title_guess=title_guess,
                author_guess=author_guess,
                year_guess=year_guess,
                format_hints=format_hints if format_hints else [],
                language_hints=language_hints if language_hints else [],
            ),
            quality=EvidenceQuality(
                signals=signals,
                warnings=self._warnings,
                errors=self._errors,
            ),
        )
