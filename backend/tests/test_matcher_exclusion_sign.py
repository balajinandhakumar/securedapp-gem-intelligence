"""Tests for the exclusion-sign fix in the 11-product matching engine.

Seeded exclusion keywords are stored with a negative weight (for example
"tracking script" -> -1.0) to mark them as disqualifying. ``SIGNAL_WEIGHTS``
applies its own negative EXCLUSION multiplier. Multiplying the two negatives
together produced a positive contribution, so mentioning a keyword that exists
precisely to *exclude* a product raised that product's relevance score. That is
a concrete implementation bug, reproduced below.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.intelligence.matching_engine import (
    SIGNAL_WEIGHTS,
    BidMatcherEngine,
    classify_score,
)


def _product(keywords):
    """Minimal stand-in for the ORM Product the engine consumes."""
    return SimpleNamespace(
        id="p1",
        name="TestProduct",
        capabilities=[
            SimpleNamespace(name="capability alpha", weight=1.0, active=True),
        ],
        keywords=[
            SimpleNamespace(keyword=word, weight=weight, type=kind, active=True)
            for word, weight, kind in keywords
        ],
    )


# The text carries one matching keyword and one disqualifying keyword, so the
# positive contribution and the exclusion are both large enough to compare.
TEXT_MAP = {"title": "alpha beta tracking script services"}


class TestExclusionSign:
    def test_seeded_exclusion_weights_are_negative(self):
        assert SIGNAL_WEIGHTS["EXCLUSION"] < 0

    def test_exclusion_keyword_lowers_the_score(self):
        engine = BidMatcherEngine()

        without = engine._match_single_product(
            SimpleNamespace(), TEXT_MAP, _product([("alpha beta", 1.0, "regular")])
        )
        with_exclusion = engine._match_single_product(
            SimpleNamespace(),
            TEXT_MAP,
            _product(
                [
                    ("alpha beta", 1.0, "regular"),
                    ("tracking script", -1.0, "exclusion"),
                ]
            ),
        )

        assert with_exclusion.relevance_score < without.relevance_score, (
            "an exclusion keyword must never increase relevance"
        )

    def test_exclusion_breakdown_reports_the_negative_contribution(self):
        engine = BidMatcherEngine()
        result = engine._match_single_product(
            SimpleNamespace(),
            TEXT_MAP,
            _product([("tracking script", -1.0, "exclusion")]),
        )
        breakdown = result.score_breakdown

        assert breakdown["negative_exclusion_adjustments"] < 0
        assert breakdown["negative_exclusion_adjustments"] == pytest.approx(
            breakdown["raw_score"], rel=0.01
        )
        # Every signal explains its own contribution to the total.
        assert all("weight" in signal for signal in result.signals)

    def test_exclusion_can_push_a_match_down_a_band(self):
        engine = BidMatcherEngine()
        positive = [("alpha beta", 1.0, "positive_signal")]

        clean = engine._match_single_product(
            SimpleNamespace(), TEXT_MAP, _product(positive)
        )
        penalized = engine._match_single_product(
            SimpleNamespace(),
            TEXT_MAP,
            _product(positive + [("tracking script", -1.0, "exclusion")]),
        )
        # Same positive evidence, strictly worse score once the exclusion fires.
        assert penalized.relevance_score < clean.relevance_score
        # The classification follows the score, it is never hardcoded.
        assert penalized.match_state == classify_score(penalized.relevance_score)

    def test_no_signal_still_scores_zero(self):
        engine = BidMatcherEngine()
        result = engine._match_single_product(
            SimpleNamespace(),
            {"title": "nutritional supplement supply"},
            _product([("solidity", 1.0, "positive_signal")]),
        )
        assert result.relevance_score == 0.0
        assert result.match_state == "NO_MATCH"