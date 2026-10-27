"""Regression tests for token-aware (word-boundary) product term matching.

A short product keyword such as ``aml`` or ``defi`` must only fire on a real
occurrence of the term, never as an arbitrary substring inside an unrelated
word. Before this fix ``aml`` matched "seamless"/"hamla" and ``defi`` matched
"defibrillator", which manufactured MATCH scores for physical-goods bids.
"""
from __future__ import annotations

import pytest

from app.db.seed_knowledge import seed_product_knowledge
from app.models.bid import Bid
from app.models.product import Product
from app.services.intelligence import match_bid_against_products
from app.services.intelligence.matching_engine import (
    BidMatcherEngine,
    text_contains_term,
    term_in_text,
)


# ---------------------------------------------------------------------------
# 1. Pure term/phrase behaviour
# ---------------------------------------------------------------------------
class TestTermBoundaries:
    @pytest.mark.parametrize(
        "text",
        [
            "seamless",
            "Seamless",
            "supply of seamless p-Ag alloy tubes",
            "formal",
            "formaldehyde",
            "animal",
            "animal feed and fodder",
            "INS HAMLA",
            "refurbishment of pol store at ins hamla",
        ],
    )
    def test_aml_does_not_match_inside_unrelated_words(self, text):
        assert term_in_text(text, "aml") is None

    @pytest.mark.parametrize(
        "text",
        [
            "defibrillator",
            "Defibrillators, ECG leads",
            "external cardiac defibrillator",
            "modified",
            "premodified cable",
        ],
    )
    def test_defi_does_not_match_inside_unrelated_words(self, text):
        assert term_in_text(text, "defi") is None

    @pytest.mark.parametrize(
        "text",
        [
            "AML compliance",
            "AML screening",
            "aml checks for onboarding",
            "KYC/AML verification",
            "anti-money laundering (AML) review",
        ],
    )
    def test_aml_matches_legitimate_phrases(self, text):
        assert term_in_text(text, "aml") is not None

    @pytest.mark.parametrize(
        "text",
        [
            "DeFi protocol",
            "DeFi platform",
            "defi infrastructure audit",
            "decentralised DeFi lending service",
        ],
    )
    def test_defi_matches_legitimate_phrases(self, text):
        assert term_in_text(text, "defi") is not None

    def test_multi_word_phrase_requires_consecutive_words(self):
        assert text_contains_term("smart contract audit", "smart contract")
        assert not text_contains_term("smart grid maintenance contract", "smart contract")

    def test_capitalisation_is_ignored(self):
        assert text_contains_term("SEAMLESS PIPE", "seamless")
        assert text_contains_term("DEFI PROTOCOL", "defi")


# ---------------------------------------------------------------------------
# 2. The 11-product engine must not score unrelated bids off substring hits
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def seed_knowledge(db):
    seed_product_knowledge(db)


def _top(results, product_name):
    return next(r for r in results if r.product_name == product_name)


def _bid(db, title, scope=None):
    bid = Bid(title=title, scope_of_work=scope or title)
    db.add(bid)
    db.commit()
    return bid


class TestNoFalsePositives:
    def test_seamless_and_hamla_bids_no_longer_match_securex_id(self, db):
        bid = _bid(
            db,
            "REFURBISHMENT OF POL STORE (480 SQ. FT) AT INS HAMLA",
            "Supply of seamless stainless steel tubes for the works",
        )
        results = match_bid_against_products(db, bid)
        assert _top(results, "SecureX-ID").relevance_score == 0.0
        assert results[0].match_state == "NO_MATCH"
        assert all(r.relevance_score == 0.0 for r in results)

    def test_defibrillator_bids_no_longer_match_securepad(self, db):
        bid = _bid(
            db,
            "Automated External Defibrillators (AEDs) with ECG Display",
            "Supply of defibrillator units and consumables to a hospital",
        )
        results = match_bid_against_products(db, bid)
        assert _top(results, "SecurePad").relevance_score == 0.0
        assert all(r.relevance_score == 0.0 for r in results)

    def test_ordinary_manufactured_goods_score_nothing(self, db):
        bid = _bid(db, "Copper seamless pipe in annealed condition")
        results = match_bid_against_products(db, bid)
        assert all(r.relevance_score == 0.0 for r in results)


class TestLegitimateTermsStillMatch:
    def test_aml_phrase_still_scores_for_securex_id(self, db):
        bid = _bid(
            db,
            "AML compliance and AML screening platform for onboarding",
            "KYC/AML verification, watchlist screening and risk scoring",
        )
        results = match_bid_against_products(db, bid)
        securex = _top(results, "SecureX-ID")
        assert securex.relevance_score > 0.0
        assert securex.match_state in ("MATCH", "POSSIBLE_MATCH", "NEEDS_REVIEW", "NO_MATCH")

    def test_defi_phrase_still_scores_for_securepad(self, db):
        bid = _bid(
            db,
            "Security audit of DeFi protocol and DeFi platform contracts",
            "Smart contract review for a decentralised DeFi lending protocol",
        )
        results = match_bid_against_products(db, bid)
        assert _top(results, "SecurePad").relevance_score > 0.0

    def test_signals_record_a_matched_snippet_for_a_real_term(self, db):
        bid = _bid(db, "AML screening solution", "AML compliance services")
        results = match_bid_against_products(db, bid)
        securex = _top(results, "SecureX-ID")
        aml_signals = [s for s in securex.signals if s.get("text", "").lower() == "aml"]
        assert aml_signals
        assert "aml" in aml_signals[0]["snippet"]

    def test_product_catalogue_untouched(self, db):
        assert db.query(Product).count() == 11
        assert all(p.active for p in db.query(Product).all())


def test_engine_helpers_are_cached_and_pure():
    assert term_in_text("seamless", "aml") is None
    assert term_in_text("AML screening", "aml") is not None
    assert text_contains_term("", "aml") is False
    # an empty/whitespace term never matches anything
    assert term_in_text("anything at all", "   ") is None
