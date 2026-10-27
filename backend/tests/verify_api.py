import sys
import os
import json
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.seed import seed_products

client = TestClient(app)

def run_api_verification():
    # Ensure database tables exist & seed products
    seed_products()

    print("\n--- 1. GET /api/v1/health ---")
    res_health = client.get("/api/v1/health")
    print(f"Status: {res_health.status_code}")
    print(f"Response: {res_health.json()}")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "ok"

    print("\n--- 2. GET /api/v1/products ---")
    res_products = client.get("/api/v1/products")
    print(f"Status: {res_products.status_code}")
    products = res_products.json()
    print(f"Total products returned: {len(products)}")
    print(f"Product names: {[p['name'] for p in products]}")
    assert res_products.status_code == 200
    assert len(products) == 11

    print("\n--- 3. GET /api/v1/bids ---")
    res_bids = client.get("/api/v1/bids")
    print(f"Status: {res_bids.status_code}")
    print(f"Bids returned: {res_bids.json()}")
    assert res_bids.status_code == 200

    print("\n--- 4. POST /api/v1/products (Valid Payload) ---")
    valid_product_payload = {
        "name": "CustomSecuritySuite",
        "description": "Custom enterprise security monitoring suite",
        "priority": 10
    }
    res_post_prod = client.post("/api/v1/products", json=valid_product_payload)
    print(f"Status: {res_post_prod.status_code}")
    print(f"Response: {res_post_prod.json()}")
    assert res_post_prod.status_code == 201
    assert res_post_prod.json()["name"] == "CustomSecuritySuite"

    print("\n--- 5. POST /api/v1/products (Invalid Payload - Duplicate Name) ---")
    res_dup_prod = client.post("/api/v1/products", json=valid_product_payload)
    print(f"Status: {res_dup_prod.status_code}")
    print(f"Response: {res_dup_prod.json()}")
    assert res_dup_prod.status_code == 400

    print("\n--- 6. POST /api/v1/bids (Valid Payload) ---")
    valid_bid_payload = {
        "gem_bid_id": "GEM/2026/B/88888",
        "bid_number": "GEM-88888",
        "title": "Quantum Vault Encryption Infrastructure Upgrade",
        "organisation": "Defence Research and Development Organisation",
        "department": "Cyber Security Division",
        "category": "Quantum Safe Encryption",
        "estimated_value": 15000000.00,
        "currency": "INR",
        "scope_of_work": "Implementation of PQC suite for secure communications.",
        "status": "NEW"
    }
    res_post_bid = client.post("/api/v1/bids", json=valid_bid_payload)
    print(f"Status: {res_post_bid.status_code}")
    print(f"Response: {res_post_bid.json()}")
    assert res_post_bid.status_code == 201
    assert res_post_bid.json()["bid_number"] == "GEM-88888"

    print("\n--- 7. POST /api/v1/bids (Invalid Payload - Missing Required 'title') ---")
    invalid_bid_payload = {
        "gem_bid_id": "GEM/2026/B/77777"
        # Missing required 'title'
    }
    res_invalid_bid = client.post("/api/v1/bids", json=invalid_bid_payload)
    print(f"Status: {res_invalid_bid.status_code}")
    print(f"Response (Validation Error): {res_invalid_bid.json()}")
    assert res_invalid_bid.status_code == 422  # Unprocessable Entity validation error

    print("\nALL API VERIFICATION CHECKS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_api_verification()
