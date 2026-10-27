"""
GePNIC tender-identity regression tests.

Motivation (real, observed on the live GePNIC home listings of Odisha, Tamil
Nadu and West Bengal): the "Reference No" column is **not row-unique**. One
organisation routinely publishes a batch of distinct works under a single
reference number, e.g. Odisha's ``RWD Ctc-14/2026-27`` appears on six distinct
rows. The default identity path keys same-run de-duplication on
``gem_bid_id``/``bid_number`` (and the normalizer cross-fills ``gem_bid_id``
from ``bid_number``), so those distinct tenders collapse into one.

These tests cover two contracts:

* **Default sources are unchanged** — ``test_default_*`` pins the existing
  behaviour (including the GePNIC collision) so refactors cannot silently alter
  it.
* **Opt-in composite identity** — a source that declares
  ``config["identity_fields"]`` derives a stable identity from several stable
  fields, so distinct tenders sharing a reference number are preserved, repeat
  syncs stay idempotent, and a date-only corrigendum is an update, not a new
  tender.

Nothing here enables the opt-in path for any production source; it is exercised
only inside the tests.
"""

from __future__ import annotations

import pytest

from app.models.bid import Bid
from app.models.source import DataSource
from app.services.ingestion.normalizer import (
    derive_composite_identity,
    normalize_record,
)
from app.services.ingestion.schemas import RawBidRecord
from app.services.sources.base import SourceConfigError
from app.services.sources.runner import run_source_sync
from tests.source_test_utils import FakeResponse, FakeSession, make_resolver

HOST = "tenders.example.com"
HOME_URL = f"https://{HOST}/nicgep/app?page=Home&service=page"

FIELD_MAP = {
    "title": "td:nth-of-type(1)",
    "bid_number": "td:nth-of-type(2)",
    "closing_date": "td:nth-of-type(3)",
    "source_url": "td:nth-of-type(1) a@href",
}


@pytest.fixture(autouse=True)
def _patch_dns(monkeypatch):
    from app.services import sources as package

    monkeypatch.setattr(package.safe_http, "_resolve_host", make_resolver())


def _row(href: str, serial: int, title: str, ref: str, closing: str) -> str:
    return (
        "<tr>"
        f'<td><a href="/nicgep/app?component=%24DirectLink&page=Home'
        f'&service=direct&session=T&sp={href}">{serial}. {title}</a></td>'
        f"<td>{ref}</td><td>{closing}</td><td>16-Oct-2026 11:00 AM</td>"
        "</tr>"
    )


def _table(*rows: str) -> str:
    return '<table id="activeTenders">' + "".join(rows) + "</table>"


