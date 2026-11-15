"""Regression tests for the generic-overmatch / double-counting fix.

Two coupled root causes are pinned here:

1. *Generic-word overmatch.* The catalogue shares generic security phrases
   ("security assessment", "monitoring", "key management") across products, so a
   bid with none of a product's own domain vocabulary could still score into the
   MATCH band. The real GeM bid "Penetration Testing and Security Assessment
   Software" matched AuditExpress purely on the phrase "security assessment".
   A product whose evidence carries none of its scope anchors is now NO_MATCH.

2. *Duplicate / overlapping signals.* A phrase listed as both a capability and a
   keyword (or a short keyword nested inside a capability phrase) was counted
   twice for the same bid field, inflating the raw score. Matches are now
   collapsed per field so one phrase contributes once.

All bids here are synthetic and live only in the isolated in-memory test DB.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db.seed_knowledge import seed_product_knowledge
from app.models.bid import Bid
from app.services.intelligence import match_bid_against_products
from app.services.intelligence.matching_engine import BidMatcherEngine


@pytest.fixture(autouse=True)
def seed_knowledge(db):
    seed_product_knowledge(db)


def _bid(db, title, scope=None) -> Bid:
    bid = Bid(title=title, scope_of_work=scope or title)
    db.add(bid)
    db.commit()
    return bid


def _top(results, product_name):
    return next(r for r in results if r.product_name == product_name)


# ---------------------------------------------------------------------------
# 1. A genuine cyber security-assessment / penetration-testing tender now
#    matches AuditExpress (and SolidityShield). The previous behaviour --
#    suppressing every bid that lacked a blockchain anchor -- is the root
#    cause of the "1 relevant bid out of ~30,000" report: real GeM pen-test
#    and security-audit tenders were out of scope by construction.
# ---------------------------------------------------------------------------
class TestAuditExpressTruePositive:
    def test_penetration_testing_bid_matches_auditexpress(self, db):
        bid = _bid(
            db,
            "Penetration Testing and Security Assessment Software",
            "Procurement of penetration testing tools and a general security "
            "assessment of the network perimeter.",
        )
        results = match_bid_against_products(db, bid)

        audit = _top(results, "AuditExpress")
        assert audit.score_breakdown.get("scope_gate") is None
        assert audit.match_state == "MATCH"
        assert audit.relevance_score >= 0.70
        assert len(audit.signals) > 0
        assert any(s["text"] == "penetration testing" for s in audit.signals)

        # SolidityShield is a smart-contract security product. A general
        # penetration-testing tender has no smart-contract domain anchor, so
        # SolidityShield is domain-gated to NEEDS_REVIEW (never auto-matched).
        shield = _top(results, "SolidityShield")
        assert shield.match_state == "NEEDS_REVIEW"
        assert shield.relevance_score == 0.3999
        assert shield.score_breakdown.get("domain_gate") == "NO_DOMAIN_ANCHOR"

    def test_vulnerability_assessment_bid_matches(self, db):
        bid = _bid(
            db,
            "Vulnerability Assessment and Management Platform",
            "Enterprise vulnerability assessment and remediation tracking.",
        )
        results = match_bid_against_products(db, bid)
        audit = _top(results, "AuditExpress")
        assert audit.score_breakdown.get("scope_gate") is None
        assert audit.match_state in ("MATCH", "POSSIBLE_MATCH")
        assert audit.relevance_score >= 0.45

    def test_cyber_security_audit_bid_matches(self, db):
        bid = _bid(
            db,
            "Cyber Security Audit - Infrastructure Audit",
            "Infrastructure security audit of network and server assets.",
        )
        results = match_bid_against_products(db, bid)
        audit = _top(results, "AuditExpress")
        assert audit.score_breakdown.get("scope_gate") is None
        assert audit.relevance_score >= 0.45

    def test_vapt_bid_matches(self, db):
        bid = _bid(
            db,
            "Custom Bid for Services - IV&V, VAPT, QA & BSS",
        )
        results = match_bid_against_products(db, bid)
        audit = _top(results, "AuditExpress")
        assert audit.score_breakdown.get("scope_gate") is None
        assert audit.match_state == "NEEDS_REVIEW"
        assert any(s["text"] == "vapt" for s in audit.signals)


# ---------------------------------------------------------------------------
# 2. Generic physical-security tenders with no cyber scope must still stay out
#    of scope for AuditExpress / SolidityShield.
# ---------------------------------------------------------------------------
class TestAuditExpressFalsePositive:
    def test_generic_security_assessment_without_contract_scope_is_not_a_match(self, db):
        bid = _bid(
            db,
            "Security Assessment Services for Office Buildings",
            "Annual security assessment and access control review of premises.",
        )
        results = match_bid_against_products(db, bid)
        audit = _top(results, "AuditExpress")
        assert audit.match_state == "NO_MATCH"
        assert audit.relevance_score == 0.0
        assert audit.score_breakdown.get("scope_gate") == "OUT_OF_SCOPE"
        # A scope-gated bid must not also carry a context-gate marker: the two
        # gates are mutually exclusive.
        assert audit.score_breakdown.get("context_gate") is None


# ---------------------------------------------------------------------------
# 2. A genuinely smart-contract scoped audit still matches AuditExpress.
# ---------------------------------------------------------------------------
class TestScopeAnchorsKeepGenuineMatches:
    def test_smart_contract_scope_is_not_gated(self, db):
        bid = _bid(
            db,
            "Automated Security Assessment for Smart Contracts",
            "Rapid automated security assessment and vulnerability scanning of "
            "smart contract code.",
        )
        results = match_bid_against_products(db, bid)
        audit = _top(results, "AuditExpress")
        assert audit.score_breakdown.get("scope_gate") is None
        assert audit.relevance_score > 0.0
        assert results[0].product_name == "AuditExpress"

    def test_anchors_are_plural_tolerant(self, db):
        bid = _bid(
            db,
            "Security Assessment of Solidity Smart Contracts",
            "Automated contract security assessment.",
        )
        audit = _top(match_bid_against_products(db, bid), "AuditExpress")
        assert audit.score_breakdown.get("scope_gate") is None
        assert audit.relevance_score > 0.0


# ---------------------------------------------------------------------------
# 3. Duplicate / overlapping signals are collapsed per field.
# ---------------------------------------------------------------------------
def _product(name, capabilities, keywords):
    return SimpleNamespace(
        id="p1",
        name=name,
        capabilities=[
            SimpleNamespace(name=cap, weight=weight, active=True)
            for cap, weight in capabilities
        ],
        keywords=[
            SimpleNamespace(keyword=word, weight=weight, type=kind, active=True)
            for word, weight, kind in keywords
        ],
    )


class TestSignalDeduplication:
    def test_identical_capability_and_keyword_counted_once(self):
        engine = BidMatcherEngine()
        product = _product(
            "TestProduct",
            [("security assessment", 0.9)],
            [("security assessment", 0.9, "positive_signal")],
        )
        result = engine._match_single_product(
            SimpleNamespace(), {"title": "security assessment"}, product
        )
        # 0.9 * title(3.0) * STRONG(1.0) == 2.7, not the doubled 5.4.
        assert result.score_breakdown["raw_score"] == pytest.approx(2.7, abs=0.001)
        assert len(result.signals) == 1

    def test_nested_keyword_inside_capability_counted_once(self):
        engine = BidMatcherEngine()
        product = _product(
            "TestProduct",
            [("reentrancy detection", 1.0)],
            [("reentrancy", 1.0, "positive_signal")],
        )
        result = engine._match_single_product(
            SimpleNamespace(), {"title": "reentrancy detection service"}, product
        )
        assert result.score_breakdown["raw_score"] == pytest.approx(3.0, abs=0.001)
        assert len(result.signals) == 1

    def test_distinct_phrases_are_both_kept(self):
        engine = BidMatcherEngine()
        product = _product(
            "TestProduct",
            [("smart contract audit", 1.0)],
            [("solidity", 1.0, "positive_signal")],
        )
        result = engine._match_single_product(
            SimpleNamespace(),
            {"title": "solidity smart contract audit"},
            product,
        )
        assert len(result.signals) == 2
        assert result.score_breakdown["raw_score"] == pytest.approx(6.0, abs=0.001)

    def test_exclusions_are_never_collapsed(self):
        engine = BidMatcherEngine()
        product = _product(
            "TestProduct",
            [("tracking script management", 1.0)],
            [("tracking script", -1.0, "exclusion")],
        )
        result = engine._match_single_product(
            SimpleNamespace(), {"title": "tracking script management"}, product
        )
        strengths = [s["strength"] for s in result.signals]
        assert "EXCLUSION" in strengths
        assert result.score_breakdown["negative_exclusion_adjustments"] < 0


# ---------------------------------------------------------------------------
# 4. Scope gate is only about scope; a product with no anchor list is untouched.
# ---------------------------------------------------------------------------
class TestScopeGateBoundaries:
    def test_product_without_anchors_is_never_gated(self):
        engine = BidMatcherEngine()
        product = _product(
            "AdminCreatedProduct",
            [("attack surface monitoring", 1.0)],
            [],
        )
        result = engine._match_single_product(
            SimpleNamespace(), {"title": "attack surface monitoring"}, product
        )
        assert result.relevance_score > 0.0
        assert result.score_breakdown.get("scope_gate") is None

    def test_anchor_present_but_no_evidence_scores_zero(self, db):
        # Mentions "smart contract" (an AuditExpress anchor) but matches no
        # capability/keyword, so there is no manufactured match.
        bid = _bid(db, "Training on smart contracts", "Awareness workshop.")
        audit = _top(match_bid_against_products(db, bid), "AuditExpress")
        assert audit.relevance_score == 0.0
        assert audit.match_state == "NO_MATCH"
