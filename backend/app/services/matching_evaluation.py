"""
Ground-truth evaluation of the bid-to-product matching engine.

The matching engine is deterministic and has no learned parameters, so its
"accuracy" is only meaningful as agreement with a human relevance judgement.
This module turns the persisted :class:`HumanReview` records into that
comparison, using **only labels that can validly serve as ground truth**:

* ``relevance_decision`` is used. ``RELEVANT`` is the positive class and
  ``NOT_RELEVANT`` the negative class.
* ``MAYBE`` is an explicit "undecided" and is **excluded** -- counting it as
  either class would invent a label the reviewer did not give.
* ``pursue_decision`` is a commercial choice, not a relevance label, and is not
  used.

Two further safeguards keep the number honest:

* Reviews are de-duplicated to the **latest review per bid**, so a bid reviewed
  twice does not weigh twice.
* A review is only evaluated when its bid has a persisted :class:`BidScore`
  (i.e. the engine actually produced a prediction). Reviews whose bid was never
  analysed are reported separately and excluded.

The AI prediction uses the engine's own positive class through the shared
``classify_score`` classifier (``MATCH``, the >= 0.70 band -- the same boundary
the dashboard and notifications use), so it follows any configured threshold.

Below :data:`MIN_LABELS_FOR_ACCURACY` evaluated samples the point estimates are
too noisy to present as a measured accuracy. The metrics are still returned (so
callers can inspect them) but are flagged ``sufficient_for_accuracy: false``,
``metrics_status`` reads ``insufficient_labels`` (or ``no_valid_labels``), and
the verdict states explicitly that accuracy remains unmeasured. A full
``confusion_matrix`` accompanies the counts.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.analysis import BidScore
from app.models.review import HumanReview
from app.services.intelligence.matching_engine import classify_score

POSITIVE_LABEL = "RELEVANT"
NEGATIVE_LABEL = "NOT_RELEVANT"
VALID_LABELS = frozenset({POSITIVE_LABEL, NEGATIVE_LABEL})

# The engine's own positive class (the >= 0.70 relevance band). Kept as a name
# rather than a number so it stays in lockstep with classify_score.
POSITIVE_CLASS = "MATCH"

# Minimum evaluated samples before precision/recall/F1 are reported as a
# measured accuracy rather than a provisional figure.
MIN_LABELS_FOR_ACCURACY = 30


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 3) if denominator > 0 else 0.0


def _latest_review_per_bid(reviews: List[HumanReview]) -> List[HumanReview]:
    latest: Dict[str, HumanReview] = {}
    for review in reviews:
        key = str(review.bid_id)
        current = latest.get(key)
        if current is None or (review.reviewed_at, str(review.id)) > (
            current.reviewed_at,
            str(current.id),
        ):
            latest[key] = review
    return list(latest.values())


def evaluate_matching(db: Session) -> Dict[str, Any]:
    """Compare the engine's relevance predictions against validated human labels."""
    all_reviews = db.query(HumanReview).all()
    latest = _latest_review_per_bid(all_reviews)

    tp = fp = fn = tn = 0
    excluded_ambiguous = 0
    excluded_no_score = 0

    for review in latest:
        decision = (review.relevance_decision or "").upper()
        if decision not in VALID_LABELS:
            excluded_ambiguous += 1
            continue

        score = (
            db.query(BidScore)
            .filter(BidScore.bid_id == review.bid_id)
            .order_by(BidScore.created_at.desc())
            .first()
        )
        if score is None:
            excluded_no_score += 1
            continue

        ai_positive = classify_score(score.relevance_score) == POSITIVE_CLASS
        human_positive = decision == POSITIVE_LABEL

        if ai_positive and human_positive:
            tp += 1
        elif ai_positive and not human_positive:
            fp += 1
        elif not ai_positive and human_positive:
            fn += 1
        else:
            tn += 1

    evaluated = tp + fp + fn + tn
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = (
        round(2 * precision * recall / (precision + recall), 3)
        if (precision + recall) > 0
        else 0.0
    )
    agreement_rate = _ratio(tp + tn, evaluated)
    sufficient = evaluated >= MIN_LABELS_FOR_ACCURACY

    # Explicit measurement status so no consumer has to infer it:
    #   measured            -> sample is large enough to quote as accuracy
    #   insufficient_labels -> figures exist but are provisional / unmeasured
    #   no_valid_labels     -> nothing to evaluate at all
    metrics_status = (
        "measured" if sufficient else ("insufficient_labels" if evaluated else "no_valid_labels")
    )

    limitations: List[str] = [
        "Ground truth is the reviewer's `relevance_decision`; only RELEVANT and "
        "NOT_RELEVANT are used. MAYBE reviews are excluded as undecided.",
        "Reviews are de-duplicated to the latest review per bid.",
        "A positive AI prediction is the engine's MATCH class (relevance >= 0.70).",
        f"At least {MIN_LABELS_FOR_ACCURACY} evaluated labels are required before "
        "these figures are reported as a measured accuracy.",
    ]
    if not sufficient:
        limitations.append(
            "Insufficient labelled data: matching accuracy remains unmeasured."
        )

    result: Dict[str, Any] = {
        # --- existing keys (backward compatible) ---
        "total_evaluated_reviews": evaluated,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "precision": precision,
        "recall": recall,
        "agreement_rate": agreement_rate,
        # --- added keys ---
        "f1_score": f1,
        "confusion_matrix": {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "true_negative": tn,
        },
        "metrics_status": metrics_status,
        "total_reviews": len(all_reviews),
        "distinct_reviewed_bids": len(latest),
        "excluded_ambiguous": excluded_ambiguous,
        "excluded_no_score": excluded_no_score,
        "positive_class": POSITIVE_CLASS,
        "min_labels_for_accuracy": MIN_LABELS_FOR_ACCURACY,
        "sufficient_for_accuracy": sufficient,
        "accuracy_measured": sufficient,
        "limitations": limitations,
    }

    if evaluated == 0:
        if not all_reviews:
            result["message"] = (
                "No human reviews submitted yet for evaluation; accuracy "
                "remains unmeasured."
            )
        elif excluded_no_score and not excluded_ambiguous:
            result["message"] = (
                "Reviews exist but none of their bids has a persisted score to "
                "compare against; accuracy remains unmeasured."
            )
        else:
            result["message"] = (
                "No reviews with a valid (RELEVANT / NOT_RELEVANT) label and a "
                "persisted score; accuracy remains unmeasured."
            )
    elif not sufficient:
        result["message"] = (
            f"Only {evaluated} evaluated label(s); results are provisional and "
            "accuracy remains unmeasured until at least "
            f"{MIN_LABELS_FOR_ACCURACY} are available."
        )
    else:
        result["message"] = (
            f"Computed from {evaluated} evaluated label(s)."
        )

    return result
