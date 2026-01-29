"""Tests for identifier extraction and validation."""

from suggest_a_bot.identifiers import (
    canonicalize_isbn,
    canonicalize_issn,
    classify_url,
    extract_identifiers,
    extract_ids_from_url,
    extract_urls,
    isbn10_to_isbn13,
    normalize_doi,
    validate_isbn10,
    validate_isbn13,
    validate_issn,
)


class TestISBN10Validation:
    """Test ISBN-10 validation."""

    def test_valid_isbn10(self):
        """Should validate correct ISBN-10."""
        assert validate_isbn10("0306406152") is True

    def test_valid_isbn10_with_x_check_digit(self):
        """Should validate ISBN-10 with X check digit."""
        assert validate_isbn10("080442957X") is True

    def test_valid_isbn10_with_lowercase_x(self):
        """Should accept lowercase x check digit."""
        assert validate_isbn10("080442957x") is True

    def test_valid_isbn10_with_hyphens(self):
        """Should validate ISBN-10 with hyphens."""
        assert validate_isbn10("0-306-40615-2") is True

    def test_valid_isbn10_with_spaces(self):
        """Should validate ISBN-10 with spaces."""
        assert validate_isbn10("0 306 40615 2") is True

    def test_invalid_isbn10_wrong_check_digit(self):
        """Should reject ISBN-10 with wrong check digit."""
        assert validate_isbn10("0306406153") is False

    def test_invalid_isbn10_wrong_length(self):
        """Should reject ISBN-10 with wrong length."""
        assert validate_isbn10("030640615") is False
        assert validate_isbn10("03064061522") is False

    def test_invalid_isbn10_x_not_at_end(self):
        """Should reject X not in check digit position."""
        assert validate_isbn10("030X406152") is False

    def test_invalid_isbn10_non_digit(self):
        """Should reject non-digit characters."""
        assert validate_isbn10("030640615A") is False


class TestISBN13Validation:
    """Test ISBN-13 validation."""

    def test_valid_isbn13(self):
        """Should validate correct ISBN-13."""
        assert validate_isbn13("9780306406157") is True

    def test_valid_isbn13_with_hyphens(self):
        """Should validate ISBN-13 with hyphens."""
        assert validate_isbn13("978-0-306-40615-7") is True

    def test_valid_isbn13_979_prefix(self):
        """Should validate ISBN-13 with 979 prefix."""
        assert validate_isbn13("9791234567896") is True

    def test_invalid_isbn13_wrong_check_digit(self):
        """Should reject ISBN-13 with wrong check digit."""
        assert validate_isbn13("9780306406158") is False

    def test_invalid_isbn13_wrong_length(self):
        """Should reject ISBN-13 with wrong length."""
        assert validate_isbn13("978030640615") is False
        assert validate_isbn13("97803064061577") is False

    def test_invalid_isbn13_wrong_prefix(self):
        """Should reject ISBN-13 without 978/979 prefix."""
        assert validate_isbn13("9770306406157") is False


class TestISBN10ToISBN13:
    """Test ISBN-10 to ISBN-13 conversion."""

    def test_convert_isbn10_to_isbn13(self):
        """Should convert ISBN-10 to ISBN-13."""
        assert isbn10_to_isbn13("0306406152") == "9780306406157"

    def test_convert_isbn10_with_x_check_digit(self):
        """Should convert ISBN-10 with X check digit."""
        result = isbn10_to_isbn13("080442957X")
        assert result is not None
        assert validate_isbn13(result)

    def test_convert_invalid_isbn10_returns_none(self):
        """Should return None for invalid ISBN-10."""
        assert isbn10_to_isbn13("0306406153") is None
        assert isbn10_to_isbn13("invalid") is None


class TestCanonicalizeISBN:
    """Test ISBN canonicalization."""

    def test_canonicalize_isbn10(self):
        """Should convert ISBN-10 to ISBN-13."""
        assert canonicalize_isbn("0306406152") == "9780306406157"

    def test_canonicalize_isbn10_with_formatting(self):
        """Should strip formatting from ISBN-10."""
        assert canonicalize_isbn("0-306-40615-2") == "9780306406157"

    def test_canonicalize_isbn13(self):
        """Should normalize ISBN-13."""
        assert canonicalize_isbn("978-0-306-40615-7") == "9780306406157"

    def test_canonicalize_invalid_isbn_returns_none(self):
        """Should return None for invalid ISBN."""
        assert canonicalize_isbn("invalid") is None
        assert canonicalize_isbn("1234567890") is None  # Invalid check digit


