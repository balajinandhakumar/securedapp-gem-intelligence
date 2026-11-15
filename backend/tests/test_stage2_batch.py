"""
Stage 2: GeM Bid Intelligence & Batch Processing Tests
======================================================

Comprehensive test suite verifying:
1. Single bid → product matching (all 11 SecuredApp products)
2. Single bid → explainable evidence
3. Single bid → requirement analysis
4. Single bid → opportunity analysis
5. Relevant bid → notification
6. Duplicate notification prevention
7. Human review workflow and auditability
8. 1,000-bid synthetic batch pipeline
9. Multiple product candidates & differentiation rules:
   - SolidityShield vs AuditExpress
   - SecureTrace vs SecureWatch
   - SecureCMS vs CookieHub
   - SecureX-DID vs SecureX-ID
   - PQCSuite vs QuantumVault
10. No-match bid
11. Incomplete bid
12. Updated bid
13. End-to-end pipeline
"""
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.seed_knowledge import seed_product_knowledge
from app.models.analysis import BidAnalysis, BidProductMatch, BidScore
from app.models.bid import Bid
from app.models.notification import Notification
from app.models.product import Product
from app.models.review import HumanReview
from app.services.ingestion import run_ingestion_pipeline
from app.services.intelligence import (
    DeterministicLLMProvider,
    OpportunityAnalyzer,
    classify_score,
    match_bid_against_products,
    process_bid_intelligence,
    run_batch_intelligence_pipeline,
)


@pytest.fixture(autouse=True)
def ensure_knowledge_seeded(db: Session):
    """Seed the 11 SecuredApp products knowledge base in the test DB."""
    seed_product_knowledge(db)


# ---------------------------------------------------------------------------
# Test 1: Single bid → product matching (all 11 SecuredApp products)
# ---------------------------------------------------------------------------
def test_single_bid_product_matching_11_products(db: Session):
    """Verify that every ingested bid is evaluated against all 11 SecuredApp products."""
    products = db.query(Product).filter(Product.active == True).all()
    assert len(products) == 11, f"Expected 11 products, found {len(products)}"

    bid = Bid(
        gem_bid_id="GEM/2026/B/20001",
        title="Smart Contract Security Audit and Solidity Vulnerability Scan",
        scope_of_work="Conducting automated vulnerability scanning, reentrancy detection, and expert security review for EVM contracts.",
        category="Cyber Security",
    )
    db.add(bid)
    db.commit()

    results = match_bid_against_products(db, bid)
    assert len(results) == 11, "Must evaluate against all 11 products"

    top_match = results[0]
    assert top_match.product_name == "SolidityShield"
    assert top_match.relevance_score >= 0.70
    assert top_match.match_state == "MATCH"
    assert top_match.confidence > 0.5


# ---------------------------------------------------------------------------
# Test 2: Single bid → explainable evidence
# ---------------------------------------------------------------------------
def test_single_bid_explainable_evidence(db: Session):
    """Verify evidence grounding, signal extraction, score breakdown, and explanation reason."""
    bid = Bid(
        gem_bid_id="GEM/2026/B/20002",
        title="Blockchain Forensics and Cryptocurrency Transaction Tracing System",
        scope_of_work="Forensic investigation, wallet tracing, fund-flow analysis, and suspicious transaction investigation.",
        category="Forensic Software",
    )
    db.add(bid)
    db.commit()

    results = match_bid_against_products(db, bid)
    top_match = results[0]
    assert top_match.product_name == "SecureTrace"
    assert len(top_match.signals) > 0

    # Verify signal attributes
    sig = top_match.signals[0]
    assert "type" in sig
    assert "field" in sig
    assert "strength" in sig
    assert "snippet" in sig

    # Verify score breakdown
    bd = top_match.score_breakdown
    assert "raw_score" in bd
    assert "normalized_score" in bd
    assert "classification" in bd
    assert "confidence" in bd
    assert top_match.reason != ""


