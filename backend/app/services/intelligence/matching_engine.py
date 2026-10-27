"""
Deterministic Bid-to-Product Matching Engine.

Analyzes normalized bid content against SecuredApp's Product Knowledge Layer.
Does NOT use LLMs, embeddings, or external AI APIs.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.models.bid import Bid
from app.models.product import Product
from app.services.boq_text import boq_evidence_text

# ---------------------------------------------------------------------------
# Token-aware term matching
# ---------------------------------------------------------------------------
# Product capabilities/keywords are matched against bid text as whole terms or
# consecutive phrases. Plain substring containment would let a short term such
# as "aml" fire inside "seamless"/"hamla" or "defi" inside "defibrillator",
# which manufactures false relevance. Terms therefore only match on word
# boundaries, and multi-word terms only as a consecutive phrase (allowing the
# punctuation that normally joins words: "kyc/aml", "anti-money laundering").
_WORD_JOIN = r"[\s\-_/,;:|()\[\]]+"


@lru_cache(maxsize=8192)
def _term_pattern(term: str) -> Optional[re.Pattern]:
    """Compiled word-boundary pattern for a (lower-cased) capability/keyword."""
    tokens = [t for t in term.strip().lower().split() if t]
    if not tokens:
        return None
    body = _WORD_JOIN.join(re.escape(t) for t in tokens)
    return re.compile(r"(?<!\w)" + body + r"(?!\w)")


def term_in_text(text: str, term: str) -> Optional[re.Match]:
    """Return the match when ``term`` occurs in ``text`` as a whole term/phrase."""
    if not text or not term:
        return None
    pattern = _term_pattern(term.strip().lower())
    if pattern is None:
        return None
    return pattern.search(text.lower())


def text_contains_term(text: str, term: str) -> bool:
    """True when ``term`` occurs in ``text`` as a whole term/phrase."""
    return term_in_text(text, term) is not None


# Separators treated as word breaks when judging whether a catalogue term is a
# lone token or a multi-word phrase. Mirrors the join characters in
# ``_WORD_JOIN`` so "Crypto-agility", "X-ID Score" and "kyc/aml" normalize the
# same way they match.
_TERM_SEPARATORS = re.compile(r"[\s\-_/,;:|()\[\]]+")


def _normalize_term(term: Optional[str]) -> str:
    """Lower-case a catalogue term and collapse separators to single spaces."""
    return _TERM_SEPARATORS.sub(" ", (term or "").strip().lower()).strip()


# ---------------------------------------------------------------------------
# Default Configurable Weights
# ---------------------------------------------------------------------------
FIELD_WEIGHTS: Dict[str, float] = {
    "title": 3.0,
    "scope_of_work": 2.5,
    "technical_requirements": 2.0,
    "category": 1.5,
    "eligibility_criteria": 1.0,
    "qualification_requirements": 1.0,
    "experience_requirements": 1.0,
    "certification_requirements": 1.0,
}

SIGNAL_WEIGHTS: Dict[str, float] = {
    "STRONG": 1.0,
    "MODERATE": 0.5,
    "WEAK": 0.2,
    "EXCLUSION": -1.5,
}

# Normalisation denominator for the raw signal total. Each matched capability or
# keyword phrase now contributes exactly once per field (duplicates and nested
# overlaps are collapsed before scoring), so the denominator that maps a
# realistic full match onto the 0-1 scale is 6.0. This keeps every previously
# genuine match in the same band it earned while stopping a single duplicated
# phrase from being counted twice.
NORMALIZATION_DENOMINATOR = 6.0

# Fields that carry *technical* procurement evidence. A single ambiguous term
# seen only in the weak descriptive fields (title / scope_of_work / category)
# is not enough to justify a MATCH; see ``_apply_context_gate``.
_TECHNICAL_EVIDENCE_FIELDS = frozenset({
    "technical_requirements",
    "eligibility_criteria",
    "qualification_requirements",
    "experience_requirements",
    "certification_requirements",
})

# Single tokens that collide with everyday language and therefore do not, on
# their own, prove a product is in scope ("Cookies" on a canteen supply list,
# "Staking" as a physical tool, "DID" as the past tense of "do"). Two distinct
# terms only count as contextual evidence when at least one of them is NOT in
# this set, so "staking" + "lending" stays ambiguous while the specific
# acronyms "KYC" + "AML" do not. Only single-token catalogue terms can ever
# appear in a signal, so entries a given catalogue does not use are harmless.
_AMBIGUOUS_TERMS = frozenset({
    "cookies", "did", "web3", "defi", "trading", "staking", "lending",
    "borrowing", "governance", "token", "consent", "privacy", "monitoring",
    "security", "wallet", "blockchain",
})

# Ceiling applied when the only evidence is a single ambiguous term with no
# contextual/technical support. Kept below the POSSIBLE_MATCH boundary (0.45)
# and above NEEDS_REVIEW (0.25), matching the existing conflict-demotion cap so
# the bid still surfaces for human review but can never be auto-matched.
_UNCONTEXTUAL_CAP = 0.3999

# Product scope anchors.
#
# A capability/keyword match is only meaningful inside the product's own domain.
# Generic security phrases ("security assessment", "monitoring", "key
# management") are deliberately shared across the catalogue, so on their own
# they can lift an unrelated bid into a product's score - the real
# "Penetration Testing and Security Assessment Software" bid matched
# AuditExpress purely on the phrase "security assessment". A product whose bid
# evidence carries none of its own anchor terms is therefore reported as
# NO_MATCH with its evidence preserved, never silently boosted.
#
# Anchors are matched as whole terms/phrases (word-boundary, plural-tolerant)
# against the combined bid text. Products without an entry here - notably
# administrator-created products - are never scope-gated.
_SCOPE_ANCHORS: Dict[str, tuple] = {
    "SolidityShield": ("smart contract", "solidity", "evm", "reentrancy",
                        "cyber security", "information security", "it security",
                        "vulnerability", "penetration", "vapt",
                        "security audit", "application security", "web application security"),
    "AuditExpress": ("smart contract", "solidity", "evm",
                      "cyber security", "information security", "it security",
                      "vulnerability", "penetration", "vapt",
                      "security audit", "application security", "web application security"),
    "SecureTrace": (
        "blockchain", "wallet", "forensic", "tracing", "fund flow",
        "crypto transaction", "cryptocurrency",
    ),
    "SecureWatch": (
        "blockchain", "transaction monitoring", "smart contract monitoring",
        "continuous monitoring", "anomaly", "token movement",
    ),
    "SecureCMS": ("consent", "privacy"),
    "CookieHub": ("cookie", "tracking script", "website consent", "consent collection"),
    "PQCSuite": (
        "post quantum", "pqc", "quantum resistant", "crypto agility",
        "cryptographic agility", "algorithm migration", "cryptographic migration",
    ),
    "SecureX-DID": (
        "decentralized identity", "decentralized identifier", "verifiable credential",
        "identity wallet", "web3 identity", "decentralized credential",
    ),
    "SecureX-ID": (
        "identity verification", "kyc", "aml", "fraud", "watchlist",
        "web3 compliance", "defi compliance", "x-id", "x id score", "identity compliance",
    ),
    "SecurePad": (
        "web3", "defi", "decentralized finance", "token", "staking",
        "lending", "borrowing", "governance",
    ),
    "QuantumVault": (
        "hsm", "hardware security module", "hardware backed", "key management",
        "key protection", "key generation", "key storage", "key rotation",
        "key revocation", "cryptographic key", "access control",
        "certificate", "pki",
    ),
}


def classify_score(score: float, threshold: Optional[float] = None) -> str:
    """Canonical score classification rule for a normalized 0.0-1.0 score.

    With no threshold this keeps the engine's existing four-band rule. When a
    single relevance threshold is configured (``MATCHING_RELEVANCE_THRESHOLD``)
    or passed explicitly, classification collapses to a binary decision at that
    cutoff on the same 0-1 scale: ``score >= threshold`` -> MATCH, else
    NO_MATCH. The scoring itself is untouched; only the label changes.
    """
    score = round(max(0.0, min(1.0, score)), 4)
    if threshold is None:
        from app.core.config import settings

        threshold = getattr(settings, "MATCHING_RELEVANCE_THRESHOLD", None)
    if threshold is not None:
        return "MATCH" if score >= float(threshold) else "NO_MATCH"
    if score >= 0.70:
        return "MATCH"
    elif score >= 0.45:
        return "POSSIBLE_MATCH"
    elif score >= 0.25:
        return "NEEDS_REVIEW"
    return "NO_MATCH"


class ProductMatchResult:
    def __init__(
        self,
        product_id: str,
        product_name: str,
        match_state: str,  # MATCH, POSSIBLE_MATCH, NEEDS_REVIEW, NO_MATCH
        relevance_score: float,  # 0.0 to 1.0
        confidence: float,
        signals: List[Dict[str, Any]],
        score_breakdown: Dict[str, Any],
        reason: str,
    ):
        self.product_id = product_id
        self.product_name = product_name
        self.relevance_score = max(0.0, min(1.0, relevance_score))
        self.match_state = classify_score(self.relevance_score)
        self.confidence = confidence
        self.signals = signals
        self.score_breakdown = score_breakdown
        self.reason = reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "product_id": str(self.product_id),
            "product_name": self.product_name,
            "match_state": self.match_state,
            "relevance_score": round(self.relevance_score, 3),
            "final_relevance_score": round(self.relevance_score, 3),
            "confidence": round(self.confidence, 3),
            "signals": self.signals,
            "score_breakdown": self.score_breakdown,
            "reason": self.reason,
        }



class BidMatcherEngine:
    def __init__(
        self,
        field_weights: Optional[Dict[str, float]] = None,
        signal_weights: Optional[Dict[str, float]] = None,
    ):
        self.field_weights = field_weights or FIELD_WEIGHTS
        self.signal_weights = signal_weights or SIGNAL_WEIGHTS

    def analyze_bid(self, db: Session, bid: Bid) -> List[ProductMatchResult]:
        """
        Analyze a bid against all active products in the DB and return sorted match results.

        Only `active` products are evaluated. The knowledge bootstrap below is a
        first-run convenience for a completely empty catalogue; it is guarded on
        the table being empty so that products an administrator has deliberately
        deactivated are never silently resurrected.
        """
        products = db.query(Product).filter(Product.active == True).all()
        if not products and db.query(Product).count() == 0:
            from app.db.seed_knowledge import seed_product_knowledge
            seed_product_knowledge(db)
            products = db.query(Product).filter(Product.active == True).all()

        bid_text_map = self._extract_bid_texts(bid)


        results: List[ProductMatchResult] = []

        for product in products:
            res = self._match_single_product(bid, bid_text_map, product)
            results.append(res)

        # Apply Product Differentiation pass across pairs
        results = self._apply_product_differentiation(bid_text_map, results)

        # Final evidence-quality gate: differentiation must not be able to lift a
        # bid whose only support is a single ambiguous descriptive term back over
        # the match boundary.
        results = self._apply_context_gate(results)

        # Sort by relevance_score descending
        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results

    def _dedupe_field_texts(self, text_map: Dict[str, str]) -> Dict[str, str]:
        """Blank a field whose text is identical to a higher-weighted field.

        Real GeM bids frequently carry the same string in both ``title`` and
        ``scope_of_work`` (the adapter copies one into the other). Scoring both
        counts every matched phrase twice for the same piece of evidence, which
        inflates the raw score. Only the highest-weighted copy is scored; the
        lower-weighted duplicate is blanked (never removed) so every field key
        remains addressable.
        """
        ordered = sorted(
            self.field_weights, key=lambda f: self.field_weights[f], reverse=True
        )
        seen: set = set()
        deduped = dict(text_map)
        for field in ordered:
            text = (text_map.get(field) or "").strip()
            if not text:
                continue
            if text in seen:
                deduped[field] = ""
            else:
                seen.add(text)
        return deduped

    def _has_contextual_evidence(self, signals: List[Dict[str, Any]]) -> bool:
        """True when a match is backed by evidence beyond a lone everyday token.

        Contextual/technical evidence is any of:
          * a multi-word phrase (a real capability/keyword, not a lone token),
            including hyphen/slash compounds such as "Crypto-agility";
          * a signal found in a technical field;
          * at least two distinct positive terms, provided at least one of them
            is specific rather than a common/off-domain token. Two ambiguous
            single words ("staking" + "lending") are still not enough, while a
            specific pair ("KYC" + "AML") is.
        """
        positive = [s for s in signals if s.get("strength") != "EXCLUSION"]
        if not positive:
            return False
        distinct: set = set()
        for sig in positive:
            term = _normalize_term(sig.get("text"))
            if term:
                distinct.add(term)
            if term and len(term.split()) >= 2:
                return True
            if sig.get("field") in _TECHNICAL_EVIDENCE_FIELDS:
                return True
        if len(distinct) < 2:
            return False
        return any(term not in _AMBIGUOUS_TERMS for term in distinct)

    def _apply_context_gate(
        self, results: List[ProductMatchResult]
    ) -> List[ProductMatchResult]:
        """Cap matches whose only evidence is a single ambiguous descriptive term.

        This never removes evidence: the raw/normalized scores and the signal
        list stay intact for audit. Only the final relevance (and therefore the
        classification/confidence) is capped, and the reason records why.
        """
        for r in results:
            if r.score_breakdown.get("scope_gate"):
                continue
            if r.relevance_score <= 0.0:
                continue
            if self._has_contextual_evidence(r.signals):
                continue
            capped = round(min(r.relevance_score, _UNCONTEXTUAL_CAP), 4)
            if capped >= r.relevance_score:
                continue
            r.relevance_score = capped
            r.match_state = classify_score(capped)
            r.confidence = min(1.0, 0.5 + (capped * 0.5))
            r.reason = (
                r.reason
                + " Context gate: insufficient contextual/technical evidence "
                "(only ambiguous everyday terms); capped below the match boundary."
            )
            r.score_breakdown["context_gate"] = "INSUFFICIENT_CONTEXT"
            r.score_breakdown["final_relevance_score"] = round(capped, 3)
            r.score_breakdown["classification"] = r.match_state
            r.score_breakdown["confidence"] = round(r.confidence, 3)
            r.score_breakdown["reason"] = r.reason
        return results

    def _extract_bid_texts(self, bid: Bid) -> Dict[str, str]:
        """Extract clean text for each weighted bid field."""
        def _textify(val: Any) -> str:
            if val is None:
                return ""
            if isinstance(val, str):
                return val.lower()
            if isinstance(val, (dict, list)):
                import json
                return json.dumps(val).lower()
            return str(val).lower()

        # The public listing truncates the item list, so the authoritative BoQ
        # line items (if fetched) are the real scope of work. They are folded
        # into the existing ``scope_of_work`` evidence channel only -- no new
        # weight, field, rule or threshold is introduced. When absent (the
        # default for every bid without BoQ evidence) this is byte-identical to
        # the previous behaviour.
        scope_text = _textify(bid.scope_of_work)
        boq_text = boq_evidence_text(getattr(bid, "boq_items", None))
        if boq_text and boq_text not in scope_text:
            scope_text = f"{scope_text} {boq_text}".strip()

        return {
            "title": _textify(bid.title),
            "scope_of_work": scope_text,
            "technical_requirements": _textify(bid.technical_requirements),
            "category": _textify(bid.category),
            "eligibility_criteria": _textify(bid.eligibility_criteria),
            "qualification_requirements": _textify(bid.qualification_requirements),
            "experience_requirements": _textify(bid.experience_requirements),
            "certification_requirements": _textify(bid.certification_requirements),
        }

    def _match_single_product(
        self,
        bid: Bid,
        text_map: Dict[str, str],
        product: Product,
    ) -> ProductMatchResult:
        # Collect every raw capability/keyword match first, then collapse
        # duplicates and nested overlaps before scoring. A catalogue that lists
        # the same phrase as both a capability and a keyword (or a short keyword
        # such as "reentrancy" inside the capability "reentrancy detection") must
        # not be counted twice for one bid field.
        #
        # The same reasoning applies across fields: real GeM bids carry the
        # identical string in both ``title`` and ``scope_of_work``, so scoring
        # both would count every matched phrase twice. Identical lower-weighted
        # fields are blanked before matching.
        field_texts = self._dedupe_field_texts(text_map)
        candidates: List[Dict[str, Any]] = []

        def _collect(field: str, term: str, points: float, strength: str,
                     span: tuple, sig_type: str, is_exclusion: bool) -> None:
            candidates.append({
                "type": sig_type,
                "text": term,
                "field": field,
                "strength": strength,
                "weight": round(points, 4),
                "snippet": self._extract_snippet(field_texts[field], term),
                "_points": points,
                "_start": span[0],
                "_end": span[1],
                "_is_exclusion": is_exclusion,
            })

        # 1. Match Capabilities
        for cap in product.capabilities:
            if not cap.active:
                continue
            cap_lower = cap.name.lower()
            for field, field_text in field_texts.items():
                if not field_text:
                    continue
                match = term_in_text(field_text, cap_lower)
                if match is not None:
                    strength = "STRONG" if field in ("title", "scope_of_work") else "MODERATE"
                    points = cap.weight * self.field_weights[field] * self.signal_weights[strength]
                    _collect(field, cap.name, points, strength, match.span(), "capability", False)

        # 2. Match Keywords & Positive / Exclusion Signals
        for kw in product.keywords:
            if not kw.active:
                continue
            kw_lower = kw.keyword.lower()
            for field, field_text in field_texts.items():
                if not field_text:
                    continue
                match = term_in_text(field_text, kw_lower)
                if match is None:
                    continue
                if kw.type == "exclusion":
                    strength = "EXCLUSION"
                    # Stored exclusion weights are already negative, so the
                    # signal weight's negative sign would cancel them and
                    # raise the score for a keyword that means "not this
                    # product". Use the magnitude and let SIGNAL_WEIGHTS
                    # supply the single negative sign.
                    points = (
                        abs(kw.weight)
                        * self.field_weights[field]
                        * self.signal_weights["EXCLUSION"]
                    )
                    # Exclusions are never collapsed: dropping one would erase a
                    # deliberate disqualification.
                    _collect(field, kw.keyword, points, strength, match.span(), kw.type, True)
                elif kw.type == "positive_signal":
                    strength = "STRONG" if field in ("title", "scope_of_work") else "MODERATE"
                    points = kw.weight * self.field_weights[field] * self.signal_weights[strength]
                    _collect(field, kw.keyword, points, strength, match.span(), kw.type, False)
                else:
                    strength = "WEAK" if len(kw_lower.split()) == 1 else "MODERATE"
                    points = kw.weight * self.field_weights[field] * self.signal_weights[strength]
                    _collect(field, kw.keyword, points, strength, match.span(), kw.type, False)

        # 3. Collapse duplicate / overlapping signals within the same field: the
        #    strongest (highest-point) signal wins, and an identical or nested
        #    weaker one adds nothing.
        kept: List[Dict[str, Any]] = []
        for cand in candidates:
            if cand["_is_exclusion"]:
                kept.append(cand)
                continue
            overlapping = [
                k
                for k in kept
                if not k["_is_exclusion"]
                and k["field"] == cand["field"]
                and k["_start"] < cand["_end"]
                and cand["_start"] < k["_end"]
            ]
            if not overlapping:
                kept.append(cand)
                continue
            best = max(overlapping, key=lambda k: k["_points"])
            if cand["_points"] > best["_points"]:
                kept.remove(best)
                kept.append(cand)

        signals: List[Dict[str, Any]] = []
        field_scores: Dict[str, float] = {f: 0.0 for f in self.field_weights}
        for c in kept:
            field_scores[c["field"]] += c["_points"]
            signals.append({
                "type": c["type"],
                "text": c["text"],
                "field": c["field"],
                "strength": c["strength"],
                # Recorded so the score breakdown can explain the total.
                "weight": c["weight"],
                "snippet": c["snippet"],
            })

        # Compute Raw & Normalized Relevance Score
        raw_score = sum(field_scores.values())
        normalized_score = max(0.0, min(1.0, raw_score / NORMALIZATION_DENOMINATOR))

        # 4. Product scope gate: evidence that carries none of the product's own
        #    domain anchors is out of scope, so it is reported as NO_MATCH (with
        #    its signals preserved) instead of being allowed to score.
        scope_gate: Optional[str] = None
        if signals and not self._is_within_product_scope(product.name, text_map):
            raw_score = 0.0
            normalized_score = 0.0
            field_scores = {f: 0.0 for f in self.field_weights}
            scope_gate = "OUT_OF_SCOPE"
        # Evidence quality: keyword-only title/scope with clear domain conflict -> demote
        if not scope_gate and normalized_score > 0.0 and signals:
            tech = any(s.get('field') in ('technical_requirements','eligibility_criteria','qualification_requirements','experience_requirements','certification_requirements') for s in signals)
            only_ts = all(s.get('field') in ('title','scope_of_work') for s in signals)
            if only_ts and not tech:
                combined = ' '.join(text_map.values())
                conflicts = ['arboriculture','forestry','horticulture','landscaping','civil works','road works','bridge','building construction','irrigation','agriculture','farming','plantation','earthworks','excavation']
                if any(t in combined for t in conflicts):
                    normalized_score = min(normalized_score, 0.3999)
                    raw_score = normalized_score * NORMALIZATION_DENOMINATOR


        # State classification is centralized in classify_score (single source
        # of truth for every threshold), used below and in the result object.

        confidence = min(1.0, 0.5 + (normalized_score * 0.5))

        if scope_gate:
            reason = (
                f"Matched {len(signals)} signal(s) outside this product's scope; "
                f"relevance suppressed. Raw score: {round(raw_score, 2)}, "
                f"normalized relevance: {round(normalized_score, 2)}."
            )
        else:
            reason = (
                f"Matched {len(signals)} signal(s) across bid fields. "
                f"Raw score: {round(raw_score, 2)}, normalized relevance: {round(normalized_score, 2)}."
            )

        # Exclusion points are already negative (SIGNAL_WEIGHTS["EXCLUSION"] < 0), so
        # they lower the total. These two sums are the explanation of that total,
        # which is why every signal must carry its own "weight".
        pos_adj = sum(
            s.get("weight", 0.0) for s in signals if s.get("strength") != "EXCLUSION"
        )
        neg_adj = sum(
            s.get("weight", 0.0) for s in signals if s.get("strength") == "EXCLUSION"
        )

        score_breakdown = {
            "field_scores": {k: round(v, 2) for k, v in field_scores.items() if v != 0.0},
            "signal_scores": [s.get("strength") for s in signals],
            "positive_adjustments": round(pos_adj, 2),
            "negative_exclusion_adjustments": round(neg_adj, 2),
            "raw_score": round(raw_score, 2),
            "normalized_score": round(normalized_score, 3),
            "final_relevance_score": round(normalized_score, 3),
            "classification": classify_score(normalized_score),
            "confidence": round(confidence, 3),
            "scope_gate": scope_gate,
            "reason": reason,
        }


        return ProductMatchResult(
            product_id=str(product.id),
            product_name=product.name,
            match_state=classify_score(normalized_score),
            relevance_score=normalized_score,
            confidence=confidence,
            signals=signals,
            score_breakdown=score_breakdown,
            reason=reason,
        )


    def _apply_product_differentiation(
        self,
        text_map: Dict[str, str],
        results: List[ProductMatchResult],
    ) -> List[ProductMatchResult]:
        """
        Applies explicit differentiation rules between closely related product pairs.

        Differentiation only *refines* comparisons that already have a footing in
        real bid evidence. It must never manufacture a product match: the rule
        trigger terms include generic words (``expert review``, ``investigation``,
        ``forensic``, ``tracing``, ``cookie``, ``did``, ``hsm``, ...) that are
        shared with everyday language but carry no product meaning on their own.
        Boosting SecureTrace because a bid says "forensic" fills a matched-product
        panel with a product the bid never actually requested.

        Every boost is therefore gated on the boosted product already carrying a
        positive relevance score from its own keywords/capabilities (real signals).
        With a zero base there is nothing to differentiate, so the rule is skipped
        and the paired demotion is skipped with it. Genuine matches are untouched:
        a product that earned its score still receives the same tie-break, and the
        stored score record stays internally consistent (final relevance =
        normalized raw score + recorded differentiation adjustment).
        """
        combined_text = " ".join(text_map.values())
        res_by_name = {r.product_name: r for r in results}

        # Pre-differentiation relevance is the evidence base. A rule may only
        # boost a product that already matched on its own keywords/capabilities.
        base_scores = {name: r.relevance_score for name, r in res_by_name.items()}
        # Net per-product delta applied by differentiation, kept in the breakdown
        # so explanation, adjustments and final score are consistent.
        adjustments = {name: 0.0 for name in res_by_name}

        def has(term: str) -> bool:
            """Whole-term/phrase presence, never an arbitrary substring."""
            return text_contains_term(combined_text, term)

        def _has_evidence(name: str) -> bool:
            """True when the product earned positive relevance on its own."""
            return base_scores.get(name, 0.0) > 0.0

        def _apply(name: str, delta: float, note: str) -> None:
            target = res_by_name[name]
            target.relevance_score = max(0.0, min(1.0, target.relevance_score + delta))
            adjustments[name] = round(adjustments[name] + delta, 4)
            if note:
                target.reason += " " + note

        # --- Rule 1: SolidityShield vs AuditExpress ---
        if "SolidityShield" in res_by_name and "AuditExpress" in res_by_name:
            if has("expert review") or has("manual review") or has("auditor validation"):
                if _has_evidence("SolidityShield"):
                    _apply("SolidityShield", 0.25, "Boosted for expert review & validation capability.")
                    _apply("AuditExpress", -0.20, "Demoted: AuditExpress is focused on rapid automated assessment.")

            elif has("rapid automated") or has("automated assessment only"):
                if _has_evidence("AuditExpress"):
                    _apply("AuditExpress", 0.25, "Boosted for rapid automated assessment focus.")

        # --- Rule 2: SecureTrace vs SecureWatch ---
        if "SecureTrace" in res_by_name and "SecureWatch" in res_by_name:
            if has("investigation") or has("forensic") or has("tracing"):
                if _has_evidence("SecureTrace"):
                    _apply("SecureTrace", 0.25, "Boosted for forensic investigation & fund flow tracing.")
                    _apply("SecureWatch", -0.20, "Demoted: SecureWatch focuses on continuous real-time monitoring.")

            elif has("continuous monitoring") or has("real-time alert") or has("abnormal token movement"):
                if _has_evidence("SecureWatch"):
                    _apply("SecureWatch", 0.25, "Boosted for continuous monitoring & alert generation.")
                    _apply("SecureTrace", -0.20, "Demoted: SecureTrace focuses on post-event tracing.")

        # --- Rule 3: SecureCMS vs CookieHub ---
        if "SecureCMS" in res_by_name and "CookieHub" in res_by_name:
            if has("cookie") or has("tracking script") or has("website script"):
                if _has_evidence("CookieHub"):
                    _apply("CookieHub", 0.30, "Boosted for website cookie and script-consent focus.")
                    _apply("SecureCMS", -0.25, "Demoted: SecureCMS focuses on enterprise user privacy records.")

            elif has("user consent records") or has("privacy compliance records"):
                if _has_evidence("SecureCMS"):
                    _apply("SecureCMS", 0.25, "Boosted for user consent and privacy compliance record management.")

        # --- Rule 4: SecureX-DID vs SecureX-ID ---
        if "SecureX-DID" in res_by_name and "SecureX-ID" in res_by_name:
            if has("verifiable credential") or has("did") or has("identity wallet"):
                if _has_evidence("SecureX-DID"):
                    _apply("SecureX-DID", 0.30, "Boosted for decentralized identity & verifiable credential focus.")

            if has("kyc") or has("aml") or has("x-id score") or has("watchlist"):
                if _has_evidence("SecureX-ID"):
                    _apply("SecureX-ID", 0.30, "Boosted for KYC/AML identity verification and risk scoring.")

        # --- Rule 5: PQCSuite vs QuantumVault ---
        if "PQCSuite" in res_by_name and "QuantumVault" in res_by_name:
            if has("crypto agility") or has("algorithm migration"):
                if _has_evidence("PQCSuite"):
                    _apply("PQCSuite", 0.30, "Boosted for cryptographic agility and algorithm migration.")

            if has("hsm") or has("hardware backed") or has("hardware key"):
                if _has_evidence("QuantumVault"):
                    _apply("QuantumVault", 0.30, "Boosted for hardware-backed key protection & HSM concepts.")

        # Re-evaluate match state for all after differentiation adjustments
        for r in results:
            r.relevance_score = max(0.0, min(1.0, r.relevance_score))
            r.match_state = classify_score(r.relevance_score)
            r.confidence = min(1.0, 0.5 + (r.relevance_score * 0.5))

            # Ensure explanation string matches final relevance score. The raw
            # score is the pre-differentiation signal total; the differentiation
            # delta is recorded separately so the two stay linked and auditable.
            raw = r.score_breakdown.get("raw_score", 0.0)
            base_reason = (
                f"Matched {len(r.signals)} signal(s) across bid fields. "
                f"Raw score: {raw}, final relevance: {round(r.relevance_score, 3)} ({r.match_state})."
            )
            # Append differentiation notes if any were appended to r.reason
            if "Boosted" in r.reason or "Demoted" in r.reason:
                notes = [part.strip() for part in r.reason.split(".") if "Boosted" in part or "Demoted" in part]
                if notes:
                    base_reason += " " + ". ".join(notes) + "."

            r.reason = base_reason
            r.score_breakdown["normalized_score"] = round(max(0.0, min(1.0, raw / NORMALIZATION_DENOMINATOR)), 3)
            r.score_breakdown["differentiation_adjustments"] = round(adjustments[r.product_name], 4)
            r.score_breakdown["final_relevance_score"] = round(r.relevance_score, 3)
            r.score_breakdown["classification"] = r.match_state
            r.score_breakdown["confidence"] = round(r.confidence, 3)
            r.score_breakdown["reason"] = r.reason

        return results

    def _is_within_product_scope(self, product_name: str, text_map: Dict[str, str]) -> bool:
        """True when the bid text carries at least one of the product's anchors.

        Products without a configured anchor list (e.g. administrator-created
        products) are never scope-gated and this always returns True.
        """
        anchors = _SCOPE_ANCHORS.get(product_name)
        if not anchors:
            return True
        combined = " ".join(text_map.values())
        for anchor in anchors:
            if text_contains_term(combined, anchor) or text_contains_term(combined, anchor + "s"):
                return True
        return False

    def _extract_snippet(self, text: str, query: str, context_len: int = 40) -> str:
        match = term_in_text(text, query)
        if match is None:
            return query
        idx, end_idx = match.span()
        start = max(0, idx - context_len)
        end = min(len(text), end_idx + context_len)
        return text[start:end].strip()


def match_bid_against_products(db: Session, bid: Bid) -> List[ProductMatchResult]:
    """Helper function to run the bid matcher engine against a bid."""
    engine = BidMatcherEngine()
    return engine.analyze_bid(db, bid)