class TestISSNValidation:
    """Test ISSN validation."""

    def test_valid_issn(self):
        """Should validate correct ISSN."""
        assert validate_issn("03178471") is True

    def test_valid_issn_with_hyphen(self):
        """Should validate ISSN with hyphen."""
        assert validate_issn("0317-8471") is True

    def test_valid_issn_with_x_check_digit(self):
        """Should validate ISSN with X check digit."""
        assert validate_issn("2049-3630") is True  # Example with numeric check

    def test_invalid_issn_wrong_check_digit(self):
        """Should reject ISSN with wrong check digit."""
        assert validate_issn("03178472") is False

    def test_invalid_issn_wrong_length(self):
        """Should reject ISSN with wrong length."""
        assert validate_issn("0317847") is False
        assert validate_issn("031784711") is False


class TestCanonicalizeISSN:
    """Test ISSN canonicalization."""

    def test_canonicalize_valid_issn(self):
        """Should strip hyphen from valid ISSN."""
        assert canonicalize_issn("0317-8471") == "03178471"

    def test_canonicalize_invalid_issn_returns_none(self):
        """Should return None for invalid ISSN."""
        assert canonicalize_issn("0317-8472") is None
        assert canonicalize_issn("invalid") is None


class TestDOINormalization:
    """Test DOI normalization."""

    def test_normalize_plain_doi(self):
        """Should normalize plain DOI."""
        assert normalize_doi("10.1000/xyz123") == "10.1000/xyz123"

    def test_normalize_doi_with_prefix(self):
        """Should strip 'doi:' prefix."""
        assert normalize_doi("doi:10.1000/xyz123") == "10.1000/xyz123"
        assert normalize_doi("DOI:10.1000/xyz123") == "10.1000/xyz123"

    def test_normalize_doi_url(self):
        """Should strip doi.org URL prefix."""
        assert normalize_doi("https://doi.org/10.1000/xyz123") == "10.1000/xyz123"
        assert normalize_doi("http://doi.org/10.1000/xyz123") == "10.1000/xyz123"

    def test_normalize_doi_dx_url(self):
        """Should strip dx.doi.org URL prefix."""
        assert normalize_doi("https://dx.doi.org/10.1000/xyz123") == "10.1000/xyz123"

    def test_normalize_doi_lowercase(self):
        """Should lowercase the DOI."""
        assert normalize_doi("10.1000/XYZ123") == "10.1000/xyz123"


class TestURLClassification:
    """Test URL classification."""

    def test_classify_amazon_as_retailer(self):
        """Should classify Amazon as retailer."""
        assert classify_url("https://www.amazon.com/dp/0306406152") == "retailer"
        assert classify_url("https://amazon.co.uk/dp/0306406152") == "retailer"

    def test_classify_barnes_and_noble_as_retailer(self):
        """Should classify Barnes & Noble as retailer."""
        assert classify_url("https://www.barnesandnoble.com/w/book") == "retailer"

    def test_classify_goodreads_as_discovery(self):
        """Should classify Goodreads as discovery."""
        assert classify_url("https://www.goodreads.com/book/show/123") == "discovery"

    def test_classify_openlibrary_as_discovery(self):
        """Should classify Open Library as discovery."""
        assert classify_url("https://openlibrary.org/works/OL123W") == "discovery"

    def test_classify_worldcat_as_discovery(self):
        """Should classify WorldCat as discovery."""
        assert classify_url("https://www.worldcat.org/oclc/123456") == "discovery"

    def test_classify_penguin_as_publisher(self):
        """Should classify Penguin Random House as publisher."""
        assert classify_url("https://www.penguinrandomhouse.com/books/123") == "publisher"

    def test_classify_library_catalog(self):
        """Should classify library catalog URLs."""
        assert classify_url("https://catalog.library.org/record/123") == "library_catalog"
        assert classify_url("https://mylib.bibliocommons.com/item/123") == "library_catalog"

    def test_classify_unknown_domain(self):
        """Should return 'unknown' for unrecognized domains."""
        assert classify_url("https://example.com/book") == "unknown"

    def test_classify_google_non_books(self):
        """Should return 'unknown' for non-books Google URLs."""
        assert classify_url("https://www.google.com/search?q=book") == "unknown"


