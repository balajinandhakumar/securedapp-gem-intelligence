"""
Stage 1 regression tests: evidence-free product matches and product display.

The root cause fixed here is `_apply_product_differentiation()` in the matching
engine. Its rule triggers include generic, everyday words such as
``investigation``/``forensic``/``tracing`` (and ``expert review``, ``cookie``,
``hsm``, ...) that carry no product meaning on their own. Because the boost was
applied unconditionally, a bid that contained those words but none of the
product's actual keywords or capabilities was pushed from a zero base up to
0.25 -- right across the NEEDS_REVIEW boundary -- and then surfaced as (and even
persisted as) a matched product.

These tests pin the corrected contract:

* differentiation never manufactures a nonzero match out of a zero base;
* genuine matches, backed by real catalogue keywords/capabilities, still win;
* the score breakdown (raw, normalized, adjustment, final, explanation) is an
  auditable, self-consistent record;
* no NO_MATCH bid shows a fabricated product in the API or the feed, and the
  ``/match-products`` endpoint no longer stores evidence-free candidates.

All bids in this file are synthetic and live only in the isolated in-memory test
database -- nothing here touches the real database.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.seed_knowledge import seed_product_knowledge
from app.models.analysis import BidProductMatch, BidScore
from app.models.bid import Bid
from app.services.bid_views import serialise_bid
from app.services.intelligence import match_bid_against_products, process_bid_intelligence
from app.services.intelligence.matching_engine import classify_score, NORMALIZATION_DENOMINATOR


@pytest.fixture(autouse=True)
def seed_knowledge(db):
    """Seed product knowledge into the isolated test DB before each test."""
    seed_product_knowledge(db)


def _bid(db, title, scope=None, **kwargs) -> Bid:
    bid = Bid(title=title, scope_of_work=scope or title, **kwargs)
    db.add(bid)
    db.commit()
    return bid


def _top(results, product_name):
    return next(r for r in results if r.product_name == product_name)


def _assert_all_no_match(results):
    assert all(r.relevance_score == 0.0 for r in results)
    assert all(r.match_state == "NO_MATCH" for r in results)
    assert results[0].match_state == "NO_MATCH"


# ---------------------------------------------------------------------------
# 1. A bid containing generic "investigation"/"forensic"/"tracing" words but no
#    product evidence must remain NO_MATCH.
# ---------------------------------------------------------------------------
class TestGenericWordsCannotManufactureSecureTrace:
    @pytest.mark.parametrize(
        "title,scope",
        [
            (
                "Investigation of cyber fraud cases",
                "Forensic audit of payment records and tracing of fraudulent transfers",
            ),
            (
                "Forensic analysis service",
                "Detailed tracing and investigation of suspicious activities",
            ),
            (
                "Anti-forensic countermeasures for tracing supply chains",
                "Investigation and forensic review of logistics documents",
            ),
        ],
    )
    def test_generic_investigation_forensic_tracing_stays_no_match(self, db, title, scope):
        results = match_bid_against_products(db, _bid(db, title, scope))
        _assert_all_no_match(results)
        # SecureTrace must not be assigned merely because these words triggered
        # its differentiation rule; it needs real capability/keyword evidence.
        assert _top(results, "SecureTrace").relevance_score == 0.0


# ---------------------------------------------------------------------------
# 2. The other four differentiation rules cannot independently manufacture a
#    match from their trigger words alone.
# ---------------------------------------------------------------------------
class TestOtherDifferentiationRulesCannotManufactureMatches:
    @pytest.mark.parametrize(
        "title,scope,assert_zero",
        [
            (
                "Expert Review and Manual Review Services",
                "Auditor validation and expert review for documentation",
                ("SolidityShield", "AuditExpress"),
            ),
            (
                "Cookie handling and website script optimisation",
                "Website script management for the online store",
                ("SecureCMS", "CookieHub"),
            ),
            (
                "Verifiable Credential handling for archivists",
                "A single verifiable credential was presented for review",
                ("SecureX-DID", "SecureX-ID"),
            ),
            (
                "Watchlist screening desk",
                "Watchlist screening for internal compliance",
                ("SecureX-ID", "SecureX-DID"),
            ),
            (
                "HSM and hardware key management",
                "Hardware key custody services for data centres",
                ("PQCSuite", "QuantumVault"),
            ),
        ],
    )
    def test_rule_triggers_alone_stay_no_match(self, db, title, scope, assert_zero):
        results = match_bid_against_products(db, _bid(db, title, scope))
        _assert_all_no_match(results)
        for product_name in assert_zero:
            assert _top(results, product_name).relevance_score == 0.0

    def test_rule1_does_not_rank_auditexpress_by_rapid_automated_words(self, db):
        results = match_bid_against_products(
            db,
            _bid(
                db,
                "Rapid automated clearance of customs paperwork",
                "Automated assessment only of import documentation",
            ),
        )
        _assert_all_no_match(results)
        assert _top(results, "AuditExpress").relevance_score == 0.0


# ---------------------------------------------------------------------------
# 3. Score breakdowns and explanations accurately reflect the final score.
# ---------------------------------------------------------------------------
class TestScoreBreakdownConsistency:
    def test_differentiation_adjustment_reconciles_with_final_score(self, db):
        # Genuine QuantumVault evidence (deduplicated raw 3.0 -> normalized 0.5)
        # plus the 0.30 hardware-backed differentiation boost ends at 0.80 MATCH.
        # The breakdown must record the base, the adjustment and the reconciled
        # final value.
        results = match_bid_against_products(
            db,
            _bid(
                db,
                "Hardware-Backed Cryptographic Key Protection and HSM Management",
                "Hardware security module (HSM) based key generation, storage, and access control.",
            ),
        )
        qvt = _top(results, "QuantumVault")
        sb = qvt.score_breakdown

        raw = sb["raw_score"]
        base = round(max(0.0, min(1.0, raw / NORMALIZATION_DENOMINATOR)), 3)
        adj = sb["differentiation_adjustments"]
        expected = round(max(0.0, min(1.0, base + adj)), 3)

        assert adj > 0.0
        assert sb["final_relevance_score"] == pytest.approx(expected, abs=1e-9)
        assert qvt.relevance_score == pytest.approx(sb["final_relevance_score"], abs=1e-6)
        assert sb["classification"] == classify_score(qvt.relevance_score)
        assert qvt.match_state == sb["classification"]
        assert str(round(qvt.relevance_score, 3)) in qvt.reason
        assert "Boosted" in qvt.reason

    def test_raw_score_equals_sum_of_signal_weights(self, db):
        results = match_bid_against_products(
            db,
            _bid(
                db,
                "AML compliance and AML screening platform for onboarding",
                "KYC/AML verification, watchlist screening and risk scoring",
            ),
        )
        xid = _top(results, "SecureX-ID")
        total_signals = sum(s.get("weight", 0.0) for s in xid.signals)
        assert xid.score_breakdown["raw_score"] == pytest.approx(total_signals, abs=0.02)

    def test_no_signal_no_adjustment_candidates_breakdown_is_flat_zero(self, db):
        results = match_bid_against_products(db, _bid(db, "Supply of office furniture"))
        sb = results[0].score_breakdown
        assert sb["raw_score"] == 0.0
        assert sb["normalized_score"] == 0.0
        assert sb["differentiation_adjustments"] == 0.0
        assert sb["final_relevance_score"] == 0.0
        assert sb["classification"] == "NO_MATCH"


# ---------------------------------------------------------------------------
# 4. A genuine bid with supporting SecureTrace capabilities still matches.
# ---------------------------------------------------------------------------
class TestGenuineSecureTraceStillMatches:
    def test_securetrace_capability_bid_is_still_a_match(self, db):
        results = match_bid_against_products(
            db,
            _bid(
                db,
                "Blockchain Investigation and Transaction Tracing Platform",
                "Forensic fund-flow analysis and tracing suspicious transactions across wallets.",
            ),
        )
        trc = _top(results, "SecureTrace")
        assert trc.relevance_score >= 0.70
        assert trc.match_state == "MATCH"
        assert results[0].product_name == "SecureTrace"
        assert results[0].relevance_score >= trc.relevance_score

    def test_securetrace_beats_securewatch_on_forensics(self, db):
        results = match_bid_against_products(
            db,
            _bid(
                db,
                "Blockchain Investigation and Transaction Tracing Platform",
                "Forensic fund-flow analysis and tracing suspicious transactions across wallets.",
            ),
        )
        assert _top(results, "SecureTrace").relevance_score > _top(results, "SecureWatch").relevance_score

    def test_securewatch_beats_securetrace_on_monitoring(self, db):
        results = match_bid_against_products(
            db,
            _bid(
                db,
                "Blockchain Transaction Continuous Monitoring and Alerting",
                "Continuous monitoring of smart contract activity with anomaly detection and real-time alerts.",
            ),
        )
        assert _top(results, "SecureWatch").relevance_score > _top(results, "SecureTrace").relevance_score


# ---------------------------------------------------------------------------
# 5. NO_MATCH bids never show a fabricated product in the API or feed, and
#    /match-products never persists an evidence-free candidate.
# ---------------------------------------------------------------------------
class TestNoFabricatedProductInApiOrPersistence:
    def test_match_products_persists_nothing_for_evidence_free_bid(self, client: TestClient, db):
        bid = _bid(
            db,
            "Investigation of cyber fraud cases",
            "Forensic audit of payment records and tracing of fraudulent transfers",
        )
        res = client.post(f"/api/v1/bids/{bid.id}/match-products")
        assert res.status_code == 200
        data = res.json()
        assert data["total_products_evaluated"] == 11
        assert all(c["match_state"] == "NO_MATCH" for c in data["candidate_products"])
        assert all(c["relevance_score"] < 0.25 for c in data["candidate_products"])
        assert db.query(BidProductMatch).filter(BidProductMatch.bid_id == bid.id).count() == 0

    def test_match_products_persists_only_genuine_match(self, client: TestClient, db):
        bid = _bid(
            db,
            "Blockchain Investigation and Transaction Tracing Platform",
            "Forensic fund-flow analysis and tracing suspicious transactions across wallets.",
        )
        res = client.post(f"/api/v1/bids/{bid.id}/match-products")
        assert res.status_code == 200
        matches = db.query(BidProductMatch).filter(BidProductMatch.bid_id == bid.id).all()
        assert len(matches) == 1
        assert matches[0].evidence["match_state"] == "MATCH"
        assert matches[0].match_score >= 0.70

    def test_intelligence_feed_never_names_a_no_match_product(self, client: TestClient, db):
        bid = _bid(
            db,
            "Investigation of cyber fraud cases",
            "Forensic audit of payment records and tracing of fraudulent transfers",
        )
        process_bid_intelligence(db, bid, auto_notify=False)

        rows = {r["id"]: r for r in client.get("/api/v1/bids/intelligence").json()["bids"]}
        row = rows[str(bid.id)]
        assert row["analyzed"] is True
        assert row["match_state"] == "NO_MATCH"
        assert row["matched_product"] is None

    def test_serialise_bid_hides_no_match_top_candidate(self, db):
        bid = Bid(id=uuid4(), title="Evidence-free generic bid")
        score = BidScore(
            id=uuid4(),
            bid_id=bid.id,
            analysis_id=uuid4(),
            relevance_score=0.0,
            opportunity_score=0.2,
            relevance_label="NO_MATCH",
            urgency="NORMAL",
            score_breakdown={
                "highest_product_match": {
                    "product_name": "SolidityShield",
                    "match_state": "NO_MATCH",
                }
            },
        )
        row = serialise_bid(bid, score)
        assert row["match_state"] == "NO_MATCH"
        assert row["matched_product"] is None


# ---------------------------------------------------------------------------
# 6. Missing analysis is reported as analyzed=False with no scores; the UI
#    renders that as "Not yet analyzed".
# ---------------------------------------------------------------------------
class TestMissingAnalysisState:
    def test_unanalyzed_bid_has_no_scores_in_the_feed(self, client: TestClient, db):
        bid = _bid(db, "Supply of ergonomic office chairs and wooden desks")
        rows = {r["id"]: r for r in client.get("/api/v1/bids/intelligence").json()["bids"]}
        row = rows[str(bid.id)]
        assert row["analyzed"] is False
        assert row["relevance_score"] is None
        assert row["opportunity_score"] is None
        assert row["matched_product"] is None

    def test_analyzed_bid_without_product_still_shows_no_product(self, client: TestClient, db):
        # A scored bid in the NO_MATCH band is analyzed; it just matched nothing.
        bid = _bid(db, "Supply of office furniture and stationery")
        process_bid_intelligence(db, bid, auto_notify=False)
        rows = {r["id"]: r for r in client.get("/api/v1/bids/intelligence").json()["bids"]}
        row = rows[str(bid.id)]
        assert row["analyzed"] is True
        assert row["match_state"] == "NO_MATCH"
        assert row["matched_product"] is None


# ---------------------------------------------------------------------------
# 7. Existing valid matches continue to work across all five product pairs.
# ---------------------------------------------------------------------------
class TestExistingValidMatchesStillWork:
    @pytest.mark.parametrize(
        "title,scope,expected_top",
        [
            # Rule 1: SolidityShield vs AuditExpress
            (
                "Solidity Smart Contract Security Audit and Manual Expert Review",
                "Requires pre-deployment vulnerability detection with expert security review and remediation validation.",
                "SolidityShield",
            ),
            (
                "Automated Security Assessment for Smart Contracts",
                "Rapid automated security assessment and vulnerability scanning for smart contract posture.",
                "AuditExpress",
            ),
            # Rule 2: SecureTrace vs SecureWatch
            (
                "Blockchain Investigation and Transaction Tracing Platform",
                "Forensic fund-flow analysis and tracing suspicious transactions across wallets.",
                "SecureTrace",
            ),
            (
                "Blockchain Transaction Continuous Monitoring and Alerting",
                "Continuous monitoring of smart contract activity with anomaly detection and real-time alerts.",
                "SecureWatch",
            ),
            # Rule 3: SecureCMS vs CookieHub
            (
                "Website Cookie Consent and Tracking-Script Management System",
                "Collecting website user consent and controlling analytics tracking scripts based on user consent.",
                "CookieHub",
            ),
            (
                "Enterprise User Consent Management and Privacy Compliance Platform",
                "Tracking user consent records, consent withdrawal, and privacy audit compliance logs.",
                "SecureCMS",
            ),
            # Rule 4: SecureX-DID vs SecureX-ID
            (
                "Decentralized Identity and Verifiable Credentials Issuance System",
                "Issuance, storage, presentation, and verification of W3C verifiable credentials.",
                "SecureX-DID",
            ),
            (
                "Web3 Identity Verification and KYC/AML Compliance Solution",
                "Identity verification, AML screening, watchlist checks, and X-ID score risk assessment.",
                "SecureX-ID",
            ),
            # Rule 5: PQCSuite vs QuantumVault
            (
                "Post-Quantum Cryptography Migration and Crypto Agility Software",
                "Flexible cryptographic layer for post-quantum algorithm migration.",
                "PQCSuite",
            ),
            (
                "Hardware-Backed Cryptographic Key Protection and HSM Management",
                "Hardware security module (HSM) based key generation, storage, and access control.",
                "QuantumVault",
            ),
        ],
    )
    def test_genuine_pair_bid_still_ranks_the_right_product_first(
        self, db, title, scope, expected_top
    ):
        results = match_bid_against_products(db, _bid(db, title, scope))
        top = results[0]
        assert top.product_name == expected_top
        assert top.relevance_score > 0.0
        assert top.match_state in ("MATCH", "POSSIBLE_MATCH")

    def test_aml_phrase_and_defi_phrase_still_score(self, db):
        aml = match_bid_against_products(
            db,
            _bid(
                db,
                "AML compliance and AML screening platform for onboarding",
                "KYC/AML verification, watchlist screening and risk scoring",
            ),
        )
        assert _top(aml, "SecureX-ID").relevance_score > 0.0

        defi = match_bid_against_products(
            db,
            _bid(
                db,
                "Security audit of DeFi protocol and DeFi platform contracts",
                "Smart contract review for a decentralised DeFi lending protocol",
            ),
        )
        assert _top(defi, "SecurePad").relevance_score > 0.0