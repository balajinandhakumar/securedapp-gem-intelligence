"""
Duplicate detection service for incoming bid records.

Provides exact duplicate detection by `gem_bid_id`, `bid_number`, or `content_hash`,
as well as candidate fuzzy duplicate detection based on title similarity and metadata.

Fuzzy policy
------------
Title similarity alone is never enough to suppress a record. Two GeM listings may
legitimately carry the same item title ("Chair for General Purpose") while being
different tenders, so a fuzzy candidate is only collapsed when corroborating
evidence says it is the same tender:

* both sides carry a GeM identity (``bid_number`` / ``gem_bid_id``) and they
  differ -> the records are distinct tenders, never collapsed;
* otherwise the fuzzy hit must be backed by identical source URL, or by the same
  organisation *and* the same closing date.

Exact bid-number / gem_bid_id / content-hash duplicates are unaffected.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session

from app.models.bid import Bid


class DuplicateCheckResult:
    def __init__(
        self,
        status: str,  # "EXACT_MATCH", "FUZZY_MATCH", "NEW"
        existing_bid: Optional[Bid] = None,
        confidence_score: float = 1.0,
        match_reason: Optional[str] = None,
        fuzzy_candidates: int = 0,
        fuzzy_rejected: int = 0,
    ):
        self.status = status
        self.existing_bid = existing_bid
        self.confidence_score = confidence_score
        self.match_reason = match_reason
        # Titles that reached the fuzzy threshold, whether or not they were
        # suppressed. Reported so runs can show fuzzy activity explicitly.
        self.fuzzy_candidates = fuzzy_candidates
        # Similar titles that were deliberately NOT suppressed (distinct tenders).
        self.fuzzy_rejected = fuzzy_rejected

    @property
    def is_exact(self) -> bool:
        return self.status == "EXACT_MATCH"

    @property
    def is_duplicate(self) -> bool:
        return self.status in ("EXACT_MATCH", "FUZZY_MATCH")


def _identity_values(*values: Any) -> set:
    """GeM identity values present among ``values`` (bid number / gem bid id)."""
    return {str(v).strip() for v in values if v is not None and str(v).strip()}


def _normalised_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).casefold()


def _same_closing_date(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    left = left.replace(tzinfo=None) if getattr(left, "tzinfo", None) else left
    right = right.replace(tzinfo=None) if getattr(right, "tzinfo", None) else right
    return left == right


def _identities_distinct(
    incoming_bid_number: Any,
    incoming_gem_id: Any,
    existing: Bid,
) -> bool:
    """True when both sides carry GeM identities and none of them overlap."""
    incoming = _identity_values(incoming_bid_number, incoming_gem_id)
    existing_ids = _identity_values(existing.bid_number, existing.gem_bid_id)
    if not incoming or not existing_ids:
        return False
    return not (incoming & existing_ids)


def _corroborating_evidence(normalized_data: Dict[str, Any], existing: Bid) -> bool:
    """Evidence beyond the title that the record is the very same tender."""
    incoming_source = normalized_data.get("source_url")
    if incoming_source and existing.source_url and incoming_source == existing.source_url:
        return True

    incoming_org = _normalised_text(normalized_data.get("organisation"))
    existing_org = _normalised_text(existing.organisation)
    if incoming_org and existing_org and incoming_org == existing_org:
        return _same_closing_date(normalized_data.get("closing_date"), existing.closing_date)
    return False


def check_duplicate(
    db: Session,
    normalized_data: Dict[str, Any],
    fuzzy_threshold: float = 0.88,
    *,
    use_bid_number_identity: bool = True,
) -> DuplicateCheckResult:
    """
    Checks if a normalized bid record already exists in the database.

    ``use_bid_number_identity`` is False for sources whose native identifier is
    not row-unique (see ``identity_fields``): those carry a derived composite
    ``gem_bid_id`` already, so the raw ``bid_number`` must **not** be treated as
    a unique identity (many distinct tenders can legitimately share one). When
    False, the exact ``bid_number`` lookup is skipped and identity falls back to
    the composite ``gem_bid_id`` and the content hash.
    """
    gem_bid_id = normalized_data.get("gem_bid_id")
    bid_number = normalized_data.get("bid_number")
    content_hash = normalized_data.get("hash")
    title = normalized_data.get("title")

    # 1. Exact match on gem_bid_id
    if gem_bid_id:
        existing = db.query(Bid).filter(Bid.gem_bid_id == gem_bid_id).first()
        if existing:
            return DuplicateCheckResult(
                status="EXACT_MATCH",
                existing_bid=existing,
                confidence_score=1.0,
                match_reason=f"Matched gem_bid_id: {gem_bid_id}",
            )

    # 2. Exact match on bid_number (only when it is a real unique identity)
    if bid_number and use_bid_number_identity:
        existing = db.query(Bid).filter(Bid.bid_number == bid_number).first()
        if existing:
            return DuplicateCheckResult(
                status="EXACT_MATCH",
                existing_bid=existing,
                confidence_score=1.0,
                match_reason=f"Matched bid_number: {bid_number}",
            )

    # 3. Exact match on content_hash
    if content_hash:
        existing = db.query(Bid).filter(Bid.content_hash == content_hash).first()
        if existing:
            return DuplicateCheckResult(
                status="EXACT_MATCH",
                existing_bid=existing,
                confidence_score=1.0,
                match_reason=f"Matched content_hash: {content_hash}",
            )

    # 4. Fuzzy match check if title is provided
    if title and len(title) > 10:
        # Candidate search: bids published recently (optimized column selection)
        candidates = (
            db.query(
                Bid.id,
                Bid.title,
                Bid.bid_number,
                Bid.gem_bid_id,
                Bid.organisation,
                Bid.closing_date,
                Bid.source_url,
            )
            .order_by(Bid.created_at.desc())
            .limit(100)
            .all()
        )
        fuzzy_candidates = 0
        fuzzy_rejected = 0
        for cand in candidates:
            cand_id, cand_title = cand[0], cand[1]
            if not cand_title:
                continue
            ratio = SequenceMatcher(None, title.lower(), cand_title.lower()).ratio()
            if ratio < fuzzy_threshold:
                continue

            fuzzy_candidates += 1

            if _identities_distinct(bid_number, gem_bid_id, cand):
                # Different GeM bid numbers: separate tenders that happen to
                # share an item title. Never collapsed.
                fuzzy_rejected += 1
                continue

            if not _corroborating_evidence(normalized_data, cand):
                fuzzy_rejected += 1
                continue

            matched_bid = db.get(Bid, cand_id)
            return DuplicateCheckResult(
                status="FUZZY_MATCH",
                existing_bid=matched_bid,
                confidence_score=round(ratio, 3),
                match_reason=f"Fuzzy title match ({round(ratio*100, 1)}%): '{cand_title[:50]}...'",
                fuzzy_candidates=fuzzy_candidates,
                fuzzy_rejected=fuzzy_rejected,
            )

        return DuplicateCheckResult(
            status="NEW",
            fuzzy_candidates=fuzzy_candidates,
            fuzzy_rejected=fuzzy_rejected,
        )

    return DuplicateCheckResult(status="NEW")
