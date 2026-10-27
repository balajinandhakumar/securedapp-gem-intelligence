"""
Adapter tests: RSS/Atom parse, JSON API (auth + pagination + field mapping),
HTML listing selectors + pagination, registry/catalog, and the secret-free
config sanitizer.

Parse-level tests run with no network (fake sessions / direct method calls).
"""

from __future__ import annotations

import json

import pytest

from app.services.sources.adapters import (
    HtmlListingAdapter,
    JsonApiAdapter,
    PlaywrightListingAdapter,
    RssFeedAdapter,
    adapter_catalog,
    all_adapters,
    get_adapter,
    get_adapter_for_source_type,
)
from app.services.sources.base import SourceConfigError, sanitize_config
from tests.source_test_utils import (
    FakeResponse,
    FakeSession,
    json_handler,
    make_resolver,
    static_handler,
)

HOST = "tenders.example.com"
BASE = f"https://{HOST}"


@pytest.fixture(autouse=True)
def _patch_dns(monkeypatch):
    from app.services import sources as package

    monkeypatch.setattr(package.safe_http, "_resolve_host", make_resolver())
    yield


RSS_2 = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Gov Tenders</title>
<item>
  <title>Supply &amp; installation of cameras</title>
  <link>https://%s/bids/cameras-1</link>
  <guid isPermaLink="false">CAM-2026-001</guid>
  <pubDate>Mon, 01 Jan 2026 09:00:00 GMT</pubDate>
  <description><![CDATA[Supply &amp; install 50 IP cameras.]]></description>
  <category>Security</category>
  <dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">Ministry of Home</dc:creator>
</item>
<item>
  <title>Furniture procurement</title>
  <link>https://%s/bids/furniture-2</link>
  <guid>FUR-001</guid>
  <pubDate>Tue, 02 Jan 2026 10:00:00 GMT</pubDate>
  <description>Office chairs and desks.</description>
</item>
</channel></rss>""" % (HOST, HOST)

ATOM = (
    """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>E-Tenders</title>
  <entry>
    <title>Cloud migration services</title>
    <id>CLOUD-9</id>
    <updated>2026-01-05T08:30:00Z</updated>
    <summary>Migrate legacy systems to the cloud.</summary>
    <author><name>Digital India Agency</name></author>
    <category term="IT Services"/>
    <link href="https://%s/tenders/cloud-9" rel="alternate"/>
  </entry>