# ---------------------------------------------------------------------------
# Test 3: Single bid → requirement analysis
# ---------------------------------------------------------------------------
def test_single_bid_requirement_analysis(db: Session):
    """Verify structured requirement, deadline intelligence, and eligibility extraction."""
    now = datetime.now(timezone.utc)
    bid = Bid(
        gem_bid_id="GEM/2026/B/20003",
        title="Enterprise User Consent Management and Privacy Compliance Platform",
        scope_of_work="Platform for user consent records, consent withdrawal, and privacy compliance tracking.",
        closing_date=now + timedelta(days=20),
        technical_requirements={"certifications": ["ISO 27001"], "experience_years": 3},
        eligibility_criteria={"annual_turnover_inr": 10000000.0},
    )
    db.add(bid)
    db.commit()

    matches = match_bid_against_products(db, bid)
    llm = DeterministicLLMProvider()
    intel = llm.analyze_bid(bid, matches)

    assert intel.bid_title == bid.title
    assert intel.deadline_intelligence.status == "NORMAL"
    assert intel.deadline_intelligence.days_remaining is not None
    assert len(intel.requirements) >= 1
    assert len(intel.eligibility_assessments) >= 1


# ---------------------------------------------------------------------------
# Test 4: Single bid → opportunity analysis
# ---------------------------------------------------------------------------
def test_single_bid_opportunity_analysis(db: Session):
    """Verify opportunity rating calculation, separation from relevance, and component breakdown."""
    now = datetime.now(timezone.utc)
    bid = Bid(
        gem_bid_id="GEM/2026/B/20004",
        title="Post-Quantum Cryptography Migration and Crypto-Agility Framework",
        scope_of_work="Implementation of post-quantum cryptography, crypto agility, and algorithm migration.",
        estimated_value=15000000.0,
        closing_date=now + timedelta(days=15),
    )
    db.add(bid)
    db.commit()

    matches = match_bid_against_products(db, bid)
    llm = DeterministicLLMProvider()
    intel = llm.analyze_bid(bid, matches)

    opp_analyzer = OpportunityAnalyzer()
    opp_result = opp_analyzer.analyze_opportunity(bid, intel)

    assert opp_result.relevance_score > 0.0
    assert 0.0 <= opp_result.opportunity_score <= 1.0
    assert opp_result.opportunity_label in ("HIGH_OPPORTUNITY", "MEDIUM_OPPORTUNITY", "LOW_OPPORTUNITY")
    assert len(opp_result.score_breakdown) == 4
    comp_names = [c.name for c in opp_result.score_breakdown]
    assert "Product Relevance" in comp_names
    assert "Contract Value Alignment" in comp_names
    assert "Eligibility Confidence" in comp_names
    assert "Deadline Feasibility" in comp_names


# ---------------------------------------------------------------------------
# Test 5: Relevant bid → notification
# ---------------------------------------------------------------------------
def test_relevant_bid_notification_trigger(db: Session):
    """Verify that a high-relevance bid triggers a pending notification with proper metadata."""
    bid = Bid(
        gem_bid_id="GEM/2026/B/20005",
        title="Decentralized Identity (DID) and Verifiable Credentials Issuance Platform",
        scope_of_work="W3C verifiable credentials issuance, identity wallet, and credential verification platform.",
        estimated_value=5000000.0,
    )
    db.add(bid)
    db.commit()

    res = process_bid_intelligence(db, bid, auto_notify=True)
    assert res["relevance_score"] >= 0.70
    assert res["match_state"] == "MATCH"
    assert res["notification_created"] is True

    notif = db.query(Notification).filter(Notification.bid_id == bid.id).first()
    assert notif is not None
    assert notif.notification_type == "NEW_HIGH_RELEVANCE"
    assert notif.channel == "EMAIL"
    assert notif.status == "PENDING"
    assert notif.deduplication_key == f"notif_{bid.id}_high_relevance"


