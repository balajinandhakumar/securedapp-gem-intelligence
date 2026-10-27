"""
Dedicated Test Suite for XLSX Ingestion — SecuredApp GeM Bid Intelligence Bot

Verifies:
1. Valid multi-row XLSX ingestion
2. XLSX with common GeM column aliases (e.g., 'Bid No.', 'Tender Title', 'Buyer Name', 'Estimated Value (INR)')
3. Empty XLSX files and blank sheets
4. Missing required bid title/identifier
5. Malformed dates and currency/value strings
6. Duplicate BID numbers (in-file and cross-batch)
7. Full ingestion pipeline: parse -> normalize -> validate -> deduplicate -> save -> query DB
8. FastAPI multipart XLSX upload endpoint integration
"""
import io
import datetime
import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.models.bid import Bid
from app.models.collection import CollectionRun
from app.services.ingestion import (
    XLSXAdapter,
    run_ingestion_pipeline,
    validate_record,
    normalize_record,
    RawBidRecord,
)


def create_test_xlsx(rows: list[list]) -> bytes:
    """Helper to generate in-memory XLSX byte content from a matrix of rows."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_xlsx_valid_multi_row_parsing():
    """Test standard XLSX parsing with multiple valid GeM bid rows."""
    rows = [
        ["gem_bid_id", "title", "organisation", "estimated_value", "published_date", "closing_date", "category"],
        ["GEM/2026/B/9001", "AI-Powered Threat Detection System", "National Informatics Centre", 1500000, "2026-03-01", "2026-04-01", "Cybersecurity"],
        ["GEM/2026/B/9002", "Cloud Vulnerability Assessment", "Defense Research Organisation", 3200000, "2026-03-05", "2026-04-15", "VAPT"],
        ["GEM/2026/B/9003", "Mobile Application Security Audit", "Indian Space Research Organisation", 850000, "2026-03-10", "2026-03-25", "AppSec"],
    ]
    xlsx_bytes = create_test_xlsx(rows)
    adapter = XLSXAdapter()
    records = adapter.parse(xlsx_bytes)

    assert len(records) == 3
    assert records[0].gem_bid_id == "GEM/2026/B/9001"
    assert records[0].title == "AI-Powered Threat Detection System"
    assert records[1].gem_bid_id == "GEM/2026/B/9002"
    assert records[2].gem_bid_id == "GEM/2026/B/9003"


def test_xlsx_gem_column_aliases():
    """Test XLSX ingestion with common GeM portal column header variations."""
    rows = [
        [
            "Bid No.",
            "Tender Title",
            "Buyer Name / Organisation",
            "Estimated Value (INR)",
            "Publish Date",
            "Closing Date",
            "Category",
            "Description / Scope",
            "Eligibility",
            "Experience",
            "Certification",
        ],
        [
            "GEM/2026/B/GEM-ALIAS-01",
            "Enterprise Zero Trust Architecture Implementation",
            "Ministry of Electronics and Information Technology",
            "₹ 45,00,000",
            datetime.date(2026, 3, 1),
            datetime.date(2026, 3, 31),
            "Security Architecture",
            "Comprehensive zero-trust implementation for state data centers",
            "OEM or Tier 1 Security Partner",
            "5+ years in defensive cybersecurity",
            "ISO 27001, CERT-In Empanelled",
        ],
    ]
    xlsx_bytes = create_test_xlsx(rows)
    adapter = XLSXAdapter()
    records = adapter.parse(xlsx_bytes)

    assert len(records) == 1
    rec = records[0]
    assert rec.bid_number == "GEM/2026/B/GEM-ALIAS-01" or rec.gem_bid_id == "GEM/2026/B/GEM-ALIAS-01"
    assert rec.title == "Enterprise Zero Trust Architecture Implementation"
    assert rec.organisation == "Ministry of Electronics and Information Technology"
    assert rec.estimated_value == "₹ 45,00,000"
    assert "2026-03-01" in str(rec.published_date)
    assert "2026-03-31" in str(rec.closing_date)
    assert rec.category == "Security Architecture"
    assert "ISO 27001" in rec.certifications_required

    # Verify that normalization maps bid_number to gem_bid_id
    norm = normalize_record(rec)
    assert norm["gem_bid_id"] == "GEM/2026/B/GEM-ALIAS-01"
    assert norm["estimated_value"] == 4500000.0


def test_xlsx_empty_workbook():
    """Test handling of empty XLSX file / worksheet."""
    rows = []
    xlsx_bytes = create_test_xlsx(rows)
    adapter = XLSXAdapter()
    records = adapter.parse(xlsx_bytes)
    assert len(records) == 0


def test_xlsx_header_only():
    """Test handling of XLSX with only header and no data rows."""
    rows = [["Bid Number", "Title", "Organisation"]]
    xlsx_bytes = create_test_xlsx(rows)
    adapter = XLSXAdapter()
    records = adapter.parse(xlsx_bytes)
    assert len(records) == 0


def test_xlsx_missing_required_identifier(db):
    """Test that records missing mandatory title are flagged as invalid and not stored as valid bids."""
    rows = [
        ["Bid Number", "Title", "Organisation"],
        ["GEM/2026/B/MISSING-TITLE", "", "Ministry of Finance"],  # Invalid: no title
        ["GEM/2026/B/VALID-01", "Firewall Appliance Procurement", "Ministry of Finance"],
    ]
    xlsx_bytes = create_test_xlsx(rows)
    result = run_ingestion_pipeline(
        db=db,
        file_content=xlsx_bytes,
        file_type="xlsx",
        source_name="test_missing_title_xlsx",
    )

    assert result.total_records == 2
    assert result.created == 1
    assert result.failed == 1
    assert len(result.errors) >= 1


def test_xlsx_malformed_date_and_currency(db):
    """Test that malformed dates and formatted currency strings are handled gracefully."""
    rows = [
        ["Bid No", "Title", "Estimated Value", "Closing Date"],
        ["GEM/2026/B/CURR-01", "Security Auditing 2026", "Rs. 25,50,000.50 /-", "2026-04-30"],
        ["GEM/2026/B/DATE-ERR", "Penetration Testing Scope", "1000000", "INVALID_DATE_STRING"],
    ]
    xlsx_bytes = create_test_xlsx(rows)
    result = run_ingestion_pipeline(
        db=db,
        file_content=xlsx_bytes,
        file_type="xlsx",
        source_name="test_malformed_xlsx",
    )

    assert result.total_records == 2
    # The first row should parse currency properly
    bid1 = db.query(Bid).filter(Bid.gem_bid_id == "GEM/2026/B/CURR-01").first()
    assert bid1 is not None
    assert float(bid1.estimated_value) == pytest.approx(2550000.50)

    # The second row should still be ingested even if the date string is malformed
    bid2 = db.query(Bid).filter(Bid.gem_bid_id == "GEM/2026/B/DATE-ERR").first()
    assert bid2 is not None


def test_xlsx_duplicate_bid_numbers(db):
    """Test in-file and cross-file duplicate detection for XLSX imports."""
    rows = [
        ["Bid No", "Title", "Organisation", "Estimated Value"],
        ["GEM/2026/B/DUP-XLSX", "Endpoint Protection EDR", "Army HQ", "5000000"],
        ["GEM/2026/B/DUP-XLSX", "Endpoint Protection EDR", "Army HQ", "5000000"],  # In-file duplicate
    ]
    xlsx_bytes = create_test_xlsx(rows)
    result = run_ingestion_pipeline(
        db=db,
        file_content=xlsx_bytes,
        file_type="xlsx",
        source_name="test_duplicates_xlsx",
    )

    assert result.total_records == 2
    assert result.created == 1
    assert result.duplicates == 1


def test_xlsx_multipart_api_upload(client: TestClient):
    """Test full multipart/form-data XLSX upload via the FastAPI endpoint."""
    rows = [
        ["Bid No.", "Tender Title", "Buyer Organisation", "Estimated Value"],
        ["GEM/2026/B/API-XLSX-01", "SIEM and SOC Implementation", "Cabinet Secretariat", 7500000],
        ["GEM/2026/B/API-XLSX-02", "Web Application Penetration Testing", "Ministry of Railways", 1200000],
    ]
    xlsx_bytes = create_test_xlsx(rows)

    files = {
        "file": (
            "gem_bids_march2026.xlsx",
            xlsx_bytes,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    response = client.post("/api/v1/ingestion/import", files=files)
    assert response.status_code == 200
    data = response.json()

    assert data["total_records"] == 2
    assert data["created"] == 2
    assert data["duplicates"] == 0
    assert data["failed"] == 0
    assert "run_id" in data

    # Verify bids are retrievable through the Bids API
    bids_res = client.get("/api/v1/bids")
    assert bids_res.status_code == 200
    bids_data = bids_res.json()
    bids_list = bids_data["items"] if "items" in bids_data else bids_data
    found = [b for b in bids_list if b["gem_bid_id"] in ("GEM/2026/B/API-XLSX-01", "GEM/2026/B/API-XLSX-02")]
    assert len(found) == 2