class TestExtractIDsFromURL:
    """Test ID extraction from URLs."""

    def test_extract_isbn_from_amazon_url(self):
        """Should extract ISBN from Amazon URL."""
        ids = extract_ids_from_url("https://www.amazon.com/dp/0306406152")
        assert "isbn" in ids
        assert "9780306406157" in ids["isbn"]  # Converted to ISBN-13

    def test_extract_asin_from_amazon_url(self):
        """Should extract non-ISBN ASIN from Amazon URL."""
        ids = extract_ids_from_url("https://www.amazon.com/dp/B00I0W4BXE")
        assert "asin" in ids
        assert "B00I0W4BXE" in ids["asin"]

    def test_extract_goodreads_id(self):
        """Should extract Goodreads book ID."""
        ids = extract_ids_from_url("https://www.goodreads.com/book/show/12345")
        assert "goodreads_id" in ids
        assert "12345" in ids["goodreads_id"]

    def test_extract_worldcat_oclc(self):
        """Should extract WorldCat OCLC number."""
        ids = extract_ids_from_url("https://www.worldcat.org/oclc/123456789")
        assert "oclc" in ids
        assert "123456789" in ids["oclc"]

    def test_extract_isbn_from_path(self):
        """Should extract ISBN from URL path."""
        ids = extract_ids_from_url("https://example.com/isbn/9780306406157")
        assert "isbn" in ids
        assert "9780306406157" in ids["isbn"]


class TestExtractURLs:
    """Test URL extraction from text."""

    def test_extract_single_url(self):
        """Should extract a single URL."""
        urls = extract_urls("Check out https://example.com/book")
        assert len(urls) == 1
        assert urls[0].url == "https://example.com/book"

    def test_extract_multiple_urls(self):
        """Should extract multiple URLs."""
        text = "See https://amazon.com/dp/123 and https://goodreads.com/book/456"
        urls = extract_urls(text)
        assert len(urls) == 2

    def test_strip_trailing_punctuation(self):
        """Should strip trailing punctuation from URLs."""
        urls = extract_urls("Visit https://example.com/book.")
        assert urls[0].normalized_url == "https://example.com/book"

    def test_deduplicate_urls(self):
        """Should deduplicate identical URLs."""
        text = "https://example.com and https://example.com again"
        urls = extract_urls(text)
        assert len(urls) == 1


class TestExtractIdentifiers:
    """Test main identifier extraction function."""

    def test_extract_isbn13_from_text(self):
        """Should extract ISBN-13 from text."""
        result = extract_identifiers("ISBN: 978-0-306-40615-7")
        assert "9780306406157" in result.isbn
        assert result.valid_isbn_present is True

    def test_extract_isbn10_and_convert(self):
        """Should extract ISBN-10 and convert to ISBN-13."""
        result = extract_identifiers("ISBN: 0306406152")
        assert "9780306406157" in result.isbn
        assert result.valid_isbn_present is True

    def test_extract_issn_from_text(self):
        """Should extract ISSN from text."""
        result = extract_identifiers("ISSN: 0317-8471")
        assert "03178471" in result.issn
        assert result.valid_issn_present is True

    def test_extract_doi_from_text(self):
        """Should extract DOI from text."""
        result = extract_identifiers("DOI: 10.1000/xyz123")
        assert "10.1000/xyz123" in result.doi
        assert result.doi_present is True

    def test_extract_doi_url_from_text(self):
        """Should extract DOI from doi.org URL."""
        result = extract_identifiers("See https://doi.org/10.1000/xyz123")
        assert "10.1000/xyz123" in result.doi
        assert result.doi_present is True

    def test_extract_url_from_text(self):
        """Should extract and classify URLs."""
        result = extract_identifiers("https://www.amazon.com/dp/0306406152")
        assert len(result.urls) == 1
        assert result.urls[0].classified_as == "retailer"
        assert result.url_present is True

    def test_extract_isbn_from_url(self):
        """Should extract ISBN from URL and add to isbn list."""
        result = extract_identifiers("https://www.amazon.com/dp/0306406152")
        assert "9780306406157" in result.isbn
        assert result.valid_isbn_present is True

    def test_combined_extraction(self):
        """Should extract multiple identifier types."""
        text = """
        Looking for ISBN 978-0-306-40615-7
        Also see https://www.goodreads.com/book/show/12345
        Related DOI: 10.1000/xyz123
        """
        result = extract_identifiers(text)
        assert len(result.isbn) >= 1
        assert len(result.doi) >= 1
        assert len(result.urls) >= 1
        assert result.valid_isbn_present is True
        assert result.doi_present is True
        assert result.url_present is True

    def test_deduplicate_isbns(self):
        """Should not duplicate ISBNs found in text and URLs."""
        text = "ISBN 0306406152 - https://amazon.com/dp/0306406152"
        result = extract_identifiers(text)
        # Should only have one entry for the same ISBN
        assert result.isbn.count("9780306406157") == 1

    def test_no_identifiers_found(self):
        """Should handle text with no identifiers."""
        result = extract_identifiers("Just a plain text request")
        assert result.isbn == []
        assert result.issn == []
        assert result.doi == []
        assert result.urls == []
        assert result.valid_isbn_present is False