# ---------------------------------------------------------------------------
# Test 6: Duplicate notification prevention
# ---------------------------------------------------------------------------
def test_duplicate_notification_prevention(db: Session):
    """Verify that re-processing a relevant bid does not generate duplicate notification records."""
    bid = Bid(
        gem_bid_id="GEM/2026/B/20006",
        title="Hardware-Backed Cryptographic Key Protection and HSM Management",
        scope_of_work="Cryptographic key protection, hardware-backed key protection, and HSM concepts.",
        estimated_value=8000000.0,
    )
    db.add(bid)
    db.commit()

    # First analysis pass
    res1 = process_bid_intelligence(db, bid, auto_notify=True)
    assert res1["notification_created"] is True
    notifs_count_1 = db.query(Notification).filter(Notification.bid_id == bid.id).count()
    assert notifs_count_1 == 1

    # Second analysis pass
    res2 = process_bid_intelligence(db, bid, auto_notify=True)
    assert res2["notification_created"] is False
    notifs_count_2 = db.query(Notification).filter(Notification.bid_id == bid.id).count()
    assert notifs_count_2 == 1, "Duplicate notification must not be created"


# ---------------------------------------------------------------------------
# Test 7: Human review workflow and auditability
# ---------------------------------------------------------------------------
def test_human_review_workflow_and_auditability(client: TestClient, db: Session):
    """Verify that reviewers can record decisions (RELEVANT, NOT_RELEVANT, MAYBE) and audit history."""
    bid = Bid(
        gem_bid_id="GEM/2026/B/20007",
        title="KYC/AML Identity Verification and Web3 Risk Scoring System",
        scope_of_work="KYC, AML, identity verification, and X-ID score risk assessment.",
    )
    db.add(bid)
    db.commit()

    # Step 1: Submit review
    r_rev = client.post(
        f"/api/v1/bids/{bid.id}/review",
        json={
            "relevance_decision": "RELEVANT",
            "pursue_decision": "PURSUE",
            "comments": "Exact match for SecureX-ID capability profile.",
        },
    )
    assert r_rev.status_code == 201
    rev_data = r_rev.json()
    assert rev_data["relevance_decision"] == "RELEVANT"
    assert rev_data["pursue_decision"] == "PURSUE"

    # Step 2: Audit history check
    r_hist = client.get(f"/api/v1/bids/{bid.id}/reviews")
    assert r_hist.status_code == 200
    reviews = r_hist.json()
    assert len(reviews) >= 1
    assert reviews[0]["comments"] == "Exact match for SecureX-ID capability profile."
    assert "reviewed_at" in reviews[0]


# ---------------------------------------------------------------------------
# Test 8: 1,000-bid synthetic batch processing
# ---------------------------------------------------------------------------
def test_1000_bid_synthetic_batch_pipeline(db: Session):
    """Verify that the batch pipeline correctly processes the 1,000 synthetic bids dataset."""
    dataset_path = "data/sample_bids/synthetic_1000_bids.json"
    if not os.path.exists(dataset_path):
        from app.scripts.generate_synthetic_bids import generate_synthetic_dataset
        generate_synthetic_dataset(dataset_path)

    with open(dataset_path, "r", encoding="utf-8") as f:
        content = f.read()

    summary = run_batch_intelligence_pipeline(
        db=db,
        file_content=content,
        file_type="json",
        source_name="synthetic_gem_dev_dataset",
        allow_update_duplicates=True,
        auto_notify=True,
    )

    assert summary.total_input_bids == 1000
    assert summary.successfully_processed == 1000
    assert summary.rejected == 0
    assert summary.relevant_matches > 0
    assert summary.no_match_records > 0
    assert summary.notifications_generated > 0
    assert summary.processing_time_seconds > 0.0
    assert summary.avg_time_per_bid_ms > 0.0


