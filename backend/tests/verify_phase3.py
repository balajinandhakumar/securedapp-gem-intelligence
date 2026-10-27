"""
Verification script for Phase 3 end-to-end matching API and database persistence.
"""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def main():
    print("=== Phase 3 Verification Start ===")

    # 1. Ingest a sample bid via Phase 2 API
    csv_content = (
        "gem_bid_id,title,organisation,scope_of_work,estimated_value\n"
        "GEM/2026/B/99001,Post-Quantum Cryptography Migration and Crypto-Agility Layer,Ministry of Electronics,Post-quantum cryptographic algorithm migration and flexible crypto layer implementation.,5000000\n"
    )
    files = {"file": ("pqc_bid.csv", csv_content.encode("utf-8"), "text/csv")}
    r_ingest = client.post("/api/v1/ingestion/import", files=files)
    assert r_ingest.status_code == 200
    print("1. Ingestion of PQC bid successful!")

    # 2. Get the created bid ID from list_bids
    r_bids = client.get("/api/v1/bids")
    assert r_bids.status_code == 200
    bids = r_bids.json()
    target_bid = next(b for b in bids if b["gem_bid_id"] == "GEM/2026/B/99001")
    bid_id = target_bid["id"]
    print(f"2. Retrieved Bid ID: {bid_id}")

    # 3. Call POST /api/v1/bids/{bid_id}/match-products
    r_match = client.post(f"/api/v1/bids/{bid_id}/match-products")
    assert r_match.status_code == 200
    match_data = r_match.json()
    print("\n3. Product Match Results:")
    top_candidate = match_data["candidate_products"][0]
    print(f"   Top Match: {top_candidate['product_name']} ({top_candidate['match_state']}) Score: {top_candidate['relevance_score']}")
    print(f"   Reason: {top_candidate['reason']}")
    print(f"   Signals: {top_candidate['signals']}")

    assert top_candidate["product_name"] == "PQCSuite"
    assert top_candidate["match_state"] == "MATCH"

    print("\n=== Phase 3 Verification Passed 100%! ===")

if __name__ == "__main__":
    main()
