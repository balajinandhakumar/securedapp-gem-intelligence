"""
Local verification script for Phase 2 endpoints using httpx / TestClient.
"""
import json
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def main():
    print("=== Testing Health Endpoint ===")
    r = client.get("/api/v1/health")
    print(f"Health Status: {r.status_code}, Body: {r.json()}")
    assert r.status_code == 200

    print("\n=== Testing JSON Bid Import ===")
    json_bids = [
        {
            "gem_bid_id": "GEM/2026/B/889911",
            "title": "Enterprise SIEM & SOC Implementation",
            "organisation": "Indian Air Force",
            "estimated_value": "25000000",
            "published_date": "2026-03-20",
        },
        {
            "gem_bid_id": "GEM/2026/B/889912",
            "title": "Vulnerability Management Solution",
            "organisation": "DRDO",
            "estimated_value": "18000000",
            "published_date": "2026-03-22",
        }
    ]
    json_bytes = json.dumps(json_bids).encode("utf-8")
    files = {"file": ("ingest_bids.json", json_bytes, "application/json")}
    r_import = client.post("/api/v1/ingestion/import", files=files)
    print(f"JSON Import Status: {r_import.status_code}, Body: {r_import.json()}")
    assert r_import.status_code == 200
    res_data = r_import.json()
    assert res_data["total_records"] == 2
    assert res_data["created"] == 2

    print("\n=== Testing Ingestion Runs Audit Log ===")
    r_runs = client.get("/api/v1/ingestion/runs")
    print(f"Runs List Status: {r_runs.status_code}, Count: {len(r_runs.json())}")
    assert r_runs.status_code == 200
    runs = r_runs.json()
    assert len(runs) > 0

    print("\n=== Phase 2 API Verification Passed Successfully! ===")

if __name__ == "__main__":
    main()