# ---------------------------------------------------------------------------
# Test 9: Multiple product candidates & differentiation rules
# ---------------------------------------------------------------------------
def test_product_differentiation_rules(db: Session):
    """Verify all 5 product differentiation rules."""
    # 1. SolidityShield vs AuditExpress
    bid_manual = Bid(
        title="Solidity Smart Contract Security Review with Expert Manual Review",
        scope_of_work="Automated vulnerability scanning, reentrancy detection, and expert review with auditor validation.",
    )
    db.add(bid_manual)
    db.commit()
    res_sol = match_bid_against_products(db, bid_manual)
    sol_score = next(r.relevance_score for r in res_sol if r.product_name == "SolidityShield")
    aud_score = next(r.relevance_score for r in res_sol if r.product_name == "AuditExpress")
    assert sol_score > aud_score, "SolidityShield must rank higher when expert/manual review is required"

    # 2. SecureTrace vs SecureWatch
    bid_trace = Bid(
        title="Blockchain Forensics and Transaction Tracing Investigation",
        scope_of_work="Blockchain investigation, wallet tracing, and fund flow analysis.",
    )
    db.add(bid_trace)
    db.commit()
    res_trc = match_bid_against_products(db, bid_trace)
    trc_score = next(r.relevance_score for r in res_trc if r.product_name == "SecureTrace")
    wtc_score = next(r.relevance_score for r in res_trc if r.product_name == "SecureWatch")
    assert trc_score > wtc_score, "SecureTrace must rank higher for post-event forensic tracing"

    # 3. SecureCMS vs CookieHub
    bid_cookie = Bid(
        title="Website Cookie Consent Banner and Tracking Script Management",
        scope_of_work="Cookie consent, tracking-script management, and script control.",
    )
    db.add(bid_cookie)
    db.commit()
    res_ckh = match_bid_against_products(db, bid_cookie)
    ckh_score = next(r.relevance_score for r in res_ckh if r.product_name == "CookieHub")
    cms_score = next(r.relevance_score for r in res_ckh if r.product_name == "SecureCMS")
    assert ckh_score > cms_score, "CookieHub must rank higher for website tracking scripts"

    # 4. SecureX-DID vs SecureX-ID
    bid_did = Bid(
        title="W3C Decentralized Identity DID and Verifiable Credentials",
        scope_of_work="Decentralized identity, W3C DID, verifiable credentials, and identity wallet.",
    )
    db.add(bid_did)
    db.commit()
    res_did = match_bid_against_products(db, bid_did)
    did_score = next(r.relevance_score for r in res_did if r.product_name == "SecureX-DID")
    xid_score = next(r.relevance_score for r in res_did if r.product_name == "SecureX-ID")
    assert did_score > xid_score, "SecureX-DID must rank higher for decentralized identity"

    # 5. PQCSuite vs QuantumVault
    bid_pqc = Bid(
        title="Post-Quantum Cryptography Migration and Crypto-Agility Framework",
        scope_of_work="Post-quantum cryptography, crypto agility, and cryptographic algorithm migration.",
    )
    db.add(bid_pqc)
    db.commit()
    res_pqc = match_bid_against_products(db, bid_pqc)
    pqc_score = next(r.relevance_score for r in res_pqc if r.product_name == "PQCSuite")
    qvt_score = next(r.relevance_score for r in res_pqc if r.product_name == "QuantumVault")
    assert pqc_score > qvt_score, "PQCSuite must rank higher for software crypto-agility"


# ---------------------------------------------------------------------------
# Test 10: No-match bid
# ---------------------------------------------------------------------------
def test_no_match_bid_classification(db: Session):
    """Verify that completely unrelated bids (e.g. office furniture / civil construction) score < 0.25 (NO_MATCH)."""
    bid = Bid(
        gem_bid_id="GEM/2026/B/20010",
        title="Supply and Installation of Ergonomic Modular Office Desks and Executive Chairs",
        scope_of_work="Supply and installation of wooden office workstations, chairs, and conference tables.",
        category="Office Supplies & Furniture",
    )
    db.add(bid)
    db.commit()

    results = match_bid_against_products(db, bid)
    top_match = results[0]
    assert top_match.relevance_score < 0.25
    assert top_match.match_state == "NO_MATCH"

    res = process_bid_intelligence(db, bid, auto_notify=True)
    assert res["relevance_score"] < 0.25
    assert res["match_state"] == "NO_MATCH"
    assert res["notification_created"] is False