</feed>"""
    % HOST
)


def test_rss_parse_maps_fields():
    records = RssFeedAdapter()._parse_feed(RSS_2, "https://x/rss")
    assert len(records) == 2
    r0 = records[0]
    assert r0.title == "Supply & installation of cameras"
    assert r0.gem_bid_id == "CAM-2026-001"
    assert r0.source_url == f"https://{HOST}/bids/cameras-1"
    assert r0.scope_of_work == "Supply & install 50 IP cameras."
    assert r0.organisation == "Ministry of Home"
    assert r0.category == "Security"


def test_atom_parse_maps_fields():
    records = RssFeedAdapter()._parse_feed(ATOM, "https://x/atom")
    assert len(records) == 1
    r0 = records[0]
    assert r0.title == "Cloud migration services"
    assert r0.gem_bid_id == "CLOUD-9"
    assert r0.source_url == f"https://{HOST}/tenders/cloud-9"
    assert r0.organisation == "Digital India Agency"
    assert r0.scope_of_work == "Migrate legacy systems to the cloud."


def test_rss_collect_via_fake_session():
    session = FakeSession(static_handler(RSS_2, 200))
    result = RssFeedAdapter().collect(
        {"url": f"https://{HOST}/feed", "max_records": 500}, session=session
    )
    assert result.pages_visited == 1
    assert len(result.records) == 2
    assert session.calls[0]["url"] == f"https://{HOST}/feed"


JSON_PAGE = {
    "items": [
        {
            "title": "Network security audit",
            "permalink": f"https://{HOST}/t/45",
            "deadline": "2026-03-01",
            "agency": "Cyber Cell",
            "id": "AUD-45",
        },
        {
            "title": "Perimeter fence",
            "permalink": f"https://{HOST}/t/88",
            "agency": "PWD",
        },
    ]
}


def test_json_api_single_page_with_field_map():
    adapter = JsonApiAdapter()
    config = {
        "url": f"https://{HOST}/api/tenders",
        "records_path": "items",
        "field_map": {
            "title": "title",
            "source_url": "permalink",
            "closing_date": "deadline",
            "organisation": "agency",
            "gem_bid_id": "id",
        },
        "max_records": 500,
    }
    session = FakeSession(json_handler(JSON_PAGE))
    result = adapter.collect(config, session=session)
    assert len(result.records) == 2
    r0, r1 = result.records
    assert r0.title == "Network security audit"
    assert r0.source_url == f"https://{HOST}/t/45"
    assert r0.gem_bid_id == "AUD-45"
    assert r0.closing_date == "2026-03-01"
    assert r0.organisation == "Cyber Cell"
    assert r1.title == "Perimeter fence"
    assert r1.closing_date is None  # not present -> not invented


def test_json_api_pagination_walks_pages():
    page1 = {"items": [{"title": f"Tender {i}", "id": f"T{i}"} for i in range(3)]}
    page2 = {
        "items": [{"title": f"Tender {i}", "id": f"T{i}"} for i in range(3)]
    }  # repeated ids -> stop
    pages = [json.dumps(page1), json.dumps(page2)]

    def handler(url, kwargs):
        return FakeResponse(200, pages.pop(0) if pages else "{}", url=url)

    config = {
        "url": f"https://{HOST}/api/tenders",
        "records_path": "items",
        "field_map": {"title": "title", "gem_bid_id": "id"},
        "page_param": "page",
        "page_size_param": "page_size",
        "page_size": 3,
        "max_pages": 5,
        "page_delay_seconds": 0,
    }
    session = FakeSession(handler)
    result = JsonApiAdapter().collect(config, session=session)
    assert len(result.records) == 3
    assert "page" in session.calls[1]["url"]
    assert result.pages_visited == 2


def test_json_api_auth_applies_env_secret(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SOURCE_ALLOWED_SECRET_ENVS", "BID_API_KEY")
    monkeypatch.setenv("BID_API_KEY", "sekrit-value")
    adapter = JsonApiAdapter()
    config = {
        "url": f"https://{HOST}/api/tenders",
        "records_path": "items",
        "auth": {"type": "query", "param": "api_key", "env_ref": "BID_API_KEY"},
    }
    session = FakeSession(json_handler(JSON_PAGE))
    adapter.collect(config, session=session)
    assert "api_key=sekrit-value" in session.calls[0]["url"]

    config["auth"] = {"type": "bearer", "env_ref": "BID_API_KEY"}
    adapter.collect(config, session=session)
    assert session.calls[1]["headers"]["Authorization"] == "Bearer sekrit-value"


def test_json_api_missing_secret_raises_config_error(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SOURCE_ALLOWED_SECRET_ENVS", "NOPE_NOT_SET_VAR")
    adapter = JsonApiAdapter()
    config = {
        "url": f"https://{HOST}/api/tenders",
        "records_path": "items",
        "auth": {"type": "bearer", "env_ref": "NOPE_NOT_SET_VAR"},
    }
    with pytest.raises(SourceConfigError):
        adapter.collect(config, session=FakeSession(json_handler(JSON_PAGE)))


HTML = (
    "<html><body><table>"
    + "".join(
        f"<tr class='row'><td class='title'>{t}</td>"
        f"<td class='when'>2026-01-0{d}</td>"
        f"<td class='org'>Org {d}</td>"
        f"<td class='desc'>Desc {d}</td></tr>"
        for d, t in ((1, "Drone survey"), (2, "Thermal mapping"))
    )
    + "</table></body></html>"
)


def test_html_listing_selector_mapping():
    config = {
        "url": f"https://{HOST}/tenders",
        "row_selector": "tr.row",
        "field_map": {
            "title": "td.title",
            "closing_date": "td.when",
            "organisation": "td.org",
            "scope_of_work": "td.desc",
        },
        "max_records": 500,
    }
    session = FakeSession(static_handler(HTML, 200))
    result = HtmlListingAdapter().collect(config, session=session)
    assert len(result.records) == 2
    assert result.records[0].title == "Drone survey"
    assert result.records[0].organisation == "Org 1"


def test_html_listing_same_origin_next_pagination():
    page1 = (
        "<html><ul>"
        "<li><a class='t' href='/b/1'>Bid 1</a></li>"
        "<li><a class='t' href='/b/2'>Bid 2</a></li>"
        "</ul><a class='next' href='/tenders?page=2'>Next</a></html>"
    )
    page2 = "<html><ul><li><a class='t' href='/b/3'>Bid 3</a></li></ul></html>"
    pages = {"first": True}

    def handler(url, kwargs):
        if pages["first"]:
            pages["first"] = False
            return FakeResponse(200, page1, url=url)
        return FakeResponse(200, page2, url=url)

    config = {
        "url": f"https://{HOST}/tenders",
        "row_selector": "li",
        "field_map": {"title": "a.t", "source_url": "a.t@href"},
        "pagination": {"next_selector": "a.next"},
        "max_pages": 4,
        "page_delay_seconds": 0,
    }
    session = FakeSession(handler)
    result = HtmlListingAdapter().collect(config, session=session)
    assert len(result.records) == 3
    assert result.pages_visited == 2
    # all source URLs are same-origin absolute
    assert all(r.source_url.startswith(f"https://{HOST}") for r in result.records)


def test_html_listing_url_to_private_link_is_dropped():
    html = (
        "<ul><li><a class='t' href='http://169.254.169.254/meta'>Bad</a></li>"
        "<li><a class='t' href='/b/9'>Good</a></li></ul>"
    )
    config = {
        "url": f"https://{HOST}/list",
        "row_selector": "li",
        "field_map": {"title": "a.t", "source_url": "a.t@href"},
    }
    session = FakeSession(static_handler(html, 200))
    result = HtmlListingAdapter().collect(config, session=session)
    assert len(result.records) == 1
    assert result.records[0].title == "Good"


def test_html_requires_row_selector():
    with pytest.raises(SourceConfigError):
        HtmlListingAdapter().validate_config({"url": f"https://{HOST}/x"})


def test_validate_config_clamps_budgets():
    cfg = JsonApiAdapter().validate_config(
        {
            "url": f"https://{HOST}/x",
            "max_pages": 9999,
            "max_records": 1,
            "timeout_seconds": 9999,
        }
    )
    assert cfg["max_pages"] == 200
    assert cfg["max_records"] == 1
    assert cfg["timeout_seconds"] == 120.0


def test_validate_url_field_blocks_localhost():
    with pytest.raises(SourceConfigError):
        RssFeedAdapter().validate_config({"url": "http://localhost/feed.xml"})


def test_registry_and_catalog():
    keys = {a.adapter_key for a in all_adapters().values()}
    assert keys == {"rss_feed", "json_api", "html_listing", "playwright_html"}
    assert get_adapter("rss_feed").adapter_label
    assert get_adapter_for_source_type("rss").adapter_key == "rss_feed"
    assert get_adapter("nope") is None
    catalog = {c["adapter_key"]: c for c in adapter_catalog()}
    assert catalog["playwright_html"]["requires_browser"] is True
    assert "integration_note" in catalog["playwright_html"]


def test_playwright_adapter_validation_allows_config():
    config = PlaywrightListingAdapter().validate_config(
        {"url": f"https://{HOST}/list", "row_selector": "li"}
    )
    assert config["row_selector"] == "li"


# ---------------------------------------------------------------------------
# Secret-free sanitization
# ---------------------------------------------------------------------------
def test_sanitize_config_masks_secrets():
    cfg = {
        "url": "https://x",
        "auth": {"type": "bearer", "env_ref": "MY_KEY"},
        "headers": {"X-API-Key": "super-secret"},
        "password": "hunter2",
    }
    out = sanitize_config(cfg)
    assert out["url"] == "https://x"
    assert out["auth"]["env_ref"] == "MY_KEY"
    assert out["auth"]["type"] == "bearer"
    assert out["headers"]["X-API-Key"] == "***"
    assert out["password"] == "***"


def test_sanitize_config_nested():
    out = sanitize_config({"nested": [{"token": "abc"}, "plain"]})
    assert out["nested"][0]["token"] == "***"
    assert out["nested"][1] == "plain"
