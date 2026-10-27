"""
Focused tests for matching-accuracy evaluation.

They pin the label-validity rules: only RELEVANT / NOT_RELEVANT count, MAYBE is
excluded, duplicate reviews collapse to the latest per bid, unscored bids are
excluded, and a small sample is explicitly flagged as an unmeasured accuracy.
"""
from datetime import datetime, timedelta, timezone

from app.models.analysis import BidAnalysis, BidScore
from app.models.bid import Bid
from app.models.review import HumanReview
from app.services.matching_evaluation import (
    MIN_LABELS_FOR_ACCURACY,
    evaluate_matching,
)


def _scored_bid(db, score_value: float) -> Bid:
    bid = Bid(title=f"Bid {score_value}")
    db.add(bid)
    db.flush()
    analysis = BidAnalysis(bid_id=bid.id, engine_version="test")
    db.add(analysis)
    db.flush()
    db.add(
        BidScore(
            bid_id=bid.id,
            analysis_id=analysis.id,
            relevance_score=score_value,
            opportunity_score=score_value,
            relevance_label="MATCH" if score_value >= 0.70 else "NO_MATCH",
            urgency="NORMAL",
        )
    )
    db.flush()
    return bid


def _review(db, bid, decision, when):
    db.add(
        HumanReview(
            bid_id=bid.id,
            relevance_decision=decision,
            pursue_decision="PENDING",
            reviewed_at=when,
        )
    )
    db.flush()


def test_confusion_matrix_and_f1(db):
    t0 = datetime.now(timezone.utc)
    # TP: human RELEVANT, engine MATCH (>= 0.70)
    _review(db, _scored_bid(db, 0.90), "RELEVANT", t0)
    # FP: human NOT_RELEVANT, engine MATCH
    _review(db, _scored_bid(db, 0.80), "NOT_RELEVANT", t0)
    # FN: human RELEVANT, engine NO_MATCH
    _review(db, _scored_bid(db, 0.00), "RELEVANT", t0)
    # TN: human NOT_RELEVANT, engine NO_MATCH
    _review(db, _scored_bid(db, 0.10), "NOT_RELEVANT", t0)
    db.commit()

    report = evaluate_matching(db)
    assert report["true_positives"] == 1
    assert report["false_positives"] == 1
    assert report["false_negatives"] == 1
    assert report["true_negatives"] == 1
    assert report["total_evaluated_reviews"] == 4
    assert report["precision"] == 0.5      # 1 / (1+1)
    assert report["recall"] == 0.5         # 1 / (1+1)
    assert report["f1_score"] == 0.5
    assert report["agreement_rate"] == 0.5  # 2 / 4
    # 4 < 30, so accuracy must be reported as unmeasured.
    assert report["sufficient_for_accuracy"] is False
    assert report["accuracy_measured"] is False


def test_maybe_label_is_excluded(db):
    t0 = datetime.now(timezone.utc)
    _review(db, _scored_bid(db, 0.90), "RELEVANT", t0)
    _review(db, _scored_bid(db, 0.00), "MAYBE", t0)
    db.commit()

    report = evaluate_matching(db)
    assert report["total_evaluated_reviews"] == 1
    assert report["excluded_ambiguous"] == 1


def test_duplicate_reviews_collapse_to_latest(db):
    t0 = datetime.now(timezone.utc)
    bid = _scored_bid(db, 0.00)
    _review(db, bid, "RELEVANT", t0)               # earlier
    _review(db, bid, "NOT_RELEVANT", t0 + timedelta(minutes=5))  # latest wins
    db.commit()

    report = evaluate_matching(db)
    assert report["total_evaluated_reviews"] == 1
    # Latest label is NOT_RELEVANT and engine is NO_MATCH -> TN (not FN).
    assert report["true_negatives"] == 1
    assert report["false_negatives"] == 0


def test_review_without_score_is_excluded(db):
    t0 = datetime.now(timezone.utc)
    bid = Bid(title="Never analysed")
    db.add(bid)
    db.flush()
    _review(db, bid, "RELEVANT", t0)
    db.commit()

    report = evaluate_matching(db)
    assert report["total_evaluated_reviews"] == 0
    assert report["excluded_no_score"] == 1
    assert "unmeasured" in report["message"].lower()


def test_large_sample_flags_accuracy_measured(db):
    t0 = datetime.now(timezone.utc)
    for _ in range(MIN_LABELS_FOR_ACCURACY):
        _review(db, _scored_bid(db, 0.90), "RELEVANT", t0)
    db.commit()

    report = evaluate_matching(db)
    assert report["total_evaluated_reviews"] == MIN_LABELS_FOR_ACCURACY
    assert report["sufficient_for_accuracy"] is True
    assert report["accuracy_measured"] is True
    assert report["precision"] == 1.0


def test_evaluation_endpoint_preserves_and_extends_contract(client, db):
    t0 = datetime.now(timezone.utc)
    _review(db, _scored_bid(db, 0.90), "RELEVANT", t0)
    db.commit()

    res = client.get("/api/v1/analytics/evaluation")
    assert res.status_code == 200
    body = res.json()
    # Existing keys must remain for current consumers.
    for key in (
        "total_evaluated_reviews",
        "true_positives",
        "false_positives",
        "false_negatives",
        "true_negatives",
        "precision",
        "recall",
        "agreement_rate",
    ):
        assert key in body
    # Added keys.
    for key in ("f1_score", "accuracy_measured", "limitations", "message"):
        assert key in body


def test_confusion_matrix_key_and_insufficient_status(db):
    t0 = datetime.now(timezone.utc)
    _review(db, _scored_bid(db, 0.90), "RELEVANT", t0)   # TP
    _review(db, _scored_bid(db, 0.80), "NOT_RELEVANT", t0)  # FP
    _review(db, _scored_bid(db, 0.00), "RELEVANT", t0)   # FN
    _review(db, _scored_bid(db, 0.10), "NOT_RELEVANT", t0)  # TN
    db.commit()

    report = evaluate_matching(db)
    assert report["confusion_matrix"] == {
        "true_positive": 1,
        "false_positive": 1,
        "false_negative": 1,
        "true_negative": 1,
    }
    assert report["metrics_status"] == "insufficient_labels"
    assert report["accuracy_measured"] is False


def test_metrics_status_measured_at_threshold(db):
    t0 = datetime.now(timezone.utc)
    for _ in range(MIN_LABELS_FOR_ACCURACY):
        _review(db, _scored_bid(db, 0.90), "RELEVANT", t0)
    db.commit()

    report = evaluate_matching(db)
    assert report["metrics_status"] == "measured"
    assert report["accuracy_measured"] is True


def test_metrics_status_no_valid_labels(db):
    report = evaluate_matching(db)
    assert report["metrics_status"] == "no_valid_labels"
    assert report["accuracy_measured"] is False
    assert report["total_evaluated_reviews"] == 0
    assert "unmeasured" in report["message"].lower()