# ---------------------------------------------------------------------------
# Test 11: Incomplete bid
# ---------------------------------------------------------------------------
def test_incomplete_bid_graceful_handling(db: Session):
    """Verify that bids with missing closing date, missing estimated value, or minimal text do not crash."""
    bid = Bid(
        gem_bid_id="GEM/2026/B/20011",
        title="Cybersecurity Advisory Notice",
        scope_of_work=None,
        closing_date=None,
        estimated_value=None,
        technical_requirements=None,
        eligibility_criteria=None,
    )
    db.add(bid)
    db.commit()

    res = process_bid_intelligence(db, bid, auto_notify=True)
    assert res["bid_id"] == str(bid.id)
    assert "opportunity_score" in res
    assert res["opportunity_score"] >= 0.0

    analysis = db.query(BidAnalysis).filter(BidAnalysis.bid_id == bid.id).first()
    assert analysis is not None
    score = db.query(BidScore).filter(BidScore.bid_id == bid.id).first()
    assert score is not None
    assert score.urgency == "UNKNOWN"


# ---------------------------------------------------------------------------
# Test 12: Updated bid
# ---------------------------------------------------------------------------
def test_updated_bid_handling(db: Session):
    """Verify that updating an existing bid (e.g. corrigendum extension) updates the DB record."""
    initial_payload = json.dumps([{
        "gem_bid_id": "GEM/2026/B/20012",
        "bid_number": "GEM-20012",
        "title": "Smart Contract Vulnerability Assessment",
        "scope_of_work": "Conducting Solidity security scan.",
        "closing_date": "2026-10-10T15:00:00Z",
    }])

    res1 = run_ingestion_pipeline(
        db=db,
        file_content=initial_payload,
        file_type="json",
        allow_update_duplicates=True,
    )
    assert res1.created == 1

    updated_payload = json.dumps([{
        "gem_bid_id": "GEM/2026/B/20012",
        "bid_number": "GEM-20012",
        "title": "Smart Contract Vulnerability Assessment [Corrigendum Extended]",
        "scope_of_work": "Conducting Solidity security scan with extended timeline.",
        "closing_date": "2026-11-15T15:00:00Z",
    }])

    res2 = run_ingestion_pipeline(
        db=db,
        file_content=updated_payload,
        file_type="json",
        allow_update_duplicates=True,
    )
    assert res2.updated == 1
    assert res2.duplicates == 1

    bid = db.query(Bid).filter(Bid.gem_bid_id == "GEM/2026/B/20012").first()
    assert bid is not None
    assert "Corrigendum" in bid.title


# ---------------------------------------------------------------------------
# Test 13: End-to-end pipeline
# ---------------------------------------------------------------------------
def test_end_to_end_pipeline(client: TestClient, db: Session):
    """
    Verify complete flow:
    Raw GeM JSON → ApprovedGeMAdapter → Validation → Normalization → DB Persistence
    → 11-product Matching → Differentiation → Requirement / Opportunity Analysis
    → Notification Generation → Human Review.
    """
    e2e_json = json.dumps([{
        "gem_bid_id": "GEM/2026/B/20013",
        "bid_number": "GEM-20013",
        "title": "Smart Contract Security Audit and Solidity Vulnerability Assessment",
        "organisation": "Defence Research and Development Organisation",
        "department": "Centre for AI & Robotics",
        "ministry": "Ministry of Defence",
        "category": "Cyber Security Consultancy",
        "published_date": "2026-09-20T10:00:00Z",
        "closing_date": "2026-11-25T15:00:00Z",
        "location": "Bengaluru",
        "estimated_value": 6000000.0,
        "currency": "INR",
        "scope_of_work": "Conducting automated security scanning, reentrancy detection, and expert security review for Solidity smart contracts.",
        "technical_requirements": {"certifications_required": ["ISO 27001", "CERT-In"]},
        "eligibility_criteria": {"prior_govt_projects": 3},
        "source_name": "synthetic_gem_dev_dataset",
        "source_url": "https://gem.gov.in/bids/GEM-20013",
    }])

    # 1. Ingestion & Analysis
    summary = run_batch_intelligence_pipeline(
        db=db,
        file_content=e2e_json,
        file_type="json",
        source_name="synthetic_gem_dev_dataset",
        allow_update_duplicates=True,
        auto_notify=True,
    )
    assert summary.total_input_bids == 1
    assert summary.relevant_matches == 1
    assert summary.notifications_generated == 1

    # 2. Inspect persisted bid & analysis
    bid = db.query(Bid).filter(Bid.gem_bid_id == "GEM/2026/B/20013").first()
    assert bid is not None

    r_analysis = client.get(f"/api/v1/bids/{bid.id}/analysis")
    assert r_analysis.status_code == 200
    analysis_data = r_analysis.json()
    assert analysis_data["analysis"] is not None
    assert analysis_data["score"] is not None
    assert analysis_data["score"]["relevance_score"] >= 0.70

    # 3. Notification log check
    r_notifs = client.get("/api/v1/notifications")
    assert r_notifs.status_code == 200
    notifs = r_notifs.json()
    assert any(n["bid_id"] == str(bid.id) for n in notifs)

    # 4. Human Review submission
    r_review = client.post(
        f"/api/v1/bids/{bid.id}/review",
        json={
            "relevance_decision": "RELEVANT",
            "pursue_decision": "PURSUE",
            "comments": "High strategic alignment with SolidityShield.",
        },
    )
    assert r_review.status_code == 201


