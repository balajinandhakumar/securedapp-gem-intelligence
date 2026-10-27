"""
Tests for Phase 3: Product Knowledge Layer, Deterministic Matching Engine, Product Differentiation, and API.
"""
import pytest
from fastapi.testclient import TestClient

from app.db.seed_knowledge import seed_product_knowledge
from app.models.bid import Bid
from app.models.analysis import BidProductMatch, BidAnalysis
from app.models.product import Product
from app.services.intelligence import match_bid_against_products


@pytest.fixture(autouse=True)
def seed_knowledge(db):
    """Seed product knowledge into the test DB before each test."""
    seed_product_knowledge(db)


def test_seed_knowledge(db):
    products = db.query(Product).all()
    assert len(products) == 11
    names = {p.name for p in products}
    assert "SolidityShield" in names
    assert "SecureTrace" in names
    assert "PQCSuite" in names
    assert "QuantumVault" in names


def test_differentiation_solidityshield_vs_auditexpress(db):
    # Bid 1: Explicit expert review -> SolidityShield should rank highest
    bid_expert = Bid(
        title="Solidity Smart Contract Security Audit and Manual Expert Review",
        scope_of_work="Requires pre-deployment vulnerability detection with expert security review and remediation validation.",
    )
    db.add(bid_expert)
    db.commit()

    results = match_bid_against_products(db, bid_expert)
    top_match = results[0]
    assert top_match.product_name == "SolidityShield"
    assert top_match.match_state == "MATCH"
    assert top_match.relevance_score >= 0.70

    # Bid 2: Rapid automated scan -> AuditExpress should rank high
    bid_auto = Bid(
        title="Automated Security Assessment for Smart Contracts",
        scope_of_work="Rapid automated security assessment and vulnerability scanning for smart contract posture.",
    )
    db.add(bid_auto)
    db.commit()

    results_auto = match_bid_against_products(db, bid_auto)
    audit_express_res = next(r for r in results_auto if r.product_name == "AuditExpress")
    assert audit_express_res.match_state in ("MATCH", "POSSIBLE_MATCH")


def test_differentiation_securetrace_vs_securewatch(db):
    # Bid 1: Forensic investigation -> SecureTrace
    bid_trace = Bid(
        title="Blockchain Investigation and Transaction Tracing Platform",
        scope_of_work="Forensic fund-flow analysis and tracing suspicious transactions across wallets.",
    )
    db.add(bid_trace)
    db.commit()

    res_trace = match_bid_against_products(db, bid_trace)
    assert res_trace[0].product_name == "SecureTrace"
    assert res_trace[0].match_state == "MATCH"

    # Bid 2: Continuous monitoring -> SecureWatch
    bid_watch = Bid(
        title="Blockchain Transaction Continuous Monitoring and Alerting",
        scope_of_work="Continuous monitoring of smart contract activity with anomaly detection and real-time alerts.",
    )
    db.add(bid_watch)
    db.commit()

    res_watch = match_bid_against_products(db, bid_watch)
    assert res_watch[0].product_name == "SecureWatch"
    assert res_watch[0].match_state == "MATCH"


def test_differentiation_securecms_vs_cookiehub(db):
    # Website cookie consent -> CookieHub
    bid_cookie = Bid(
        title="Website Cookie Consent and Tracking-Script Management System",
        scope_of_work="Collecting website user consent and controlling analytics tracking scripts based on user consent.",
    )
    db.add(bid_cookie)
    db.commit()

    res_cookie = match_bid_against_products(db, bid_cookie)
    assert res_cookie[0].product_name == "CookieHub"
    assert res_cookie[0].match_state == "MATCH"

    # Privacy compliance records -> SecureCMS
    bid_cms = Bid(
        title="Enterprise User Consent Management and Privacy Compliance Platform",
        scope_of_work="Tracking user consent records, consent withdrawal, and privacy audit compliance logs.",
    )
    db.add(bid_cms)
    db.commit()

    res_cms = match_bid_against_products(db, bid_cms)
    assert res_cms[0].product_name == "SecureCMS"
    assert res_cms[0].match_state == "MATCH"


