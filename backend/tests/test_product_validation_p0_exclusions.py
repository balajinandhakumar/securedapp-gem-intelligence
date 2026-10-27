"""P0 exclusion fixes from the SecuredApp product validation report.

The audit (``docs/SECUREDAPP_PRODUCT_VALIDATION_REPORT.md`` §6–§7) found three
catalogue exclusions that contradict the vendor's own public product
documentation and therefore suppressed potentially relevant bids:

* **AuditExpress** penalised ``expert security review`` / ``manual audit
  review``, although the official Audit Express page states it "combines
  automated tools with manual reviews".
* **SecureTrace** penalised ``continuous monitoring`` / ``real-time alerts``,
  although the official SecureTrace page itself advertises "real-time
  monitoring".
* **PQCSuite** penalised ``hardware security module`` / ``hsm key storage``,
  although the official PQC Suite page advertises an "IoT & HSM" capability.

These tests pin the removal: the terms no longer lower the product's own score,
an unrelated tender carrying the terms is still not auto-matched, and every
other catalogue exclusion is preserved untouched.

All bids are synthetic and live only in the isolated in-memory test database --
nothing touches the real database.
"""
from __future__ import annotations

import pytest

from app.db.seed_knowledge import PRODUCTS_KNOWLEDGE, seed_product_knowledge
from app.models.bid import Bid
from app.services.intelligence import match_bid_against_products


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


def _exclusions(product_name):
    info = next(i for i in PRODUCTS_KNOWLEDGE if i["name"] == product_name)
    return [kw for kw, _weight, kind in info["keywords"] if kind == "exclusion"]


def _assert_no_exclusion_signal(result):
    assert all(s["strength"] != "EXCLUSION" for s in result.signals), (
        f"{result.product_name} still produced an exclusion signal: "
        f"{[s for s in result.signals if s['strength'] == 'EXCLUSION']}"
    )
    assert result.score_breakdown["negative_exclusion_adjustments"] == 0


# ---------------------------------------------------------------------------
# 1. The contradictory exclusions are gone from the seeded catalogue.
# ---------------------------------------------------------------------------
class TestContradictoryExclusionsRemoved:
    def test_auditexpress_has_no_review_exclusion(self):
        assert _exclusions("AuditExpress") == []

    def test_securetrace_has_no_monitoring_exclusion(self):
        assert _exclusions("SecureTrace") == []

    def test_pqcsuit_has_no_hsm_exclusion(self):
        assert _exclusions("PQCSuite") == []


# ---------------------------------------------------------------------------
# 2. The terms no longer suppress a potentially relevant bid.
# ---------------------------------------------------------------------------
class TestTermsNoLongerSuppressRelevantBids:
    def test_manual_audit_review_does_not_suppress_auditexpress(self, db):
        # Genuine smart-contract scope plus the formerly-excluded phrase.
        results = match_bid_against_products(
            db,
            _bid(
                db,
                "Automated Security Assessment for Smart Contracts",
                "Rapid automated security assessment and vulnerability scanning "
                "for smart contract posture, including a manual audit review.",
            ),
        )
        audit = _top(results, "AuditExpress")
        _assert_no_exclusion_signal(audit)
        assert audit.relevance_score >= 0.45, (
            "AuditExpress must not be pushed below POSSIBLE_MATCH by the "
            f"manual-review phrase (got {audit.relevance_score})"
        )

    def test_real_time_alerts_do_not_suppress_securetrace(self, db):
        results = match_bid_against_products(
            db,
            _bid(
                db,
                "Blockchain Investigation Platform",
                "Real-time alerts for suspicious transactions.",
            ),
        )
        trace = _top(results, "SecureTrace")
        _assert_no_exclusion_signal(trace)
        assert trace.relevance_score >= 0.45, (
            "SecureTrace must not be pushed below POSSIBLE_MATCH by the "
            f"real-time-alerts phrase (got {trace.relevance_score})"
        )

    def test_hardware_security_module_does_not_suppress_pqcsuit(self, db):
        results = match_bid_against_products(
            db,
            _bid(
                db,
                "Post-Quantum Cryptography Readiness",
                "Integration with our hardware security module to protect "
                "quantum-resistant keys.",
            ),
        )
        pqc = _top(results, "PQCSuite")
        _assert_no_exclusion_signal(pqc)
        assert pqc.relevance_score >= 0.45, (
            "PQCSuite must not be pushed below POSSIBLE_MATCH by the HSM "
            f"phrase (got {pqc.relevance_score})"
        )