def _gepnic_source(db, *, source_id="gepnic-src", identity_fields=None):
    config = {
        "url": HOME_URL,
        "row_selector": "table#activeTenders tr",
        "field_map": dict(FIELD_MAP),
        "max_records": 50,
        "max_pages": 1,
    }
    if identity_fields is not None:
        config["identity_fields"] = identity_fields
    source = DataSource(
        source_id=source_id,
        name="GePNIC listing",
        source_type="html_listing",
        adapter_key="html_listing",
        enabled=True,
        collection_interval_minutes=60,
        config=config,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _session_for(html_pages):
    pages = list(html_pages)

    def handler(url, kwargs):
        return FakeResponse(200, pages.pop(0), url=url)

    return FakeSession(handler)


# ---------------------------------------------------------------------------
# Unit semantics of the composite identity
# ---------------------------------------------------------------------------
def test_composite_identity_distinct_titles_are_distinct():
    a = derive_composite_identity(
        ["bid_number", "title"],
        {
            "bid_number": "RWD Ctc-14/2026-27",
            "title": "1. Repair and maintenance of left parallel road",
        },
    )
    b = derive_composite_identity(
        ["bid_number", "title"],
        {
            "bid_number": "RWD Ctc-14/2026-27",
            "title": "2. S/R to Fire station office building at Adaspur",
        },
    )
    assert a != b


def test_composite_identity_ignores_leading_serial_and_case_whitespace():
    a = derive_composite_identity(
        ["bid_number", "title"],
        {
            "bid_number": "RWD Ctc-14/2026-27",
            "title": "1. Repair  road   at A",
        },
    )
    b = derive_composite_identity(
        ["bid_number", "title"],
        {
            "bid_number": "rwd ctc-14/2026-27",
            "title": "9. repair road at a",
        },
    )
    assert a == b


def test_composite_identity_is_deterministic_and_bounded():
    fields = ["bid_number", "title"]
    values = {"bid_number": "X-1", "title": "1. Something"}
    first = derive_composite_identity(fields, values)
    assert first == derive_composite_identity(fields, values)
    assert first.startswith("srcid-")
    assert len(first) <= 100  # fits Bid.gem_bid_id String(100)


# ---------------------------------------------------------------------------
# Default behaviour is unchanged (regression pin)
# ---------------------------------------------------------------------------
def test_default_distinct_tenders_sharing_reference_collapse(db):
    """Current default behaviour, pinned: shared Reference No collapses rows.

    This documents the known GePNIC limitation the opt-in mode exists to fix.
    It must keep passing (i.e. keep collapsing) until identity behaviour is
    intentionally changed.
    """
    source = _gepnic_source(db)  # no identity_fields
    html = _table(
        _row(
            "AAA", 1, "Repair road at A", "RWD Ctc-14/2026-27", "15-Oct-2026 05:00 PM"
        ),
        _row(
            "BBB", 2, "Repair road at B", "RWD Ctc-14/2026-27", "15-Oct-2026 05:00 PM"
        ),
    )
    result = run_source_sync(db, source, session=_session_for([html]))

    assert result["discovered"] == 1  # collapsed within the run
    assert result["inserted"] == 1
    assert db.query(Bid).count() == 1


def test_default_normalizer_still_cross_fills_identity():
    norm = normalize_record(RawBidRecord(title="T", bid_number="REF-1"))
    assert norm["gem_bid_id"] == "REF-1"
    assert norm["bid_number"] == "REF-1"


# ---------------------------------------------------------------------------
# Opt-in composite identity
# ---------------------------------------------------------------------------
def test_composite_preserves_distinct_tenders_sharing_reference(db):
    source = _gepnic_source(db, identity_fields=["bid_number", "title"])
    html = _table(
        _row(
            "AAA", 1, "Repair road at A", "RWD Ctc-14/2026-27", "15-Oct-2026 05:00 PM"
        ),
        _row(
            "BBB", 2, "Repair road at B", "RWD Ctc-14/2026-27", "15-Oct-2026 05:00 PM"
        ),
        _row(
            "CCC", 3, "Repair road at C", "RWD Ctc-14/2026-27", "15-Oct-2026 05:00 PM"
        ),
    )
    result = run_source_sync(db, source, session=_session_for([html]))

    assert result["discovered"] == 3
    assert result["inserted"] == 3
    bids = db.query(Bid).all()
    assert len(bids) == 3
    # Every row keeps its human reference number, but identity is distinct.
    assert {b.bid_number for b in bids} == {"RWD Ctc-14/2026-27"}
    assert len({b.gem_bid_id for b in bids}) == 3
    assert all((b.gem_bid_id or "").startswith("srcid-") for b in bids)


def test_composite_second_sync_is_idempotent(db):
    source = _gepnic_source(db, identity_fields=["bid_number", "title"])
    html = _table(
        _row(
            "AAA", 1, "Repair road at A", "RWD Ctc-14/2026-27", "15-Oct-2026 05:00 PM"
        ),
        _row(
            "BBB", 2, "Repair road at B", "RWD Ctc-14/2026-27", "15-Oct-2026 05:00 PM"
        ),
    )
    run_source_sync(db, source, session=_session_for([html]))

    # Identical content again, fresh session tokens -> same identity, no new rows.
    html2 = _table(
        _row(
            "XXX", 1, "Repair road at A", "RWD Ctc-14/2026-27", "15-Oct-2026 05:00 PM"
        ),
        _row(
            "YYY", 2, "Repair road at B", "RWD Ctc-14/2026-27", "15-Oct-2026 05:00 PM"
        ),
    )
    result = run_source_sync(db, source, session=_session_for([html2]))

    assert result["inserted"] == 0
    assert result["duplicates"] == 2
    assert result["updated"] == 0
    assert db.query(Bid).count() == 2


def test_composite_date_only_corrigendum_is_update_not_new(db):
    source = _gepnic_source(db, identity_fields=["bid_number", "title"])
    first = _table(
        _row(
            "AAA", 1, "Repair road at A", "RWD Ctc-14/2026-27", "15-Oct-2026 05:00 PM"
        ),
    )
    run_source_sync(db, source, session=_session_for([first]))

    # Same reference and title, closing date moved (a corrigendum).
    amended = _table(
        _row(
            "ZZZ", 1, "Repair road at A", "RWD Ctc-14/2026-27", "22-Oct-2026 05:00 PM"
        ),
    )
    result = run_source_sync(db, source, session=_session_for([amended]))

    assert result["inserted"] == 0
    assert result["duplicates"] == 1
    assert result["updated"] == 1
    bids = db.query(Bid).all()
    assert len(bids) == 1
    assert bids[0].closing_date is not None
    assert bids[0].closing_date.strftime("%Y-%m-%d") == "2026-10-22"


def test_composite_real_odisha_batch_shape(db):
    """Mirror the real Odisha home page: 3 distinct refs, 10 rows total."""
    source = _gepnic_source(db, identity_fields=["bid_number", "title"])
    rows = [
        _row(
            "A1",
            1,
            "Repair and maintenance of left parallel road",
            "e-TCN-NO-25-OF-2026-2027",
            "16-Oct-2026 02:00 PM",
        ),
        _row(
            "A2",
            2,
            "Repair and maintenance of road from Governor House",
            "TCN NO 25 OF 2026-2027",
            "16-Oct-2026 02:00 PM",
        ),
    ]
    for i in range(3, 9):  # six distinct works under ONE reference number
        rows.append(
            _row(
                f"B{i}",
                i,
                f"S/R to building number {i}",
                "RWD Ctc-14/2026-27",
                "15-Oct-2026 05:00 PM",
            )
        )
    for i in (9, 10):
        rows.append(
            _row(
                f"C{i}",
                i,
                f"Road work package {i}",
                "Tender Online-Divn.NPR-12/2026-27",
                "15-Oct-2026 05:00 PM",
            )
        )
    html = _table(*rows)

    result = run_source_sync(db, source, session=_session_for([html]))

    assert result["discovered"] == 10
    assert result["inserted"] == 10
    assert db.query(Bid).count() == 10


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------
def test_identity_fields_rejected_when_single_or_unknown_or_not_list():
    from app.services.sources.adapters import HtmlListingAdapter

    adapter = HtmlListingAdapter()
    base = {
        "url": HOME_URL,
        "row_selector": "table#activeTenders tr",
        "field_map": dict(FIELD_MAP),
    }
    with pytest.raises(SourceConfigError):
        adapter.validate_config({**base, "identity_fields": ["title"]})  # single
    with pytest.raises(SourceConfigError):
        adapter.validate_config({**base, "identity_fields": ["title", "nonsense"]})
    with pytest.raises(SourceConfigError):
        adapter.validate_config(
            {**base, "identity_fields": "bid_number,title"}
        )  # str, not list
    # A valid composite is accepted and preserved.
    ok = adapter.validate_config({**base, "identity_fields": ["bid_number", "title"]})
    assert ok["identity_fields"] == ["bid_number", "title"]
    # Absent stays absent (default behaviour untouched).
    plain = adapter.validate_config(dict(base))
    assert "identity_fields" not in plain
