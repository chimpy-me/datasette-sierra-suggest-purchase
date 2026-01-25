"""
Identifier extraction and validation for suggest-a-bot.

Handles ISBN-10/13, ISSN, DOI, and URL parsing with validation.
Pure Python implementation - no external dependencies.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class ExtractedUrl:
    """A URL extracted from text with classification and embedded IDs."""

    url: str
    normalized_url: str
    domain: str
    classified_as: str  # "retailer", "publisher", "discovery", "library_catalog", "unknown"
    extracted_ids: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class ExtractedIdentifiers:
    """Collection of identifiers extracted from text."""

    isbn: list[str] = field(default_factory=list)  # Canonicalized ISBN-13s
    issn: list[str] = field(default_factory=list)  # Canonicalized ISSNs
    doi: list[str] = field(default_factory=list)  # Normalized DOIs
    urls: list[ExtractedUrl] = field(default_factory=list)

    # Quality signals
    valid_isbn_present: bool = False
    valid_issn_present: bool = False
    doi_present: bool = False
    url_present: bool = False


# =============================================================================
# ISBN Validation and Canonicalization
# =============================================================================

# ISBN patterns
ISBN_10_PATTERN = re.compile(r"\b(\d{9}[\dXx]|\d[\- ]?\d{3}[\- ]?\d{5}[\- ]?[\dXx])\b")
ISBN_13_PATTERN = re.compile(r"\b(97[89][\- ]?\d[\- ]?\d{3}[\- ]?\d{5}[\- ]?\d)\b")


def _strip_isbn(isbn: str) -> str:
    """Remove hyphens and spaces from an ISBN."""
    return isbn.replace("-", "").replace(" ", "").upper()


def validate_isbn10(isbn: str) -> bool:
    """
    Validate an ISBN-10 using modulo 11 check digit.

    The check digit is calculated such that the sum of all digits
    multiplied by their position (1-10) is divisible by 11.
    The last digit can be 'X' representing 10.
    """
    isbn = _strip_isbn(isbn)
    if len(isbn) != 10:
        return False

    total = 0
    for i, char in enumerate(isbn):
        if char == "X":
            if i != 9:
                return False
            value = 10
        elif char.isdigit():
            value = int(char)
        else:
            return False
        total += value * (10 - i)

    return total % 11 == 0


def validate_isbn13(isbn: str) -> bool:
    """
    Validate an ISBN-13 using modulo 10 check digit.

    Alternating weights of 1 and 3 are applied to digits 1-12.
    The check digit makes the weighted sum divisible by 10.
    """
    isbn = _strip_isbn(isbn)
    if len(isbn) != 13:
        return False
    if not isbn.isdigit():
        return False

    total = 0
    for i, char in enumerate(isbn):
        weight = 1 if i % 2 == 0 else 3
        total += int(char) * weight

    return total % 10 == 0


def isbn10_to_isbn13(isbn10: str) -> str | None:
    """
    Convert a valid ISBN-10 to ISBN-13.

    Prepends '978' and recalculates the check digit.
    Returns None if the input is not a valid ISBN-10.
    """
    isbn10 = _strip_isbn(isbn10)
    if len(isbn10) != 10 or not validate_isbn10(isbn10):
        return None

    # Take first 9 digits and prepend 978
    base = "978" + isbn10[:9]

    # Calculate new check digit
    total = 0
    for i, char in enumerate(base):
        weight = 1 if i % 2 == 0 else 3
        total += int(char) * weight

    check = (10 - (total % 10)) % 10
    return base + str(check)


def canonicalize_isbn(isbn: str) -> str | None:
    """
    Canonicalize an ISBN to ISBN-13 format (digits only).

    - Strips all formatting (hyphens, spaces)
    - Converts ISBN-10 to ISBN-13
    - Validates check digit
    - Returns None if invalid
    """
    isbn = _strip_isbn(isbn)

    if len(isbn) == 10:
        if validate_isbn10(isbn):
            return isbn10_to_isbn13(isbn)
        return None
    elif len(isbn) == 13:
        if validate_isbn13(isbn):
            return isbn
        return None
    else:
        return None


# =============================================================================
# ISSN Validation and Canonicalization
# =============================================================================

ISSN_PATTERN = re.compile(r"\b(\d{4}[\- ]?\d{3}[\dXx])\b")


def _strip_issn(issn: str) -> str:
    """Remove hyphen from an ISSN."""
    return issn.replace("-", "").replace(" ", "").upper()


def validate_issn(issn: str) -> bool:
    """
    Validate an ISSN using modulo 11 check digit.

    Weights 8,7,6,5,4,3,2 are applied to digits 1-7.
    The check digit makes the weighted sum (including check * 1) divisible by 11.
    """
    issn = _strip_issn(issn)
    if len(issn) != 8:
        return False

    total = 0
    for i, char in enumerate(issn[:7]):
        if not char.isdigit():
            return False
        total += int(char) * (8 - i)

    # Check digit
    check_char = issn[7]
    if check_char == "X":
        check = 10
    elif check_char.isdigit():
        check = int(check_char)
    else:
        return False

    total += check

    return total % 11 == 0


def canonicalize_issn(issn: str) -> str | None:
    """
    Canonicalize an ISSN (digits only, uppercase X if present).

    Returns None if invalid.
    """
    issn = _strip_issn(issn)
    if validate_issn(issn):
        return issn
    return None


# =============================================================================
# DOI Normalization
# =============================================================================

DOI_PATTERN = re.compile(
    r"\b(10\.\d{4,}/[^\s]+)",
    re.IGNORECASE,
)

DOI_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:dx\.)?doi\.org/(10\.\d{4,}/[^\s]+)",
    re.IGNORECASE,
)


def normalize_doi(doi: str) -> str:
    """
    Normalize a DOI to its canonical form.

    - Strips 'doi:', 'https://doi.org/' prefixes
    - Returns lowercase
    """
    doi = doi.strip()

    # Remove common prefixes
    if doi.lower().startswith("doi:"):
        doi = doi[4:].strip()
    if doi.lower().startswith("https://doi.org/"):
        doi = doi[16:]
    if doi.lower().startswith("http://doi.org/"):
        doi = doi[15:]
    if doi.lower().startswith("https://dx.doi.org/"):
        doi = doi[19:]
    if doi.lower().startswith("http://dx.doi.org/"):
        doi = doi[18:]

    return doi.lower()


# =============================================================================
# URL Classification and ID Extraction
# =============================================================================

# Domain classifications
RETAILER_DOMAINS = {
    "amazon.com",
    "amazon.co.uk",
    "amazon.ca",
    "amazon.de",
    "amazon.fr",
    "barnesandnoble.com",
    "bn.com",
    "bookshop.org",
    "betterworldbooks.com",
    "abebooks.com",
    "alibris.com",
    "thriftbooks.com",
    "powells.com",
    "indiebound.org",
    "bookdepository.com",
}

DISCOVERY_DOMAINS = {
    "goodreads.com",
    "librarything.com",
    "storygraph.com",
    "openlibrary.org",
    "worldcat.org",
    "oclc.org",
    "google.com",  # books.google.com
}

PUBLISHER_DOMAINS = {
    "penguinrandomhouse.com",
    "harpercollins.com",
    "simonandschuster.com",
    "hachettebookgroup.com",
    "macmillan.com",
    "scholastic.com",
    "oup.com",
    "cambridge.org",
    "springer.com",
    "wiley.com",
    "elsevier.com",
    "taylorandfrancis.com",
    "sagepub.com",
}

LIBRARY_CATALOG_PATTERNS = [
    r"\.lib\.",  # *.lib.* domains
    r"catalog\.",  # catalog.* subdomains
    r"/catalog/",  # /catalog/ in path
    r"opac",  # OPAC systems
    r"encore",  # III Encore
    r"bibliocommons",
]

# ASIN pattern (Amazon Standard Identification Number)
ASIN_PATTERN = re.compile(r"/(?:dp|product|gp/product)/([A-Z0-9]{10})", re.IGNORECASE)

# ISBN in URL path
URL_ISBN_PATTERN = re.compile(r"(?:/isbn[/=]|/isbn$|/)(\d{10}|\d{13})\b")

# Goodreads book ID
GOODREADS_ID_PATTERN = re.compile(r"/book/show/(\d+)")

# Google Books ID
GOOGLE_BOOKS_ID_PATTERN = re.compile(r"[?&]id=([A-Za-z0-9_-]+)")

# WorldCat OCLC number
WORLDCAT_OCLC_PATTERN = re.compile(r"/oclc/(\d+)")


def _get_base_domain(domain: str) -> str:
    """Extract base domain from full domain (e.g., 'www.amazon.com' -> 'amazon.com')."""
    parts = domain.lower().split(".")
    if len(parts) >= 2:
        # Handle co.uk, com.au etc.
        if parts[-2] in ("co", "com", "org", "net", "gov"):
            return ".".join(parts[-3:]) if len(parts) >= 3 else domain.lower()
        return ".".join(parts[-2:])
    return domain.lower()


def classify_url(url: str) -> str:
    """
    Classify a URL by its domain type.

    Returns: 'retailer', 'publisher', 'discovery', 'library_catalog', or 'unknown'
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        base_domain = _get_base_domain(domain)
        path = parsed.path.lower()

        # Check specific domain lists
        if base_domain in RETAILER_DOMAINS:
            return "retailer"
        if base_domain in PUBLISHER_DOMAINS:
            return "publisher"
        if base_domain in DISCOVERY_DOMAINS:
            # Special case for books.google.com
            if base_domain == "google.com" and not domain.startswith("books."):
                return "unknown"
            return "discovery"

        # Check library catalog patterns
        full_url = f"{domain}{path}"
        for pattern in LIBRARY_CATALOG_PATTERNS:
            if re.search(pattern, full_url, re.IGNORECASE):
                return "library_catalog"

        return "unknown"

    except Exception:
        return "unknown"


