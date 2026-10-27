"""
Tests for Phase 2: Ingestion pipeline, adapters, validator, normalizer, duplicate detector, and API endpoints.
"""
import io
import json
import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.models.bid import Bid
from app.models.collection import CollectionRun
from app.services.ingestion import (
    JSONAdapter,
    CSVAdapter,
    XLSXAdapter,
    validate_record,
    normalize_record,
    check_duplicate,
    run_ingestion_pipeline,
    RawBidRecord,
)


def test_json_adapter_parsing():
    json_data = json.dumps([
        {
            "gem_bid_id": "GEM/2026/B/1001",
            "title": "Cyber Security Audit Service",
            "organisation": "Ministry of Defense",
            "estimated_value": "500000",
            "published_date": "2026-03-01",
        }
    ]).encode("utf-8")

    adapter = JSONAdapter()
    records = adapter.parse(json_data)
    assert len(records) == 1
    assert records[0].gem_bid_id == "GEM/2026/B/1001"
    assert records[0].title == "Cyber Security Audit Service"


def test_csv_adapter_parsing():
    csv_data = (
        "BID NO,BID TITLE,ORGANISATION,ESTIMATED VALUE\n"
        "GEM/2026/B/2002,Web Application Firewall,ISRO,1200000\n"
    ).encode("utf-8")

    adapter = CSVAdapter()
    records = adapter.parse(csv_data)
    assert len(records) == 1
    assert (records[0].bid_number == "GEM/2026/B/2002" or records[0].gem_bid_id == "GEM/2026/B/2002")
    assert records[0].title == "Web Application Firewall"


def test_json_adapter_accepts_utf8_bom():
    # Exports produced by spreadsheet/government tooling frequently carry a
    # UTF-8 byte-order mark; it must not reject an otherwise valid document.
    json_data = (
        "\ufeff" + json.dumps([
            {
                "gem_bid_id": "GEM/2026/B/BOM1",
                "title": "Cyber Security Audit Service",
                "organisation": "Ministry of Defense",
                "estimated_value": "500000",
                "published_date": "2026-03-01",
            }
        ])
    ).encode("utf-8")

    adapter = JSONAdapter()
    records = adapter.parse(json_data)
    assert len(records) == 1
    assert records[0].gem_bid_id == "GEM/2026/B/BOM1"
    assert records[0].title == "Cyber Security Audit Service"


def test_csv_adapter_accepts_utf8_bom():
    csv_data = (
        "\ufeff" +
        "BID NO,BID TITLE,ORGANISATION,ESTIMATED VALUE\n"
        "GEM/2026/B/BOM2,Web Application Firewall,ISRO,1200000\n"
    ).encode("utf-8")

    adapter = CSVAdapter()
    records = adapter.parse(csv_data)
    assert len(records) == 1
    assert (records[0].bid_number == "GEM/2026/B/BOM2" or records[0].gem_bid_id == "GEM/2026/B/BOM2")
    assert records[0].title == "Web Application Firewall"


def test_xlsx_adapter_parsing():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["gem_bid_id", "title", "organisation", "estimated_value"])
    ws.append(["GEM/2026/B/3003", "SOC Managed Services", "DRDO", "4500000"])

    output = io.BytesIO()
    wb.save(output)
    xlsx_bytes = output.getvalue()

    adapter = XLSXAdapter()
    records = adapter.parse(xlsx_bytes)
    assert len(records) == 1
    assert records[0].gem_bid_id == "GEM/2026/B/3003"
    assert records[0].title == "SOC Managed Services"


def test_validation():
    # Invalid record (missing title)
    raw_invalid = RawBidRecord(gem_bid_id="GEM/1", title="")
    res_invalid = validate_record(raw_invalid, index=0)
    assert not res_invalid.is_valid
    assert len(res_invalid.errors) > 0

    # Valid record
    raw_valid = RawBidRecord(gem_bid_id="GEM/1", title="Penetration Testing Service")
    res_valid = validate_record(raw_valid, index=0)
    assert res_valid.is_valid


def test_normalization():
    raw = RawBidRecord(
        gem_bid_id=" GEM/2026/B/9999 ",
        title=" Cyber   Security  Consulting ",
        published_date="2026-03-15 10:30:00",
        estimated_value="₹ 15,00,000",
        currency="inr",
    )
    norm = normalize_record(raw)
    assert norm["gem_bid_id"] == "GEM/2026/B/9999"
    assert norm["title"] == "Cyber Security Consulting"
    assert norm["estimated_value"] == 1500000.0
    assert norm["currency"] == "INR"
    assert norm["hash"] is not None


def test_duplicate_detection(db):
    # Seed an existing bid
    existing = Bid(
        gem_bid_id="GEM/DUP/001",
        title="Existing SIEM System Procurement",
        content_hash="dummyhash123",
    )
    db.add(existing)
    db.commit()

    # Exact match check by gem_bid_id
    res_exact = check_duplicate(db, {"gem_bid_id": "GEM/DUP/001", "title": "Existing SIEM System Procurement"})
    assert res_exact.is_exact
    assert res_exact.existing_bid.id == existing.id

    # New bid check
    res_new = check_duplicate(db, {"gem_bid_id": "GEM/NEW/999", "title": "Brand New Cloud Security Platform"})
    assert not res_new.is_duplicate


def test_ingestion_pipeline_e2e(db):
    json_data = json.dumps([
        {
            "gem_bid_id": "GEM/2026/B/7777",
            "title": "Endpoint Detection and Response (EDR)",
            "organisation": "Ministry of Home Affairs",
            "estimated_value": "8000000",
        },
        {
            "gem_bid_id": "GEM/2026/B/7777",  # Duplicate
            "title": "Endpoint Detection and Response (EDR)",
            "organisation": "Ministry of Home Affairs",
            "estimated_value": "8000000",
        }
    ]).encode("utf-8")

    result = run_ingestion_pipeline(
        db=db,
        file_content=json_data,
        file_type="json",
        source_name="test_e2e_json",
    )

    assert result.status in ("completed", "success")
    assert result.total_records == 2
    assert result.created == 1
    assert result.duplicates == 1

    # Check CollectionRun in DB
    run = db.query(CollectionRun).filter(CollectionRun.id == result.run_id).first()
    assert run is not None
    assert run.records_found == 2
    assert run.records_new == 1


def test_import_api_endpoint(client: TestClient):
    csv_content = (
        "gem_bid_id,title,organisation,estimated_value\n"
        "GEM/2026/B/8888,Network Vulnerability Assessment,NIC,350000\n"
    )
    files = {
        "file": ("bids_sample.csv", csv_content.encode("utf-8"), "text/csv")
    }
    response = client.post("/api/v1/ingestion/import", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["total_records"] == 1
    assert data["created"] == 1

    # Check listing ingestion runs
    runs_res = client.get("/api/v1/ingestion/runs")
    assert runs_res.status_code == 200
    runs = runs_res.json()
    assert len(runs) >= 1

