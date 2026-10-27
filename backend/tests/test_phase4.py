"""
Tests for Phase 4: Bid Intelligence, Requirement Extraction, Eligibility Analysis,
Opportunity Scoring, Human Review Workflow, Notifications, and Analytics Evaluation.
"""
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from app.models.bid import Bid
from app.models.analysis import BidScore, BidAnalysis
from app.models.notification import Notification
from app.services.intelligence import (
    DeterministicLLMProvider,
    OpportunityAnalyzer,
    match_bid_against_products,
)


def test_deadline_intelligence_calculation(db):
    now = datetime.now(timezone.utc)
    llm = DeterministicLLMProvider()

    # Normal (> 14 days)
    bid_normal = Bid(title="Normal Bid", closing_date=now + timedelta(days=20))
    d_normal = llm._calculate_deadline_intelligence(bid_normal, now)
    assert d_normal.status == "NORMAL"

    # Upcoming (8-14 days)
    bid_upcoming = Bid(title="Upcoming Bid", closing_date=now + timedelta(days=10))
    d_upcoming = llm._calculate_deadline_intelligence(bid_upcoming, now)
    assert d_upcoming.status == "UPCOMING"

    # Urgent (4-7 days)
    bid_urgent = Bid(title="Urgent Bid", closing_date=now + timedelta(days=5))
    d_urgent = llm._calculate_deadline_intelligence(bid_urgent, now)
    assert d_urgent.status == "URGENT"

    # Closing Soon (<= 3 days)
    bid_soon = Bid(title="Closing Soon Bid", closing_date=now + timedelta(days=2))
    d_soon = llm._calculate_deadline_intelligence(bid_soon, now)
    assert d_soon.status == "CLOSING_SOON"

    # Closed (< 0 days)
    bid_closed = Bid(title="Closed Bid", closing_date=now - timedelta(days=1))
    d_closed = llm._calculate_deadline_intelligence(bid_closed, now)
    assert d_closed.status == "CLOSED"

    # Unknown (missing closing date)
    bid_unknown = Bid(title="Unknown Bid", closing_date=None)
    d_unknown = llm._calculate_deadline_intelligence(bid_unknown, now)
    assert d_unknown.status == "UNKNOWN"


def test_opportunity_scoring_separation(db):
    bid = Bid(
        title="Post-Quantum Cryptography Migration",
        scope_of_work="Implement PQCSuite cryptographic agility layer and post-quantum migration.",
        estimated_value="50000000",  # 5 Cr
        closing_date=datetime.now(timezone.utc) + timedelta(days=25),
    )
    db.add(bid)
    db.commit()

    matches = match_bid_against_products(db, bid)
    llm = DeterministicLLMProvider()
    intel = llm.analyze_bid(bid, matches)

    opp_analyzer = OpportunityAnalyzer()
    opp_result = opp_analyzer.analyze_opportunity(bid, intel)

    assert opp_result.relevance_score != opp_result.opportunity_score or opp_result.opportunity_score > 0
    assert len(opp_result.score_breakdown) == 4
    assert opp_result.opportunity_label in ("HIGH_OPPORTUNITY", "MEDIUM_OPPORTUNITY")


def test_full_analysis_api_endpoint(client: TestClient, db):
    bid = Bid(
        title="Solidity Smart Contract Audit and Security Assessment",
        scope_of_work="Comprehensive vulnerability scanning, reentrancy detection, and expert review.",
        estimated_value="2500000",
        closing_date=datetime.now(timezone.utc) + timedelta(days=12),
    )
    db.add(bid)
    db.commit()

    r = client.post(f"/api/v1/bids/{bid.id}/analyze")
    assert r.status_code == 200
    data = r.json()
    assert data["bid_id"] == str(bid.id)
    assert "intelligence" in data
    assert "opportunity" in data

    # Check database persistence
    score = db.query(BidScore).filter(BidScore.bid_id == bid.id).first()
    assert score is not None
    assert score.relevance_score >= 0.70

    notif = db.query(Notification).filter(Notification.bid_id == bid.id).first()
    assert notif is not None
    assert notif.notification_type == "NEW_HIGH_RELEVANCE"


def test_human_review_and_evaluation_analytics(client: TestClient, db):
    bid = Bid(
        title="Decentralized Identity (DID) Platform Implementation",
        scope_of_work="W3C verifiable credentials issuance, identity wallet, and credential verification.",
    )
    db.add(bid)
    db.commit()

    # Analyze first
    client.post(f"/api/v1/bids/{bid.id}/analyze")

    # Submit Human Review
    r_rev = client.post(
        f"/api/v1/bids/{bid.id}/review",
        json={"relevance_decision": "RELEVANT", "pursue_decision": "PURSUE", "comments": "Good technical fit for SecureX-DID."}
    )
    assert r_rev.status_code == 201
    rev_data = r_rev.json()
    assert rev_data["relevance_decision"] == "RELEVANT"

    # Query reviews history
    r_hist = client.get(f"/api/v1/bids/{bid.id}/reviews")
    assert r_hist.status_code == 200
    assert len(r_hist.json()) >= 1

    # Check evaluation metrics API
    r_eval = client.get("/api/v1/analytics/evaluation")
    assert r_eval.status_code == 200
    eval_data = r_eval.json()
    assert eval_data["total_evaluated_reviews"] >= 1
    assert eval_data["precision"] > 0