def extract_ids_from_url(url: str) -> dict[str, list[str]]:
    """
    Extract identifiers embedded in a URL.

    Returns dict with keys like 'isbn', 'asin', 'goodreads_id', 'google_books_id', 'oclc'
    """
    ids: dict[str, list[str]] = {}

    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        full_path = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path

        # Amazon ASIN (often ISBNs for books)
        if "amazon" in domain:
            match = ASIN_PATTERN.search(full_path)
            if match:
                asin = match.group(1)
                # Check if it's an ISBN-10
                if asin.isdigit() and len(asin) == 10:
                    if validate_isbn10(asin):
                        ids.setdefault("isbn", []).append(asin)
                    else:
                        ids.setdefault("asin", []).append(asin)
                else:
                    ids.setdefault("asin", []).append(asin)

        # ISBN in path
        for match in URL_ISBN_PATTERN.finditer(full_path):
            potential_isbn = match.group(1)
            canonical = canonicalize_isbn(potential_isbn)
            if canonical:
                ids.setdefault("isbn", []).append(canonical)

        # Goodreads book ID
        if "goodreads" in domain:
            match = GOODREADS_ID_PATTERN.search(full_path)
            if match:
                ids.setdefault("goodreads_id", []).append(match.group(1))

        # Google Books ID
        if "google" in domain and "books" in domain:
            match = GOOGLE_BOOKS_ID_PATTERN.search(full_path)
            if match:
                ids.setdefault("google_books_id", []).append(match.group(1))

        # WorldCat OCLC number
        if "worldcat" in domain or "oclc" in domain:
            match = WORLDCAT_OCLC_PATTERN.search(full_path)
            if match:
                ids.setdefault("oclc", []).append(match.group(1))

    except Exception:
        pass

    return ids