# ---------------------------------------------------------------------------
# 3. Removing the exclusions must not auto-match unrelated tenders that merely
#    contain the same terms.
# ---------------------------------------------------------------------------
class TestNegativeContextStillSafe:
    def test_unrelated_manual_audit_review_is_not_a_match(self, db):
        results = match_bid_against_products(
            db,
            _bid(db, "Manual audit review of catering and housekeeping invoices"),
        )
        audit = _top(results, "AuditExpress")
        assert audit.relevance_score == 0.0
        assert audit.match_state == "NO_MATCH"
        assert all(r.match_state != "MATCH" for r in results)

    def test_unrelated_real_time_alerts_is_not_a_match(self, db):
        # "continuous monitoring" is also a legitimate SecureWatch keyword, so
        # this bid may match SecureWatch (unrelated to this fix). What matters
        # is that removing SecureTrace's exclusions does not make *SecureTrace*
        # match a non-blockchain tender.
        results = match_bid_against_products(
            db,
            _bid(
                db,
                "Real-time alerts and continuous monitoring of building fire "
                "safety systems",
            ),
        )
        trace = _top(results, "SecureTrace")
        assert trace.relevance_score == 0.0
        assert trace.match_state == "NO_MATCH"

    def test_hsm_appliance_matches_quantumvault(self, db):
        results = match_bid_against_products(
            db,
            _bid(
                db,
                "Supply of HSM hardware security module appliance for the data centre",
            ),
        )
        # HSM hardware-backed key protection is QuantumVault's core domain, so an
        # HSM appliance tender is a genuine QuantumVault opportunity.
        qv = _top(results, "QuantumVault")
        assert qv.match_state in ("MATCH", "POSSIBLE_MATCH")
        assert qv.relevance_score > 0.0
        # PQCSuite has no HSM keyword/capability, so it must not claim the bid.
        pqc = _top(results, "PQCSuite")
        assert pqc.relevance_score == 0.0
        assert pqc.match_state == "NO_MATCH"


# ---------------------------------------------------------------------------
# 4. No unrelated exclusion was removed: the rest of the catalogue is intact.
# ---------------------------------------------------------------------------
class TestOtherExclusionsPreserved:
    EXPECTED_REMAINING = {
        ("SecureCMS", "tracking script"),
        ("SecureCMS", "cookie consent"),
        ("CookieHub", "privacy compliance records"),
        ("SecureX-DID", "kyc aml verification"),
        ("SecureX-DID", "x id score"),
        ("SecureWatch", "forensic investigation"),
        ("SecureWatch", "transaction tracing"),
        ("SecurePad", "generic blockchain development"),
        ("SecureX-ID", "verifiable credentials"),
        ("SecureX-ID", "decentralized identity did"),
        ("QuantumVault", "crypto agility software"),
    }

    def test_only_the_six_contradictory_exclusions_were_removed(self):
        remaining = {
            (info["name"], kw)
            for info in PRODUCTS_KNOWLEDGE
            for kw, _weight, kind in info["keywords"]
            if kind == "exclusion"
        }
        assert remaining == self.EXPECTED_REMAINING

    def test_unrelated_exclusions_still_fire(self, db):
        # A Cleanup/CookieHub bid: "tracking script" must still demote SecureCMS.
        results = match_bid_against_products(
            db,
            _bid(
                db,
                "Privacy compliance records and consent management platform",
                "Tracking script control and cookie consent for the website.",
            ),
        )
        cms = _top(results, "SecureCMS")
        assert any(s["strength"] == "EXCLUSION" for s in cms.signals)
        assert cms.score_breakdown["negative_exclusion_adjustments"] < 0