# ---------------------------------------------------------------------------
# Test 14: Product-match persistence via process_bid_intelligence
# ---------------------------------------------------------------------------
def test_product_match_persistence_via_process_bid_intelligence(db):
    """Verify that process_bid_intelligence persists BidProductMatch rows."""
    bid = Bid(
        gem_bid_id="GEM/2026/B/20050",
        title="Solidity Smart Contract Security Audit and Vulnerability Detection",
        scope_of_work="Automated vulnerability scanning, reentrancy detection, and expert security review for EVM contracts.",
        category="Cyber Security",
    )
    db.add(bid)
    db.commit()

    res = process_bid_intelligence(db, bid, auto_notify=False, commit=False)
    db.commit()

    # BidProductMatch rows must exist for positively classified matches
    matches = db.query(BidProductMatch).filter(BidProductMatch.bid_id == bid.id).all()
    assert len(matches) >= 1, "At least one product match row must be persisted"

    # Check the top match is persisted correctly
    top_match = [m for m in matches if m.match_score > 0]
    assert len(top_match) >= 1
    solidity_match = [m for m in top_match if m.product.name == "SolidityShield"]
    assert len(solidity_match) == 1
    assert solidity_match[0].match_score >= 0.70
    assert solidity_match[0].match_type == "DETERMINISTIC_PHASE3"
    assert solidity_match[0].evidence is not None
    assert "match_state" in solidity_match[0].evidence


# ---------------------------------------------------------------------------
# Test 15: Repeated analysis deduplication
# ---------------------------------------------------------------------------
def test_repeated_analysis_deduplicates_product_matches(db):
    """Verify that re-processing a bid does not create duplicate BidProductMatch rows."""
    bid = Bid(
        gem_bid_id="GEM/2026/B/20051",
        title="Hardware-Backed Cryptographic Key Protection and HSM Management",
        scope_of_work="Cryptographic key protection, hardware-backed key protection, and HSM concepts.",
        estimated_value=8000000.0,
    )
    db.add(bid)
    db.commit()

    # First analysis pass
    process_bid_intelligence(db, bid, auto_notify=False, commit=False)
    db.commit()
    matches_after_first = db.query(BidProductMatch).filter(BidProductMatch.bid_id == bid.id).all()
    count_after_first = len(matches_after_first)

    # Second analysis pass
    process_bid_intelligence(db, bid, auto_notify=False, commit=False)
    db.commit()
    matches_after_second = db.query(BidProductMatch).filter(BidProductMatch.bid_id == bid.id).all()
    count_after_second = len(matches_after_second)

    assert count_after_first == count_after_second, (
        f"Duplicate match rows: {count_after_first} vs {count_after_second}"
    )