def test_differentiation_pqcsuite_vs_quantumvault(db):
    # Software Crypto Agility -> PQCSuite
    bid_pqc = Bid(
        title="Post-Quantum Cryptography Migration and Crypto Agility Software",
        scope_of_work="Flexible cryptographic layer for post-quantum algorithm migration.",
    )
    db.add(bid_pqc)
    db.commit()

    res_pqc = match_bid_against_products(db, bid_pqc)
    assert res_pqc[0].product_name == "PQCSuite"
    assert res_pqc[0].match_state == "MATCH"

    # Hardware Key Protection HSM -> QuantumVault
    bid_hsm = Bid(
        title="Hardware-Backed Cryptographic Key Protection and HSM Management",
        scope_of_work="Hardware security module (HSM) based key generation, storage, and access control.",
    )
    db.add(bid_hsm)
    db.commit()

    res_hsm = match_bid_against_products(db, bid_hsm)
    assert res_hsm[0].product_name == "QuantumVault"
    assert res_hsm[0].match_state == "MATCH"


def test_differentiation_securexdid_vs_securexid(db):
    # Decentralized Identity -> SecureX-DID
    bid_did = Bid(
        title="Decentralized Identity and Verifiable Credentials Issuance System",
        scope_of_work="Issuance, storage, presentation, and verification of W3C verifiable credentials.",
    )
    db.add(bid_did)
    db.commit()

    res_did = match_bid_against_products(db, bid_did)
    assert res_did[0].product_name == "SecureX-DID"

    # Identity Verification KYC/AML -> SecureX-ID
    bid_xid = Bid(
        title="Web3 Identity Verification and KYC/AML Compliance Solution",
        scope_of_work="Identity verification, AML screening, watchlist checks, and X-ID score risk assessment.",
    )
    db.add(bid_xid)
    db.commit()

    res_xid = match_bid_against_products(db, bid_xid)
    assert res_xid[0].product_name == "SecureX-ID"


def test_unmatched_bid(db):
    bid_civil = Bid(
        title="Supply of Office Furniture and Wooden Chairs",
        scope_of_work="Procurement of ergonomically designed office chairs and wooden tables.",
    )
    db.add(bid_civil)
    db.commit()

    results = match_bid_against_products(db, bid_civil)
    for r in results:
        assert r.match_state == "NO_MATCH"
        assert r.relevance_score < 0.25


def test_match_api_endpoint(client: TestClient, db):
    bid = Bid(
        title="Solidity Smart Contract Security Review and Audit",
        scope_of_work="Comprehensive vulnerability detection and expert audit of smart contracts.",
    )
    db.add(bid)
    db.commit()

    response = client.post(f"/api/v1/bids/{bid.id}/match-products")
    assert response.status_code == 200
    data = response.json()
    assert data["bid_id"] == str(bid.id)
    assert len(data["candidate_products"]) == 11

    # Check persistence in DB
    db_matches = db.query(BidProductMatch).filter(BidProductMatch.bid_id == bid.id).all()
    assert len(db_matches) >= 1

    db_analyses = db.query(BidAnalysis).filter(BidAnalysis.bid_id == bid.id).all()
    assert len(db_analyses) == 1
    assert db_analyses[0].engine_version == "Phase3-Deterministic"


def test_score_classification_boundaries():
    from app.services.intelligence.matching_engine import classify_score

    assert classify_score(0.750) == "MATCH"
    assert classify_score(0.700) == "MATCH"
    assert classify_score(0.699) == "POSSIBLE_MATCH"
    assert classify_score(0.450) == "POSSIBLE_MATCH"
    assert classify_score(0.449) == "NEEDS_REVIEW"
    assert classify_score(0.250) == "NEEDS_REVIEW"
    assert classify_score(0.249) == "NO_MATCH"
    assert classify_score(0.000) == "NO_MATCH"

