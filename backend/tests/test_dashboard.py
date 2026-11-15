"""
Dashboard summary endpoint tests.

The dashboard must only ever surface real persisted data. These tests assert
that figures are derived from `bids` / `bid_scores` / `notifications`, and that
bids which have not been analyzed are reported honestly instead of being given
a fabricated score.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.db.seed_knowledge import seed_product_knowledge
from app.models.bid import Bid
from app.services.intelligence import process_bid_intelligence


def _make_bid(db, **kwargs) -> Bid:
    bid = Bid(**kwargs)
    db.add(bid)
    db.commit()
    return bid


def test_summary_reports_zero_state_for_empty_database(client, db):
    res = client.get("/api/v1/dashboard/summary")
    assert res.status_code == 200
    body = res.json()

    metrics = body["metrics"]
    assert metrics["total_bids"] == 0
    assert metrics["relevant_bids"] == 0
    assert metrics["needs_review_bids"] == 0
    assert metrics["closing_soon_bids"] == 0
    assert metrics["notifications"] == 0

    assert body["priority_opportunities"] == []
    assert body["possible_matches"] == []
    assert body["recent_bids"] == []
    assert body["action_required"] == []
    assert body["recent_activity"] == []


def test_unanalyzed_bids_have_no_fabricated_score(client, db):
    _make_bid(
        db,
        title="Smart Contract Security Audit and Solidity Vulnerability Scan",
        scope_of_work="Expert review of Solidity smart contracts.",
    )

    body = client.get("/api/v1/dashboard/summary").json()
    assert body["metrics"]["total_bids"] == 1
    assert body["metrics"]["analyzed_bids"] == 0
    assert body["metrics"]["pending_analysis"] == 1
    assert body["metrics"]["relevant_bids"] == 0

    row = body["recent_bids"][0]
    assert row["analyzed"] is False
    assert row["relevance_score"] is None
    assert row["opportunity_score"] is None
    assert row["matched_product"] is None
    assert row["relevance_label"] is None


def test_metrics_reflect_real_analysis_results(client, db):
    seed_product_knowledge(db)

    relevant_bid = _make_bid(
        db,
        title="Solidity Smart Contract Security Audit with Manual Expert Review",
        scope_of_work="Automated scanning plus expert security review and auditor validation of Solidity findings.",
        estimated_value=5_000_000.0,
        closing_date=datetime.now(timezone.utc) + timedelta(days=10),
    )
    civil_bid = _make_bid(
        db,
        title="Supply of Ergonomic Office Chairs and Wooden Desks",
        scope_of_work="Supply and installation of office furniture.",
    )

    process_bid_intelligence(db, relevant_bid, auto_notify=True)
    process_bid_intelligence(db, civil_bid, auto_notify=True)

    body = client.get("/api/v1/dashboard/summary").json()
    metrics = body["metrics"]

    assert metrics["total_bids"] == 2
    assert metrics["analyzed_bids"] == 2
    assert metrics["pending_analysis"] == 0
    assert metrics["relevant_bids"] == 1
    assert metrics["notifications"] == 1

    # No hardcoded figures: the numbers must come from the stored scores.
    from app.models.analysis import BidScore

    stored_relevant = db.query(BidScore).filter(BidScore.bid_id == relevant_bid.id).first()
    assert metrics["relevant_bids"] == 1
    assert stored_relevant.relevance_score >= 0.70

    opportunity = body["priority_opportunities"][0]
    assert opportunity["id"] == str(relevant_bid.id)
    assert opportunity["analyzed"] is True
    assert opportunity["relevance_score"] is not None
    assert opportunity["relevance_score"] >= 0.70
    assert opportunity["opportunity_score"] is not None
    assert opportunity["matched_product"] == "SolidityShield"
    assert opportunity["days_remaining"] is not None


def test_possible_matches_surface_a_possible_match_bid(client, db):
    """A POSSIBLE_MATCH bid must have its own dashboard list.

    Such a bid is below the MATCH band, so it is correctly excluded from
    ``priority_opportunities``; without ``possible_matches`` it would have no
    entry point on the dashboard at all (unless it happened to be recent or
    closing soon).
    """
    from app.models.analysis import BidAnalysis, BidScore

    bid = _make_bid(
        db,
        title="Telegram Group Monitoring Intelligence De anonymization software",
        scope_of_work="Cryptocurrency transaction tracing and blockchain intelligence analysis.",
    )
    analysis_id = str(uuid4())
    db.add(BidAnalysis(id=analysis_id, bid_id=bid.id, engine_version="test", model_used="test"))
    db.add(
        BidScore(
            bid_id=bid.id,
            analysis_id=analysis_id,
            relevance_score=0.667,
            opportunity_score=0.628,
            relevance_label="POSSIBLE_MATCH",
            urgency="NORMAL",
            score_breakdown={
                "highest_product_match": {
                    "product_name": "SecureTrace",
                    "match_state": "POSSIBLE_MATCH",
                }
            },
        )
    )
    db.commit()

    body = client.get("/api/v1/dashboard/summary").json()

    assert body["metrics"]["possible_match_bids"] == 1
    assert body["metrics"]["relevant_bids"] == 0

    # Not a MATCH-band bid, so it stays out of the relevant list...
    assert body["priority_opportunities"] == []
    # ...but it is surfaced as a real possible match, with its product and score.
    assert [row["id"] for row in body["possible_matches"]] == [str(bid.id)]
    row = body["possible_matches"][0]
    assert row["matched_product"] == "SecureTrace"
    assert row["match_state"] == "POSSIBLE_MATCH"
    assert row["relevance_score"] == 0.667


def test_closing_soon_counts_real_deadlines(client, db):
    now = datetime.now(timezone.utc)
    _make_bid(db, title="Closing very soon", closing_date=now + timedelta(days=2))
    _make_bid(db, title="Closing later", closing_date=now + timedelta(days=40))
    _make_bid(db, title="Already closed", closing_date=now - timedelta(days=3))
    _make_bid(db, title="No deadline supplied")

    body = client.get("/api/v1/dashboard/summary").json()
    assert body["metrics"]["closing_soon_bids"] == 1

    titles = [row["title"] for row in body["action_required"]]
    assert titles == ["Closing very soon"]

    statuses = {row["title"]: row["deadline_status"] for row in body["recent_bids"]}
    assert statuses["Already closed"] == "CLOSED"
    assert statuses["No deadline supplied"] == "UNKNOWN"


def test_priority_opportunities_exclude_unanalyzed_bids(client, db):
    _make_bid(
        db,
        title="Solidity Smart Contract Security Audit with Manual Expert Review",
        scope_of_work="Expert security review of Solidity smart contracts.",
    )
    body = client.get("/api/v1/dashboard/summary").json()
    # Nothing was analyzed, so there is no scored opportunity to rank.
    assert body["priority_opportunities"] == []


def test_recent_activity_uses_real_notification_records(client, db):
    seed_product_knowledge(db)
    bid = _make_bid(
        db,
        title="W3C Decentralized Identity and Verifiable Credentials Issuance System",
        scope_of_work="Verifiable credential issuance, storage, presentation and verification.",
        estimated_value=8_000_000.0,
    )
    process_bid_intelligence(db, bid, auto_notify=True)

    body = client.get("/api/v1/dashboard/summary").json()
    assert len(body["recent_activity"]) == 1

    activity = body["recent_activity"][0]
    assert activity["bid_id"] == str(bid.id)
    assert activity["bid_title"] == bid.title
    assert activity["notification_type"] == "NEW_HIGH_RELEVANCE"
    assert activity["status"] == "PENDING"


def test_relevant_bids_respect_configured_threshold(client, db, monkeypatch):
    """A configured 0.5 cutoff must surface a 0.55 bid as relevant.

    Previously the dashboard applied its own hardcoded 0.70 band, so a
    threshold deployment showed an engine MATCH as merely "possible".
    """
    from app.core.config import settings
    from app.models.analysis import BidAnalysis, BidScore

    monkeypatch.setattr(settings, "MATCHING_RELEVANCE_THRESHOLD", 0.5)

    bid = _make_bid(db, title="Borderline relevance bid")
    analysis_id = str(uuid4())
    db.add(
        BidAnalysis(id=analysis_id, bid_id=bid.id, engine_version="test", model_used="test")
    )
    db.add(
        BidScore(
            bid_id=bid.id,
            analysis_id=analysis_id,
            relevance_score=0.55,
            opportunity_score=0.40,
            relevance_label="MATCH",
            urgency="NORMAL",
        )
    )
    db.commit()

    metrics = client.get("/api/v1/dashboard/summary").json()["metrics"]
    assert metrics["relevant_bids"] == 1
    assert metrics["possible_match_bids"] == 0


def test_needs_review_count_comes_from_backend_thresholds(client, db):
    from app.models.analysis import BidAnalysis, BidScore

    bid = _make_bid(db, title="Peripheral IT security advisory", scope_of_work="General advisory notice.")

    # A score sitting in the NEEDS_REVIEW band as defined by the engine.
    analysis_id = str(uuid4())
    db.add(
        BidAnalysis(
            id=analysis_id,
            bid_id=bid.id,
            engine_version="test",
            model_used="test",
        )
    )
    db.add(
        BidScore(
            bid_id=bid.id,
            analysis_id=analysis_id,
            relevance_score=0.30,
            opportunity_score=0.20,
            relevance_label="NEEDS_REVIEW",
            urgency="NORMAL",
        )
    )
    db.commit()

    body = client.get("/api/v1/dashboard/summary").json()
    assert body["metrics"]["needs_review_bids"] == 1
    assert body["metrics"]["relevant_bids"] == 0


def test_bid_intelligence_feed_returns_every_bid_without_a_row_cap(client, db):
    """
    The feed must never hide rows behind a hardcoded maximum. Bids are the
    system's primary dataset, so volume is governed by the data itself.
    """
    for index in range(150):
        _make_bid(db, title=f"Bulk tender {index:03d}", category=f"Category {index % 7}")

    body = client.get("/api/v1/bids/intelligence").json()

    assert body["total"] == 150
    assert len(body["bids"]) == 150
    assert {row["title"] for row in body["bids"]} == {f"Bulk tender {i:03d}" for i in range(150)}


def test_bid_intelligence_feed_never_invents_scores(client, db):
    seed_product_knowledge(db)
    analyzed = _make_bid(
        db,
        title="Solidity Smart Contract Security Audit with Manual Expert Review",
        scope_of_work="Expert security review and auditor validation of Solidity findings.",
    )
    unanalyzed = _make_bid(
        db,
        title="Supply of Ergonomic Office Chairs and Wooden Desks",
        scope_of_work="Supply and installation of office furniture.",
    )
    process_bid_intelligence(db, analyzed, auto_notify=False)

    rows = {row["id"]: row for row in client.get("/api/v1/bids/intelligence").json()["bids"]}

    scored = rows[str(analyzed.id)]
    assert scored["analyzed"] is True
    assert scored["relevance_score"] is not None
    assert scored["relevance_score"] >= 0.70
    assert scored["match_state"] == "MATCH"
    assert scored["matched_product"] == "SolidityShield"

    # A bid the pipeline has not seen must not receive a guess in the feed.
    blank = rows[str(unanalyzed.id)]
    assert blank["analyzed"] is False
    assert blank["relevance_score"] is None
    assert blank["opportunity_score"] is None
    assert blank["matched_product"] is None
    assert blank["match_state"] is None
    assert blank["urgency"] is None


def test_no_match_bid_never_reports_a_product(client, db):
    """
    A NO_MATCH bid must not be credited with a product.

    The matching engine ranks *every* active product, so when nothing matches all
    of them score 0.0 and the top-ranked candidate is simply the first row of the
    catalogue. Persisting that candidate is fine, but reporting it as the bid's
    product match would present an arbitrary product (e.g. SolidityShield) as a
    real match. The feed must instead say there is no relevant product.
    """
    seed_product_knowledge(db)
    irrelevant = _make_bid(
        db,
        title="Supply of Ergonomic Office Chairs and Wooden Desks",
        scope_of_work="Supply and installation of office furniture.",
        estimated_value=1_200_000.0,
    )
    process_bid_intelligence(db, irrelevant, auto_notify=False)

    row = {r["id"]: r for r in client.get("/api/v1/bids/intelligence").json()["bids"]}[
        str(irrelevant.id)
    ]

    assert row["analyzed"] is True
    assert row["match_state"] == "NO_MATCH"
    assert row["matched_product"] is None
    # Real persisted scores are still reported for an analyzed bid.
    assert row["relevance_score"] is not None
    assert row["opportunity_score"] is not None

    # The pipeline did evaluate a top candidate, it just must not leak through.
    from app.models.analysis import BidScore

    stored = db.query(BidScore).filter(BidScore.bid_id == irrelevant.id).first()
    highest = stored.score_breakdown["highest_product_match"]
    assert highest["product_name"] is not None
    assert highest["match_state"] == "NO_MATCH"


def test_match_state_always_drives_whether_a_product_is_reported():
    """
    Unit-level: the persisted match state alone decides whether a product name is
    reported. MATCH / POSSIBLE_MATCH / NEEDS_REVIEW report their product; NO_MATCH
    and an absent state report none.
    """
    from app.models.analysis import BidScore
    from app.services.bid_views import MATCHED_STATES, serialise_bid

    bid = Bid(id=uuid4(), title="Bid with an explicitly persisted match state")

    for state in ("MATCH", "POSSIBLE_MATCH", "NEEDS_REVIEW", "NO_MATCH", None, "SOMETHING_NEW"):
        score = BidScore(
            id=uuid4(),
            bid_id=bid.id,
            analysis_id=uuid4(),
            relevance_score=0.9 if state in MATCHED_STATES else 0.0,
            opportunity_score=0.4,
            relevance_label=state or "UNMATCHED",
            urgency="NORMAL",
            score_breakdown={
                "highest_product_match": {
                    "product_name": "SolidityShield",
                    "match_state": state,
                }
            },
        )
        row = serialise_bid(bid, score)
        assert row["match_state"] == state
        if state in MATCHED_STATES:
            assert row["matched_product"] == "SolidityShield", state
        else:
            assert row["matched_product"] is None, state


def test_bid_intelligence_feed_is_ordered_newest_published_first(client, db):
    older = _make_bid(
        db,
        title="Older notice",
        published_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    newer = _make_bid(
        db,
        title="Newer notice",
        published_date=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )
    assert older.id and newer.id

    rows = client.get("/api/v1/bids/intelligence").json()["bids"]
    assert [row["title"] for row in rows] == ["Newer notice", "Older notice"]


def test_list_bids_returns_the_full_dataset(client, db):
    for index in range(120):
        _make_bid(db, title=f"Notice {index:03d}")

    res = client.get("/api/v1/bids")
    assert res.status_code == 200
    assert len(res.json()) == 120


# ---------------------------------------------------------------------------
# Closed-bid exclusion tests
# ---------------------------------------------------------------------------
def test_closed_bids_excluded_from_dashboard_counts(client, db):
    """Closed bids (past closing_date) must not inflate active dashboard counts."""
    now = datetime.now(timezone.utc)
    # Open bids
    _make_bid(db, title="Open bid 1", closing_date=now + timedelta(days=10))
    _make_bid(db, title="Open bid 2", closing_date=now + timedelta(days=20))
    # Closed bid
    _make_bid(db, title="Closed bid", closing_date=now - timedelta(days=3))
    # No deadline = not closed
    _make_bid(db, title="No deadline")

    body = client.get("/api/v1/dashboard/summary").json()
    metrics = body["metrics"]

    # total_bids counts ALL bids (2 open + 1 closed + 1 no-deadline = 4)
    assert metrics["total_bids"] == 4
    # closed_bids is tracked separately
    assert metrics["closed_bids"] == 1
    # analyzed_bids counts only open analyzed bids
    assert metrics["analyzed_bids"] == 0
    # pending_analysis is open minus analyzed
    assert metrics["pending_analysis"] == 3


def test_closed_bids_excluded_from_active_lists(client, db):
    """Closed bids must not appear in priority_opportunities, possible_matches,
    or action_required."""
    from app.models.analysis import BidAnalysis, BidScore

    now = datetime.now(timezone.utc)
    # Relevant open bid
    relevant = _make_bid(
        db,
        title="Relevant open bid",
        scope_of_work="Solidity smart contract audit with expert review.",
        closing_date=now + timedelta(days=10),
    )
    # Closed but relevant-scored bid
    closed_relevant = _make_bid(
        db,
        title="Closed but relevant bid",
        scope_of_work="Solidity smart contract audit with expert review.",
        closing_date=now - timedelta(days=1),
    )

    process_bid_intelligence(db, relevant, auto_notify=False)
    process_bid_intelligence(db, closed_relevant, auto_notify=False)

    body = client.get("/api/v1/dashboard/summary").json()

    # Only the open relevant bid appears in priority_opportunities
    opp_ids = [row["id"] for row in body["priority_opportunities"]]
    assert str(relevant.id) in opp_ids
    assert str(closed_relevant.id) not in opp_ids

    # Only the open relevant bid is counted as relevant
    assert body["metrics"]["relevant_bids"] == 1

    # Closed bid must not appear in possible_matches or action_required
    possible_ids = [row["id"] for row in body["possible_matches"]]
    assert str(closed_relevant.id) not in possible_ids
    action_ids = [row["id"] for row in body["action_required"]]
    assert str(closed_relevant.id) not in action_ids


def test_closed_bids_still_appear_in_recent_bids(client, db):
    """Closed bids appear in recent_bids (historical activity) with CLOSED
    deadline_status, but are excluded from active counts and lists."""
    now = datetime.now(timezone.utc)
    _make_bid(db, title="Open bid", closing_date=now + timedelta(days=10))
    _make_bid(db, title="Closed bid", closing_date=now - timedelta(days=3))
    _make_bid(db, title="No deadline bid")

    body = client.get("/api/v1/dashboard/summary").json()

    # recent_bids includes ALL bids including closed ones
    recent_titles = [row["title"] for row in body["recent_bids"]]
    assert "Closed bid" in recent_titles
    assert "Open bid" in recent_titles
    assert "No deadline bid" in recent_titles

    # Closed bid shows its CLOSED status
    statuses = {row["title"]: row["deadline_status"] for row in body["recent_bids"]}
    assert statuses["Closed bid"] == "CLOSED"
    assert statuses["No deadline bid"] == "UNKNOWN"


def test_closed_bids_excluded_from_dashboard_notifications(client, db):
    """Closed bids must not appear in recent_activity notification feed."""
    from app.models.analysis import BidAnalysis, BidScore

    now = datetime.now(timezone.utc)
    # Open high-relevance bid → generates notification
    open_bid = _make_bid(
        db,
        title="Open high-relevance bid",
        scope_of_work="Solidity smart contract audit with expert review.",
        estimated_value=5_000_000.0,
        closing_date=now + timedelta(days=10),
    )
    # Closed high-relevance bid → must NOT generate notification
    closed_bid = _make_bid(
        db,
        title="Closed high-relevance bid",
        scope_of_work="Solidity smart contract audit with expert review.",
        estimated_value=5_000_000.0,
        closing_date=now - timedelta(days=1),
    )

    process_bid_intelligence(db, open_bid, auto_notify=True)
    process_bid_intelligence(db, closed_bid, auto_notify=True)

    body = client.get("/api/v1/dashboard/summary").json()

    # Only the open bid's notification appears in recent_activity
    activity_ids = [a["bid_id"] for body_item in [body] for a in body_item["recent_activity"]]
    assert str(open_bid.id) in activity_ids
    assert str(closed_bid.id) not in activity_ids


def test_list_bids_excludes_closed_by_default(client, db):
    """list_bids excludes closed bids unless include_closed=true."""
    now = datetime.now(timezone.utc)
    _make_bid(db, title="Open bid", closing_date=now + timedelta(days=10))
    _make_bid(db, title="Closed bid", closing_date=now - timedelta(days=3))

    # Default: closed excluded
    res = client.get("/api/v1/bids")
    assert res.status_code == 200
    titles = [b["title"] for b in res.json()]
    assert "Open bid" in titles
    assert "Closed bid" not in titles

    # include_closed=true: all bids returned
    res = client.get("/api/v1/bids?include_closed=true")
    assert res.status_code == 200
    titles = [b["title"] for b in res.json()]
    assert "Open bid" in titles
    assert "Closed bid" in titles


def test_list_bid_intelligence_excludes_closed_by_default(client, db):
    """list_bid_intelligence excludes closed bids unless include_closed=true."""
    now = datetime.now(timezone.utc)
    _make_bid(db, title="Open bid", closing_date=now + timedelta(days=10))
    _make_bid(db, title="Closed bid", closing_date=now - timedelta(days=3))

    # Default: closed excluded
    res = client.get("/api/v1/bids/intelligence")
    assert res.status_code == 200
    data = res.json()
    titles = [b["title"] for b in data["bids"]]
    assert "Open bid" in titles
    assert "Closed bid" not in titles

    # include_closed=true: all bids returned
    res = client.get("/api/v1/bids/intelligence?include_closed=true")
    assert res.status_code == 200
    data = res.json()
    titles = [b["title"] for b in data["bids"]]
    assert "Open bid" in titles
    assert "Closed bid" in titles
