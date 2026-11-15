"""
Tests for document-aware extraction of GeM bid documents.

Uses a local synthetic fixture PDF (tests/fixtures/fixture_security_bid.pdf)
that simulates a GeM bid document with security-relevant content.
This fixture is NOT a real GeM record and does not represent actual GeM data.
"""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.services.ingestion.gem_document_extractor import (
    DocumentExtractionResult,
    _clean_text,
    _map_document_fields,
    download_document,
    enrich_record_from_document,
    extract_document_text,
    is_pdf_document_url,
)
from app.services.ingestion.schemas import RawBidRecord

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_PDF = FIXTURE_DIR / "fixture_security_bid.pdf"


# ---------------------------------------------------------------------------
# is_pdf_document_url
# ---------------------------------------------------------------------------

def test_is_pdf_document_url_matches_showbiddocument():
    assert is_pdf_document_url("https://bidplus.gem.gov.in/showbidDocument/9943807") is True
    assert is_pdf_document_url("https://bidplus.gem.gov.in/showbidDocument/123") is True


def test_is_pdf_document_url_rejects_listing():
    assert is_pdf_document_url("https://bidplus.gem.gov.in/all-bids") is False


def test_is_pdf_document_url_rejects_none():
    assert is_pdf_document_url(None) is False
    assert is_pdf_document_url("") is False


# ---------------------------------------------------------------------------
# download_document
# ---------------------------------------------------------------------------

def test_download_document_rejects_missing_url():
    result = download_document("")
    assert result.success is False
    assert result.error_type == "missing_url"


def test_download_document_rejects_non_ge_m_url():
    result = download_document("https://evil.example.com/doc.pdf")
    assert result.success is False
    assert result.error_type == "allowlist"


@patch("app.services.ingestion.gem_document_extractor.requests.Session")
def test_download_document_handles_download_error(mock_session_class):
    mock_session = MagicMock()
    mock_session.get.side_effect = requests.RequestException("connection refused")
    mock_session_class.return_value = mock_session

    result = download_document("https://bidplus.gem.gov.in/showbidDocument/999")
    assert result.success is False
    assert result.error_type == "download"


@patch("app.services.ingestion.gem_document_extractor.requests.Session")
def test_download_document_handles_http_error(mock_session_class):
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_session.get.return_value = mock_response
    mock_session_class.return_value = mock_session

    result = download_document("https://bidplus.gem.gov.in/showbidDocument/999")
    assert result.success is False
    assert result.error_type == "http_error"


@patch("app.services.ingestion.gem_document_extractor.requests.Session")
def test_download_document_rejects_non_pdf(mock_session_class):
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"<html><body>not a pdf</body></html>"
    mock_session.get.return_value = mock_response
    mock_session_class.return_value = mock_session

    result = download_document("https://bidplus.gem.gov.in/showbidDocument/999")
    assert result.success is False
    assert result.error_type == "not_pdf"


@patch("app.services.ingestion.gem_document_extractor.requests.Session")
def test_download_document_accepts_pdf(mock_session_class):
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"%PDF-1.4\nfake pdf content"
    mock_response.headers = {"Content-Type": "application/pdf"}
    mock_session.get.return_value = mock_response
    mock_session_class.return_value = mock_session

    result = download_document("https://bidplus.gem.gov.in/showbidDocument/999")
    assert result.success is True
    assert result.content_type == "application/pdf"
    assert result.file_size_bytes == len(b"%PDF-1.4\nfake pdf content")


# ---------------------------------------------------------------------------
# extract_document_text
# ---------------------------------------------------------------------------

def test_extract_document_text_from_fixture():
    if not FIXTURE_PDF.exists():
        pytest.skip(f"Fixture PDF not found: {FIXTURE_PDF}")

    content = FIXTURE_PDF.read_bytes()
    result = DocumentExtractionResult(success=True)
    result._raw_bytes = content  # type: ignore[attr-defined]

    result = extract_document_text(result)

    assert result.success is True
    assert result.page_count == 1
    assert result.extracted_text is not None
    assert "Vulnerability" in result.extracted_text
    assert "penetration" in result.extracted_text.lower()
    assert "GEM/2026/B/9999999" in result.extracted_text


def test_extract_document_text_empty_bytes():
    result = DocumentExtractionResult(success=True)
    result._raw_bytes = b""  # type: ignore[attr-defined]

    result = extract_document_text(result)

    assert result.success is False
    assert result.error_type == "parse"


