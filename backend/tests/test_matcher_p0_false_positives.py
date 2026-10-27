"""P0 regression tests for matching-correctness.

Two coupled defects found in the audit are pinned here:

1. *Duplicated title/scope text.* Real GeM bids carry the identical string in
   both ``title`` and ``scope_of_work`` (the ingestion adapter copies one into
   the other). Scoring both counted every matched phrase twice for the same
   evidence. Only the higher-weighted copy is now scored.

2. *Single ambiguous term auto-matching.* A lone everyday token ("Cookies",
   "Staking", "DeFi" as an acronym) seen only in the descriptive fields could
   reach the MATCH band. A match now requires contextual/technical evidence: a
   multi-word phrase (including hyphen compounds such as "Crypto-agility"), a
   technical-field signal, or at least two distinct terms *where at least one
   is specific*. Two ambiguous everyday words ("staking" + "lending") stay
   capped, while the specific pair "KYC" + "AML" does not.

The three tests in ``TestSingleAmbiguousTermCannotMatch`` reproduce the real
false positives from ``dev.db`` (stored 0.825 MATCH / 0.825 MATCH / 0.400
NEEDS_REVIEW) as isolated synthetic bids. Everything here lives only in the
in-memory test database -- nothing touches the real database.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db.seed_knowledge import seed_product_knowledge
from app.models.bid import Bid
from app.services.intelligence import match_bid_against_products
from app.services.intelligence.matching_engine import (
    BidMatcherEngine,
    _UNCONTEXTUAL_CAP,
)


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
# 1. Identical title/scope text is scored once, never twice.
# ---------------------------------------------------------------------------
class TestDuplicatedFieldsAreNotDoubleCounted:
    def test_identical_title_and_scope_score_once(self):
        engine = BidMatcherEngine()
        product = SimpleNamespace(
            id="p1",
            name="TestProduct",
            capabilities=[
                SimpleNamespace(name="smart contract audit", weight=1.0, active=True)
            ],
            keywords=[],
        )
        result = engine._match_single_product(
            SimpleNamespace(),
            {"title": "smart contract audit", "scope_of_work": "smart contract audit"},
            product,
        )
        # title: 1.0 * 3.0 * STRONG(1.0) == 3.0; the identical scope copy adds 0.
        assert result.score_breakdown["raw_score"] == pytest.approx(3.0, abs=0.001)
        assert len(result.signals) == 1

    def test_distinct_fields_still_score_separately(self):
        engine = BidMatcherEngine()
        product = SimpleNamespace(
            id="p1",
            name="TestProduct",
            capabilities=[
                SimpleNamespace(name="smart contract audit", weight=1.0, active=True)
            ],
            keywords=[],
        )
        result = engine._match_single_product(
            SimpleNamespace(),
            {
                "title": "smart contract audit",
                "scope_of_work": "conduct a smart contract audit",
            },
            product,
        )
        # title (3.0) + scope (2.5) are different strings, so both count.
        assert result.score_breakdown["raw_score"] == pytest.approx(5.5, abs=0.001)
        assert len(result.signals) == 2

    def test_long_real_title_and_scope_counted_once(self):
        # Reproduces the real 0.825 false positive's full-length list where the
        # adapter copies the title verbatim into scope_of_work.
        engine = BidMatcherEngine()
        product = SimpleNamespace(
            id="p2",
            name="TestProduct",
            capabilities=[SimpleNamespace(name="Cookies", weight=0.9, active=True)],
            keywords=[],
        )
        text = (
            "Diesel,Engine oil,Oil filter,Fuel filter,Air filter,Photo frames,"
            "Tea,Biscuits,Milk Powder,Cookies,Sugar,Soap"
        )
        result = engine._match_single_product(
            SimpleNamespace(),
            {"title": text, "scope_of_work": text},
            product,
        )
        assert len(result.signals) == 1
        assert result.score_breakdown["raw_score"] == pytest.approx(0.9 * 3.0, abs=0.001)


# ---------------------------------------------------------------------------
# 2. The three real false positives never reach MATCH.
# ---------------------------------------------------------------------------
class TestSingleAmbiguousTermCannotMatch:
    def test_cookies_listing_is_not_a_cookiehub_match(self, db):
        # GEM/2026/B/8018975: a canteen supply list that happens to contain
        # "Cookies". Previously 0.825 MATCH.
        results = match_bid_against_products(
            db,
            _bid(
                db,
                "Diesel,Engine oil,Oil filter,Fuel filter,Air filter,Photo frames,"
                "Tea,Biscuits,Milk Powder,Cookies,Sugar,Soap",
            ),
        )
        cookiehub = _top(results, "CookieHub")
        assert cookiehub.match_state != "MATCH"
        assert cookiehub.relevance_score < 0.45
        assert cookiehub.score_breakdown.get("context_gate") == "INSUFFICIENT_CONTEXT"
        assert all(r.match_state != "MATCH" for r in results)

    def test_staking_tool_is_not_a_securepad_match(self, db):
        # GEM/2026/B/8084573: a physical staking tool. Previously 0.825 MATCH.
        results = match_bid_against_products(
            db, _bid(db, "ORV SPHERICAL BEARING AND STAKING TOOL")
        )
        securepad = _top(results, "SecurePad")
        assert securepad.match_state != "MATCH"
        assert securepad.relevance_score < 0.45
        assert securepad.score_breakdown.get("context_gate") == "INSUFFICIENT_CONTEXT"
        assert all(r.match_state != "MATCH" for r in results)

    def test_arboriculture_defi_services_is_not_a_securepad_match(self, db):
        # GEM/2026/B/8124731: "DEFI" is an acronym in a civil-works title, not
        # decentralized finance.
        results = match_bid_against_products(
            db,
            _bid(
                db,
                "Custom Bid for Services - PROVISION OF ARBORICULTURE FOR DEFI "
                "SINGLE OFFRS ACCN AT MIL STN",
            ),
        )
        securepad = _top(results, "SecurePad")
        assert securepad.match_state != "MATCH"
        assert securepad.relevance_score < 0.45
        assert all(r.match_state != "MATCH" for r in results)


# ---------------------------------------------------------------------------
# 3. The gate is evidence-based: genuine matches are untouched.
# ---------------------------------------------------------------------------
class TestLegitimateEvidenceStillMatches:
    def test_multi_word_technical_evidence_is_untouched(self, db):
        results = match_bid_against_products(
            db,
            _bid(
                db,
                "Solidity Smart Contract Security Audit and Manual Expert Review",
                "Requires pre-deployment vulnerability detection with expert security review.",
            ),
        )
        top = _top(results, "SolidityShield")
        assert top.match_state == "MATCH"
        assert top.relevance_score >= 0.70
        assert top.score_breakdown.get("context_gate") is None

    def test_two_distinct_terms_are_treated_as_context(self, db):
        results = match_bid_against_products(
            db,
            _bid(
                db,
                "AML compliance and AML screening platform for onboarding",
                "KYC/AML verification, watchlist screening and risk scoring",
            ),
        )
        securex = _top(results, "SecureX-ID")
        assert securex.relevance_score > 0.0
        assert securex.score_breakdown.get("context_gate") is None

    def test_gate_never_raises_a_score(self, db):
        # A zero-evidence furniture bid must stay flat zero (the cap is a ceiling,
        # not a floor).
        results = match_bid_against_products(db, _bid(db, "Supply of office furniture"))
        assert all(r.relevance_score == 0.0 for r in results)
        assert all(r.match_state == "NO_MATCH" for r in results)
        assert results[0].relevance_score <= _UNCONTEXTUAL_CAP


# ---------------------------------------------------------------------------
# 4. The "two distinct terms" rule only counts when at least one term is
#    specific; two ambiguous everyday words do not establish context.
# ---------------------------------------------------------------------------
class TestAmbiguousTermPolicy:
    @staticmethod
    def _signals(*pairs):
        return [{"text": t, "field": f, "strength": "STRONG"} for t, f in pairs]

    def test_single_ambiguous_term_is_not_context(self):
        engine = BidMatcherEngine()
        assert engine._has_contextual_evidence(
            self._signals(("Staking", "title"))
        ) is False

    def test_two_ambiguous_terms_are_not_context(self):
        engine = BidMatcherEngine()
        assert engine._has_contextual_evidence(
            self._signals(("Staking", "title"), ("Lending", "title"))
        ) is False

    def test_two_specific_terms_are_context(self):
        engine = BidMatcherEngine()
        assert engine._has_contextual_evidence(
            self._signals(("KYC", "title"), ("AML", "scope_of_work"))
        ) is True

    def test_one_specific_term_among_ambiguous_is_context(self):
        engine = BidMatcherEngine()
        assert engine._has_contextual_evidence(
            self._signals(("Staking", "title"), ("PQC", "title"))
        ) is True

    def test_same_term_in_two_fields_is_one_distinct_term(self):
        engine = BidMatcherEngine()
        assert engine._has_contextual_evidence(
            self._signals(("Staking", "title"), ("Staking", "scope_of_work"))
        ) is False

    def test_hyphenated_compound_counts_as_multiword(self):
        engine = BidMatcherEngine()
        assert engine._has_contextual_evidence(
            self._signals(("Crypto-agility", "title"))
        ) is True
        assert engine._has_contextual_evidence(
            self._signals(("X-ID Score", "title"))
        ) is True

    def test_single_term_in_technical_field_is_context(self):
        engine = BidMatcherEngine()
        assert engine._has_contextual_evidence(
            self._signals(("KYC", "eligibility_criteria"))
        ) is True

    def test_exclusion_only_is_not_context(self):
        engine = BidMatcherEngine()
        assert engine._has_contextual_evidence(
            [{"text": "Forensic investigation", "field": "title", "strength": "EXCLUSION"}]
        ) is False


# ---------------------------------------------------------------------------
# 5. End-to-end behaviour of the hardened gate.
# ---------------------------------------------------------------------------
class TestHardenedGateEndToEnd:
    def test_two_ambiguous_terms_do_not_match_securepad(self, db):
        results = match_bid_against_products(
            db,
            _bid(db, "Staking and lending services for employee cooperative society"),
        )
        securepad = _top(results, "SecurePad")
        assert securepad.match_state != "MATCH"
        assert securepad.relevance_score < 0.45
        assert securepad.score_breakdown.get("context_gate") == "INSUFFICIENT_CONTEXT"
        assert all(r.match_state != "MATCH" for r in results)

    def test_many_documented_terms_reach_match(self, db):
        results = match_bid_against_products(
            db,
            _bid(
                db,
                "Web3 DeFi infrastructure platform with token creation, staking",
                "lending and borrowing, governance",
            ),
        )
        securepad = _top(results, "SecurePad")
        assert securepad.match_state == "MATCH"
        assert securepad.relevance_score >= 0.70
        assert securepad.score_breakdown.get("context_gate") is None

    def test_gate_caps_but_preserves_evidence(self, db):
        results = match_bid_against_products(
            db, _bid(db, "Diesel, Engine oil, Cookies, Tea, Sugar, Soap")
        )
        cookiehub = _top(results, "CookieHub")
        assert cookiehub.relevance_score == pytest.approx(_UNCONTEXTUAL_CAP, abs=1e-4)
        assert cookiehub.match_state == "NEEDS_REVIEW"
        assert cookiehub.signals
        assert cookiehub.score_breakdown["normalized_score"] > cookiehub.relevance_score
        assert cookiehub.score_breakdown.get("context_gate") == "INSUFFICIENT_CONTEXT"

    def test_scope_gated_result_has_no_context_gate_marker(self, db):
        # A bid carrying a product signal but none of that product's domain
        # anchors is out of scope: relevance is suppressed (scope gate) and it
        # must NOT additionally carry a context-gate marker -- the two gates
        # are mutually exclusive.
        results = match_bid_against_products(
            db,
            _bid(db, "Annual security assessment and access control review of office premises."),
        )
        auditexpress = _top(results, "AuditExpress")
        assert auditexpress.score_breakdown.get("scope_gate") == "OUT_OF_SCOPE"
        assert auditexpress.score_breakdown.get("context_gate") is None
        assert auditexpress.relevance_score == 0.0
        assert auditexpress.match_state == "NO_MATCH"