# =============================================================================
# URL Extraction
# =============================================================================

URL_PATTERN = re.compile(
    r"https?://[^\s<>\"\'\]\)]+",
    re.IGNORECASE,
)


def _normalize_url(url: str) -> str:
    """Normalize a URL for comparison."""
    # Remove trailing punctuation that's likely not part of URL
    url = url.rstrip(".,;:!?")
    return url


def extract_urls(text: str) -> list[ExtractedUrl]:
    """Extract and classify all URLs from text."""
    urls = []
    seen = set()

    for match in URL_PATTERN.finditer(text):
        url = match.group(0)
        normalized = _normalize_url(url)

        if normalized in seen:
            continue
        seen.add(normalized)

        try:
            parsed = urlparse(normalized)
            domain = parsed.netloc.lower()

            urls.append(
                ExtractedUrl(
                    url=url,
                    normalized_url=normalized,
                    domain=domain,
                    classified_as=classify_url(normalized),
                    extracted_ids=extract_ids_from_url(normalized),
                )
            )
        except Exception:
            continue

    return urls


# =============================================================================
# Main Entry Point
# =============================================================================


def extract_identifiers(text: str) -> ExtractedIdentifiers:
    """
    Extract all identifiers from text.

    This is the main entry point for identifier extraction.
    Returns an ExtractedIdentifiers object with:
    - isbn: list of canonicalized ISBN-13s
    - issn: list of canonicalized ISSNs
    - doi: list of normalized DOIs
    - urls: list of ExtractedUrl objects
    - Quality signals (valid_isbn_present, etc.)
    """
    result = ExtractedIdentifiers()
    seen_isbns: set[str] = set()
    seen_issns: set[str] = set()
    seen_dois: set[str] = set()

    # Extract ISBNs (check ISBN-13 first as they're more specific)
    for pattern in [ISBN_13_PATTERN, ISBN_10_PATTERN]:
        for match in pattern.finditer(text):
            raw = match.group(1)
            canonical = canonicalize_isbn(raw)
            if canonical and canonical not in seen_isbns:
                seen_isbns.add(canonical)
                result.isbn.append(canonical)
                result.valid_isbn_present = True

    # Extract ISSNs
    for match in ISSN_PATTERN.finditer(text):
        raw = match.group(1)
        canonical = canonicalize_issn(raw)
        if canonical and canonical not in seen_issns:
            seen_issns.add(canonical)
            result.issn.append(canonical)
            result.valid_issn_present = True

    # Extract DOIs (check URL form first)
    for pattern in [DOI_URL_PATTERN, DOI_PATTERN]:
        for match in pattern.finditer(text):
            raw = match.group(1) if pattern == DOI_URL_PATTERN else match.group(0)
            normalized = normalize_doi(raw)
            if normalized and normalized not in seen_dois:
                seen_dois.add(normalized)
                result.doi.append(normalized)
                result.doi_present = True

    # Extract URLs
    result.urls = extract_urls(text)
    result.url_present = len(result.urls) > 0

    # Add any ISBNs found in URLs that weren't in the text directly
    for extracted_url in result.urls:
        for isbn in extracted_url.extracted_ids.get("isbn", []):
            canonical = canonicalize_isbn(isbn)
            if canonical and canonical not in seen_isbns:
                seen_isbns.add(canonical)
                result.isbn.append(canonical)
                result.valid_isbn_present = True

    return result