# ---------------------------------------------------------------------------
# Test 16: Security keyword improvement - vulnerability scanner matches SolidityShield
# ---------------------------------------------------------------------------
def test_vulnerability_scanner_keyword_matches_solidityshield(db):
    """Verify that 'vulnerability scanner' keyword matches SolidityShield for real GeM bids."""
    bid = Bid(
        gem_bid_id="GEM/2026/B/7966311",
        title="Network Vulnerability Scanner Software (Nesus Pro) 2 years license",
        organisation="Ministry of Defence Department of Military Affairs",
        source_url="https://bidplus.gem.gov.in/showbidDocument/9812121",
    )
    db.add(bid)
    db.commit()

    results = match_bid_against_products(db, bid)
    solidity_result = next((r for r in results if r.product_name == "SolidityShield"), None)

    assert solidity_result is not None, "SolidityShield must be evaluated"
    assert solidity_result.relevance_score > 0, (
        "SolidityShield must score > 0 for vulnerability scanner bid"
    )

    # SolidityShield is a smart-contract security product. A general network
    # vulnerability scanner has no smart-contract domain anchor, so it is
    # domain-gated to NEEDS_REVIEW (never auto-matched). AuditExpress is the
    # correct product for general vulnerability scanning.
    assert solidity_result.match_state == "NEEDS_REVIEW"
    assert solidity_result.relevance_score == 0.3999
    assert solidity_result.score_breakdown.get("domain_gate") == "NO_DOMAIN_ANCHOR"

    # Verify the signal is "vulnerability scanner" in title
    title_signals = [s for s in solidity_result.signals if s.get("field") == "title"]
    assert len(title_signals) >= 1
    scanner_signal = [s for s in title_signals if "vulnerability" in s.get("text", "").lower()]
    assert len(scanner_signal) >= 1, "Must match 'vulnerability scanner' signal in title"


# ---------------------------------------------------------------------------
# Test 17: Firewall bid remains unmatched (no product offers firewall capability)
# ---------------------------------------------------------------------------
def test_firewall_bid_remains_unmatched(db):
    """Verify that firewall bids score 0.0 since no product offers firewall capability."""
    bid = Bid(
        gem_bid_id="GEM/2026/B/8194255",
        title="FIREWALL 100 USER VALID FOR 3 YEARS SUBSCRIPTION",
        organisation="Ministry of Chemicals and Fertilizers Department of Chemicals and Petrochemicals",
        source_url="https://bidplus.gem.gov.in/showbidDocument/10073641",
    )
    db.add(bid)
    db.commit()

    results = match_bid_against_products(db, bid)
    for r in results:
        assert r.relevance_score == 0.0, (
            f"{r.product_name} should score 0.0 for firewall bid, got {r.relevance_score}"
        )
        assert r.match_state == "NO_MATCH"


# ---------------------------------------------------------------------------
# Test 18: Unrelated bids remain unmatched after keyword addition
# ---------------------------------------------------------------------------
def test_unrelated_bids_still_unmatched(db):
    """Verify that adding vulnerability scanner keyword does not create false positives."""
    unrelated_titles = [
        "Saree,Saree,Saree,Peticoat,Chunari,Pant Clothes",
        "Shell & Tube Heat Exchanger",
        "Target Face - Shooting",
        "Nails for wooden work",
    ]

    for title in unrelated_titles:
        bid = Bid(
            gem_bid_id=f"TEST/{title[:20].replace(' ', '_')}",
            title=title,
            scope_of_work=title,
        )
        db.add(bid)
        db.commit()

        results = match_bid_against_products(db, bid)
        non_zero = [r for r in results if r.relevance_score > 0]
        assert len(non_zero) == 0, (
            f"Unrelated bid '{title}' should not match any product, got {len(non_zero)} matches"
        )

        # Clean up
        db.query(Bid).filter(Bid.gem_bid_id == bid.gem_bid_id).delete()
        db.commit()