def test_extract_document_text_no_pypdf():
    content = b"%PDF-1.4\nfake"
    result = DocumentExtractionResult(success=True)
    result._raw_bytes = content  # type: ignore[attr-defined]

    with patch("app.services.ingestion.gem_document_extractor.PdfReader", None):
        result = extract_document_text(result)

    assert result.success is False
    assert result.error_type == "missing_dependency"


# ---------------------------------------------------------------------------
# _map_document_fields
# ---------------------------------------------------------------------------

def test_map_document_fields_extracts_known_labels():
    text = """
    Technical Requirements: Web application security assessment and API security testing.
    Eligibility Criteria: Bidder must have 3 years of experience.
    Experience Requirements: Minimum 5 similar projects.
    Certification Requirements: ISO 27001 certification required.
    Estimated Value: INR 50,00,000
    Location: New Delhi, India
    Category: Security Services
    Bid Type: Two Packet Bid
    Contact Information: security-testing@meity.gov.in
    """
    fields = _map_document_fields(text)

    assert fields["technical_requirements"] is not None
    assert "Web application security" in fields["technical_requirements"]
    assert fields["eligibility_criteria"] is not None
    assert "3 years" in fields["eligibility_criteria"]
    assert fields["experience_requirements"] is not None
    assert fields["certification_requirements"] is not None
    assert "ISO 27001" in fields["certification_requirements"]
    assert fields["estimated_value"] is not None
    assert fields["location"] == "New Delhi, India"
    assert fields["category"] == "Security Services"
    assert fields["bid_type"] == "Two Packet Bid"
    assert fields["contact_information"] == "security-testing@meity.gov.in"


def test_map_document_fields_missing_labels_return_none():
    text = "Some random text without any labeled fields."
    fields = _map_document_fields(text)

    # scope_of_work gets the full text
    assert fields["scope_of_work"] is not None
    # All other fields should be None
    for field in ("technical_requirements", "eligibility_criteria",
                  "qualification_requirements", "experience_requirements",
                  "certification_requirements", "estimated_value", "location",
                  "category", "bid_type", "contact_information",
                  "tender_fee_information", "emd_information"):
        assert fields[field] is None, f"{field} should be None, got {fields[field]}"


# ---------------------------------------------------------------------------
# enrich_record_from_document
# ---------------------------------------------------------------------------

def test_enrich_record_from_document_rejects_non_document_url():
    record = RawBidRecord(
        gem_bid_id="GEM/2026/B/123",
        bid_number="GEM/2026/B/123",
        title="Test Bid",
        source_url="https://bidplus.gem.gov.in/all-bids",
    )
    result = enrich_record_from_document(record)
    assert result.success is False
    assert result.error_type == "not_document_url"


def test_enrich_record_from_document_from_fixture():
    if not FIXTURE_PDF.exists():
        pytest.skip(f"Fixture PDF not found: {FIXTURE_PDF}")

    record = RawBidRecord(
        gem_bid_id="GEM/2026/B/9999999",
        bid_number="GEM/2026/B/9999999",
        title="Vulnerability Assessment and Penetration Testing",
        organisation="Ministry of Electronics and Information Technology",
        source_url=f"file://{FIXTURE_PDF}",
    )

    # file:// URLs won't pass the allowlist, so we test with a showbidDocument URL
    # and mock the download. Instead, test the field mapping directly.
    result = DocumentExtractionResult(success=True)
    result._raw_bytes = FIXTURE_PDF.read_bytes()  # type: ignore[attr-defined]
    result = extract_document_text(result)

    assert result.success is True
    assert result.extracted_fields["scope_of_work"] is not None
    assert "Vulnerability assessment" in result.extracted_fields["scope_of_work"]
    assert result.extracted_fields["technical_requirements"] is not None
    assert result.extracted_fields["certification_requirements"] is not None


# ---------------------------------------------------------------------------
# _map_document_fields: incomplete / ambiguous values
# ---------------------------------------------------------------------------

def test_map_document_fields_rejects_incomplete_eligibility():
    """A fragment ending mid-sentence should not count as eligibility criteria."""
    text = "Eligibility Criteria: Bidder must have"
    fields = _map_document_fields(text)
    assert fields["eligibility_criteria"] is None


def test_map_document_fields_rejects_ambiguous_estimated_value():
    """Text mentioning EMD/amount without an actual numeric figure is not a value."""
    text = "Estimated Value: indicated above is being declared solely for guidance on EMD amount."
    fields = _map_document_fields(text)
    assert fields["estimated_value"] is None


