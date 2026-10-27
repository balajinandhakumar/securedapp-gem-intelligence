"""Automatic, bounded BoQ enrichment for freshly collected GeM bids.

GeM's public listing truncates a bid's item list to ~99 characters in its
``data-content`` popover, so ``title`` / ``scope_of_work`` carry only a prefix of
the real scope. The authoritative line items are published as a CSV linked from
the bid document (see :mod:`app.services.ingestion.gem_boq_evidence`). This
module wires that *existing* fetch into the *existing* direct-collection
pipeline, so a freshly collected bid can be enriched before the 11-product
matching engine runs. It introduces no new collection, fetching or matching
architecture.

Safety properties (all enforced here):

* **Off unless enabled.** Like the optional detail-page enrichment, it performs
  per-bid network calls and only runs when ``GEM_BOQ_AUTO_ENRICH_ENABLED`` is set.
* **Bounded.** At most ``GEM_BOQ_AUTO_ENRICH_MAX_PER_RUN`` bids are attempted per
  collection run; the rest stay eligible for a later run.
* **Idempotent / no repeated fetches.** A bid is skipped when it already carries
  BoQ evidence, and a bid is attempted at most once because the attempt is
  recorded on ``Bid.boq_checked_at`` even when no CSV is found.
* **Failure-isolated.** Any fetch / parse / network error is logged and the bid
  continues through the pipeline with the data it already had.

The manual CLI (``scripts/enrich_bid_boq.py``) is unchanged and keeps using the
same ``enrich_bid_from_source`` service.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.core.config import settings
from app.services.ingestion.gem_boq_evidence import (
    BoQEvidenceError,
    enrich_bid_from_source,
)

logger = logging.getLogger(__name__)

# The bid document endpoint whose linked CSV carries the line items. Other
# allowlisted GeM pages (the listing, the mkp document hosts) never do.
_BID_DOCUMENT_PATH_MARKER = "showbiddocument"


def is_gem_bid_document_url(source_url: Optional[str]) -> bool:
    """True when ``source_url`` is a GeM bid document that can carry a BoQ CSV."""
    if not source_url:
        return False
    try:
        parsed = urlparse(str(source_url).strip())
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    if host != "gem.gov.in" and not host.endswith(".gem.gov.in"):
        return False
    return _BID_DOCUMENT_PATH_MARKER in path


def enrich_collected_bids(
    bids: List[Any],
    *,
    max_per_run: Optional[int] = None,
    session: Any = None,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """
    Enrich a bounded number of just-collected bids with BoQ evidence.

    Returns a counter dict ``{eligible, attempted, enriched, skipped, failed}``.
    Never raises: every failure is logged and the bid is left untouched apart
    from its attempt marker. Does not commit -- the caller commits.
    """
    summary = {"eligible": 0, "attempted": 0, "enriched": 0, "skipped": 0, "failed": 0}

    if not bool(getattr(settings, "GEM_BOQ_AUTO_ENRICH_ENABLED", False)):
        return summary

    if max_per_run is None:
        try:
            max_per_run = int(getattr(settings, "GEM_BOQ_AUTO_ENRICH_MAX_PER_RUN", 25) or 0)
        except (TypeError, ValueError):
            max_per_run = 25
    budget = max(0, int(max_per_run or 0))

    moment = now or datetime.now(timezone.utc)

    for bid in bids:
        # Already has authoritative evidence, or was already attempted once.
        if (
            getattr(bid, "boq_items", None) is not None
            or getattr(bid, "boq_checked_at", None) is not None
        ):
            summary["skipped"] += 1
            continue
        if not is_gem_bid_document_url(getattr(bid, "source_url", None)):
            summary["skipped"] += 1
            continue

        summary["eligible"] += 1
        if budget and summary["attempted"] >= budget:
            # Budget exhausted: leave the rest untouched (still NULL, so they
            # stay eligible next run) rather than exceed the cap.
            continue

        summary["attempted"] += 1
        # Record the attempt up-front so a later run never re-fetches this bid,
        # even if the fetch below fails or finds no CSV.
        bid.boq_checked_at = moment
        try:
            outcome = enrich_bid_from_source(bid, session=session)
            if outcome.get("changed"):
                summary["enriched"] += 1
        except BoQEvidenceError as exc:
            summary["failed"] += 1
            logger.info(
                "BoQ auto-enrichment found no usable evidence for %s: %s",
                getattr(bid, "gem_bid_id", None) or getattr(bid, "id", None),
                exc,
            )
        except Exception as exc:  # noqa: BLE001 - enrichment must never break collection
            summary["failed"] += 1
            logger.warning(
                "BoQ auto-enrichment failed for %s: %s: %s",
                getattr(bid, "gem_bid_id", None) or getattr(bid, "id", None),
                type(exc).__name__,
                exc,
            )

    return summary