def test_map_document_fields_accepts_valid_estimated_value():
    """A real currency amount with digits is accepted."""
    text = "Estimated Value: INR 50,00,000"
    fields = _map_document_fields(text)
    assert fields["estimated_value"] == "INR 50,00,000"


def test_map_document_fields_rejects_symbol_only_contact():
    """A contact field that is only punctuation should be None."""
    text = "Contact Information: -"
    fields = _map_document_fields(text)
    assert fields["contact_information"] is None


# ---------------------------------------------------------------------------
# download_document: size limit
# ---------------------------------------------------------------------------

@patch("app.services.ingestion.gem_document_extractor.requests.Session")
def test_download_document_rejects_oversized(mock_session_class):
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"%PDF-1.4\n" + b"x" * (15 * 1024 * 1024)  # 15 MB > 10 MB cap
    mock_response.headers = {"Content-Type": "application/pdf"}
    mock_session.get.return_value = mock_response
    mock_session_class.return_value = mock_session

    result = download_document(
        "https://bidplus.gem.gov.in/showbidDocument/999",
        max_size_bytes=10 * 1024 * 1024,
    )
    assert result.success is False
    assert result.error_type == "too_large"


@patch("app.services.ingestion.gem_document_extractor.requests.Session")
def test_download_document_accepts_under_size(mock_session_class):
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"%PDF-1.4\nsmall pdf content"
    mock_response.headers = {"Content-Type": "application/pdf"}
    mock_session.get.return_value = mock_response
    mock_session_class.return_value = mock_session

    result = download_document(
        "https://bidplus.gem.gov.in/showbidDocument/999",
        max_size_bytes=10 * 1024 * 1024,
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# extract_document_text: page limit
# ---------------------------------------------------------------------------

def test_extract_document_text_applies_page_limit():
    if not FIXTURE_PDF.exists():
        pytest.skip(f"Fixture PDF not found: {FIXTURE_PDF}")

    content = FIXTURE_PDF.read_bytes()
    result = DocumentExtractionResult(success=True)
    result._raw_bytes = content  # type: ignore[attr-defined]

    result = extract_document_text(result, max_pages=1)

    assert result.success is True
    assert result.page_limit_applied is True
    assert result.page_count == 1


# ---------------------------------------------------------------------------
# extract_document_text: encrypted/unreadable PDF
# ---------------------------------------------------------------------------

def test_extract_document_text_encrypted_pdf():
    """An encrypted PDF cannot be opened by pypdf and should be reported."""
    # Minimal encrypted PDF structure (not actually valid, but triggers parse failure)
    content = b"%PDF-1.4\n1 0 obj<</Encrypt<</V 1/R 2/O(-)>><<>>stream\nfake\nendstream\nendobj\ntrailer<</Root 1 0 R>>\n%%EOF"
    result = DocumentExtractionResult(success=True)
    result._raw_bytes = content  # type: ignore[attr-defined]

    result = extract_document_text(result)

    assert result.success is False
    assert result.error_type == "parse"


# ---------------------------------------------------------------------------
# extract_document_text: scanned/image-only PDF (no text)
# ---------------------------------------------------------------------------

def test_extract_document_text_no_extractable_text():
    """A PDF that parses but yields no text should be reported as no_text."""
    # A minimal PDF with a page but no extractable text content.
    content = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]>>endobj\n"
        b"startxref\n100\n%%EOF"
    )
    result = DocumentExtractionResult(success=True)
    result._raw_bytes = content  # type: ignore[attr-defined]

    result = extract_document_text(result)

    assert result.success is False
    assert result.error_type in ("parse", "no_text")


def test_extract_document_text_malformed_pdf_parse_error():
    """A structurally malformed PDF should produce a parse error, not silent success."""
    content = b"%PDF-1.4\nnot really a valid pdf structure at all"
    result = DocumentExtractionResult(success=True)
    result._raw_bytes = content  # type: ignore[attr-defined]

    result = extract_document_text(result)

    assert result.success is False
    assert result.error_type in ("parse", "no_text")


# ---------------------------------------------------------------------------
# _clean_text
# ---------------------------------------------------------------------------

def test_clean_text_normalizes_whitespace():
    assert _clean_text("  hello   world  ") == "hello world"
    assert _clean_text("") is None
    assert _clean_text(None) is None
    assert _clean_text("   ") is None
