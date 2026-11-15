"""
Concrete source adapters and the adapter registry.

Adapter keys
------------
``rss_feed``        RSS 2.0 / Atom feeds (single fetch, no pagination)
``json_api``        JSON HTTP API with optional query/header/bearer auth and
                    page-based pagination
``html_listing``    Public HTML listing pages parsed with configurable CSS
                    selectors (same-origin pagination only)
``playwright_html`` Browser-rendered public listing pages (Playwright). Only
                    used when the page genuinely needs a browser; plain-HTTP
                    listing is always preferred.

Every adapter parses into the canonical ``RawBidRecord`` shape and returns
only *safe* per-run error details (trimmed, secret-free, never raw payloads).
"""

from __future__ import annotations

import html as _html
import json
import logging
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from app.services.ingestion.schemas import RawBidRecord
from app.services.sources.base import (
    BaseSourceAdapter,
    CollectResult,
    ConnectionTestResult,
    SourceConfigError,
    _allowed_hosts,
    apply_auth,
    clamp_int,
    safe_error,
    validate_secret_ref,
)
from app.services.sources.safe_http import (
    BlockedResponseError,
    SafeFetchError,
    UrlNotPermittedError,
    url_for_log,
    validate_public_url,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(value: Any) -> str:
    """Remove HTML tags/CDATA wrapper and unescape, collapsing whitespace."""
    if value is None:
        return ""
    text = str(value)
    if text.startswith("<![CDATA[") and text.endswith("]]>"):
        text = text[9:-3]
    text = _TAG_RE.sub(" ", text)
    return " ".join(_html.unescape(text).split())


def _dotted_get(data: Optional[Dict[str, Any]], path: Optional[str]) -> Any:
    if not path:
        return None
    node: Any = data
    for part in str(path).split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


# Alias table applied when a source item has no explicit field_map entry.
_IMPLICIT_ALIASES = {
    "description": "scope_of_work",
    "summary": "scope_of_work",
    "body": "scope_of_work",
    "link": "source_url",
    "url": "source_url",
    "permalink": "source_url",
    "published": "published_date",
    "pub_date": "published_date",
    "publish_date": "published_date",
    "deadline": "closing_date",
    "close_date": "closing_date",
    "closing": "closing_date",
    "agency": "organisation",
    "buyer": "organisation",
    "procuring_entity": "organisation",
    "procuring_agency": "organisation",
    "organization": "organisation",
}


# ---------------------------------------------------------------------------
# RSS / Atom adapter
# ---------------------------------------------------------------------------
class RssFeedAdapter(BaseSourceAdapter):
    adapter_key = "rss_feed"
    adapter_label = "RSS / Atom feed"
    source_types = ("rss", "atom")
    method = "http"
    integration_note = ""

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def _parse_feed(self, raw: str, source_url: str) -> List[RawBidRecord]:
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise SourceConfigError(
                f"Feed at {source_url} is malformed XML: {exc}",
                safe_message=f"Feed could not be parsed as XML ({type(exc).__name__}).",
            ) from exc

        tag = str(getattr(root, "tag", "")).split("}")[-1]
        if tag == "rss":
            return self._parse_rss(root, source_url)
        if tag == "feed":
            return self._parse_atom(root, source_url)
        raise SourceConfigError(
            f"Unrecognized feed root <{tag}> (expected <rss> or <feed>).",
            safe_message="Feed root element is not RSS or Atom.",
        )

    def _parse_rss(self, root: ET.Element, source_url: str) -> List[RawBidRecord]:
        records: List[RawBidRecord] = []
        items = root.findall(".//item")
        for item in items:
            title = strip_html(_text(item, "title"))
            guid = _text(item, "guid") or _text(item, "identifier")
            link = _text(item, "link")
            pub_date = (
                _text(item, "pubDate") or _text(item, "date") or _text(item, "updated")
            )
            description = strip_html(_text(item, "description"))
            category = strip_html(_text(item, "category"))
            author = (
                strip_html(_text(item, "creator"))
                or strip_html(_text(item, "author"))
                or ""
            )
            if not title:
                continue
            records.append(
                RawBidRecord(
                    gem_bid_id=guid,
                    title=title,
                    organisation=author or None,
                    category=category or None,
                    published_date=pub_date or None,
                    scope_of_work=description or None,
                    source_url=(link or source_url),
                )
            )
        return records

    def _parse_atom(self, root: ET.Element, source_url: str) -> List[RawBidRecord]:
        records: List[RawBidRecord] = []
        for entry in root.findall(".//{*}entry"):
            title = strip_html(_text(entry, "title"))
            if not title:
                continue
            link = ""
            for link_el in entry.findall(".//{*}link"):
                href = str(link_el.get("href") or "")
                if href:
                    link = href
                    break
            guid = _text(entry, "id") or link
            published = _text(entry, "published") or _text(entry, "updated")
            summary = strip_html(_text(entry, "summary")) or strip_html(
                _text(entry, "content")
            )
            author_el = entry.find(".//{*}author/{*}name")
            author = strip_html(_text_from(author_el)) if author_el is not None else ""
            category = strip_html(_text_of(entry, "category"))
            records.append(
                RawBidRecord(
                    gem_bid_id=guid or None,
                    title=title,
                    organisation=author or None,
                    category=category or None,
                    published_date=published or None,
                    scope_of_work=summary or None,
                    source_url=(link or source_url),
                )
            )
        return records

    def collect(
        self, config: Dict[str, Any], *, name: str = "", session: Any = None
    ) -> CollectResult:
        url = str(config["url"])
        errors: List[Dict[str, str]] = []
        try:
            resp = self._safe_fetch(url, session, config)
        except BlockedResponseError:
            raise
        except (SafeFetchError, UrlNotPermittedError) as exc:
            raise SafeFetchError(str(exc), url=url) from exc
        if resp.status_code == 404:
            raise SafeFetchError(f"Feed {url_for_log(url)} returned HTTP 404.", url=url)
        try:
            records = self._parse_feed(resp.text, url)
        except SourceConfigError:
            raise
        except Exception as exc:  # noqa: BLE001 - a parse failure is a safe run error
            raise SafeFetchError(
                f"Feed {url_for_log(url)} could not be parsed: {exc}", url=url
            ) from exc
        if config.get("max_records") and len(records) > int(config["max_records"]):
            records = records[: int(config["max_records"])]
        return CollectResult(
            records=records, pages_visited=1, errors=errors, method="http"
        )

    def test_connection(
        self, config: Dict[str, Any], *, session: Any = None
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(config["url"], session, config)
            parsed = self._parse_feed(resp.text, config["url"])
            return ConnectionTestResult(
                ok=True,
                message=f"Feed reachable (HTTP {resp.status_code}); {len(parsed)} record(s) parsed.",
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, SourceConfigError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except UrlNotPermittedError:
            return ConnectionTestResult(
                ok=False, message="Destination is not permitted (private/reserved)."
            )


def _text(el: ET.Element, name: str) -> str:
    """Namespace-agnostic child text."""
    for child in el.iter():
        local = str(getattr(child, "tag", "")).split("}")[-1]
        if local == name and child.text:
            return str(child.text)
    return ""


def _text_from(el: Optional[ET.Element]) -> str:
    return str(el.text or "").strip() if el is not None else ""


def _text_of(el: ET.Element, name: str) -> str:
    for field in el.findall(".//*"):
        if str(getattr(field, "tag", "")).split("}")[-1] == name and field.text:
            return str(field.text)
    return ""


# ---------------------------------------------------------------------------
# JSON API adapter
# ---------------------------------------------------------------------------
class JsonApiAdapter(BaseSourceAdapter):
    adapter_key = "json_api"
    adapter_label = "JSON API"
    source_types = ("json_api",)
    method = "http"

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        auth = cfg.get("auth") or {}
        if auth:
            auth_type = str(auth.get("type") or "").lower()
            if auth_type not in ("bearer", "header", "query"):
                raise SourceConfigError(
                    "Unsupported auth type.",
                    safe_message="auth.type must be bearer, header or query.",
                )
            # Reject arbitrary / malformed / non-allowlisted credential
            # references at save time (and again at collection time).
            validate_secret_ref(auth.get("env_ref"))
        if cfg.get("page_size"):
            cfg["page_size"] = clamp_int(cfg["page_size"], 50, 1, 500)
        return cfg

    def _resolve_target(
        self,
        base: str,
        auth: Dict[str, str],
        page: Optional[int],
        config: Dict[str, Any],
    ) -> str:
        parts = urllib.parse.urlsplit(base)
        query = dict(urllib.parse.parse_qsl(parts.query))
        query.update(auth.get("query") or {})
        page_param = str(config.get("page_param") or "").strip()
        if page is not None and page_param:
            query[page_param] = str(page)
        size_param = str(config.get("page_size_param") or "").strip()
        if size_param and config.get("page_size"):
            query[size_param] = str(config["page_size"])
        return urllib.parse.urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urllib.parse.urlencode(query),
                parts.fragment,
            )
        )

    def collect(
        self, config: Dict[str, Any], *, name: str = "", session: Any = None
    ) -> CollectResult:
        errors: List[Dict[str, str]] = []
        base_url = str(config["url"])
        headers: Dict[str, str] = {}
        auth_args = apply_auth(
            config
        )  # raises SourceConfigError if a secret is missing
        headers.update(auth_args.get("headers") or {})
        auth = auth_args

        pages: List[Dict[str, Any]] = []
        max_pages = int(config.get("max_pages") or 1)
        page_param = str(config.get("page_param") or "").strip()
        page = 1
        fetched = 0
        seen_ids: set = set()
        while True:
            url = self._resolve_target(
                base_url, auth, page if page_param else None, config
            )
            try:
                resp = self._safe_fetch(url, session, config, headers=headers)
            except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                raise
            except Exception as exc:  # noqa: BLE001
                errors.append(safe_error("json", f"page {page}: {exc}"))
                break
            fetched += 1
            if resp.status_code == 404:
                errors.append(safe_error("json", f"page {page}: HTTP 404"))
                break
            try:
                payload = json.loads(resp.text)
            except ValueError as exc:
                errors.append(
                    safe_error("json", f"page {page}: not valid JSON ({exc})")
                )
                break
            items = _dotted_get(payload, config.get("records_path") or "")
            if items is None:
                items = [payload]
            elif not isinstance(items, list):
                items = [payload]
            else:
                items = list(items)

            ids = _page_ids(items, config)
            # A fully-repeated page is the end of pagination: it was already
            # collected, so it is never appended a second time.
            if page_param and page > 1 and ids and ids <= seen_ids:
                break
            pages.append(payload)
            if ids:
                seen_ids |= ids
            if not page_param or page >= max_pages:
                break
            if not items:
                break
            if config.get("page_size") and len(items) < int(config["page_size"]):
                break
            page += 1
            if config.get("page_delay_seconds"):
                time.sleep(float(config["page_delay_seconds"]))

        records: List[RawBidRecord] = []
        for payload in pages:
            items = _dotted_get(payload, config.get("records_path") or "")
            if not isinstance(items, list):
                items = [payload]
            for item in items:
                if not isinstance(item, dict):
                    continue
                rec = self._map_item(item, config, name)
                if rec is None:
                    continue
                records.append(rec)
                if config.get("max_records") and len(records) >= int(
                    config["max_records"]
                ):
                    return CollectResult(
                        records=records,
                        pages_visited=fetched,
                        errors=errors,
                        method="http",
                    )

        return CollectResult(
            records=records, pages_visited=fetched, errors=errors, method="http"
        )

    def _map_item(
        self, item: Dict[str, Any], config: Dict[str, Any], name: str
    ) -> Optional[RawBidRecord]:
        field_map = config.get("field_map") or {}
        kwargs: Dict[str, Any] = {}
        for canonical, source_field in field_map.items():
            if canonical not in RawBidRecord.model_fields:
                continue
            value = _dotted_get(item, str(source_field))
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            if isinstance(value, (int, float)) and value == 0:
                value = str(value)
            if value is not None:
                kwargs[canonical] = value
        # Implicit aliases for unmapped canonical fields.
        for source_field, canonical in _IMPLICIT_ALIASES.items():
            if canonical in kwargs:
                continue
            value = item.get(source_field)
            if isinstance(value, dict):
                value = None
            if isinstance(value, list):
                value = (
                    ", ".join(str(v) for v in value if not isinstance(v, (dict, list)))
                    or None
                )
            if value is not None:
                kwargs[canonical] = value
        if not kwargs.get("title"):
            return None
        kwargs.setdefault("source_name", name or None)
        return RawBidRecord(**kwargs)

    def test_connection(
        self, config: Dict[str, Any], *, session: Any = None
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            auth_args = apply_auth(config)
            headers: Dict[str, str] = dict(auth_args.get("headers") or {})
            url = self._resolve_target(str(config["url"]), auth_args, None, config)
            resp = self._safe_fetch(url, session, config, headers=headers)
            json.loads(resp.text)
            return ConnectionTestResult(
                ok=True,
                message=f"API reachable (HTTP {resp.status_code}).",
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except SourceConfigError:
            raise
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"API refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except ValueError:
            return ConnectionTestResult(
                ok=False, message="Response was not valid JSON."
            )


def _page_ids(items: List[Any], config: Dict[str, Any]) -> set:
    ids: set = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        rec = JsonApiAdapter()._map_item(item, config, name="")
        if rec and (rec.gem_bid_id or rec.bid_number):
            ids.add((rec.gem_bid_id or rec.bid_number).strip().upper())
    return ids


# ---------------------------------------------------------------------------
# HTML listing adapter (configurable CSS selectors)
# ---------------------------------------------------------------------------
class HtmlListingAdapter(BaseSourceAdapter):
    adapter_key = "html_listing"
    adapter_label = "Public HTML listing (configurable selectors)"
    source_types = ("html_listing",)
    method = "http"

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        if not str(cfg.get("row_selector") or "").strip():
            raise SourceConfigError(
                "row_selector is required.",
                safe_message="A CSS row_selector identifying listing rows is required.",
            )
        field_map = cfg.get("field_map") or {}
        if not isinstance(field_map, dict):
            raise SourceConfigError(
                "field_map must be an object.",
                safe_message="field_map must be an object.",
            )
        for canonical in field_map:
            if canonical not in RawBidRecord.model_fields and canonical != "source_url":
                raise SourceConfigError(
                    f"Unknown field '{canonical}' in field_map.",
                    safe_message=f"field_map contains unknown field '{canonical}'.",
                )
        return cfg

    def _extract_text(self, container: Any, selector: str) -> str:
        # selector can be "css" or "css@attr"
        css, _, attr = selector.partition("@")
        css = css.strip()
        if not css:
            return ""
        el = container.select_one(css)
        if el is None:
            return ""
        if attr:
            value = el.get(attr)
            return str(value or "").strip()
        return " ".join(el.get_text(" ", strip=True).split())

    def _extract_record(
        self, row: Any, base_url: str, config: Dict[str, Any]
    ) -> Optional[RawBidRecord]:
        field_map = config.get("field_map") or {}
        kwargs: Dict[str, Any] = {}
        for canonical, selector in field_map.items():
            value = self._extract_text(row, str(selector))
            if not value:
                continue
            if canonical == "source_url":
                parsed = urllib.parse.urljoin(base_url, value)
                try:
                    validate_public_url(parsed, allowed_hosts=_allowlist())
                except UrlNotPermittedError:
                    # A row pointing at a private/local link is dropped whole:
                    # the record must never survive without its source link.
                    return None
                kwargs["source_url"] = parsed
            else:
                kwargs[canonical] = value
        if not kwargs.get("title"):
            return None
        return RawBidRecord(**kwargs)

    def collect(
        self, config: Dict[str, Any], *, name: str = "", session: Any = None
    ) -> CollectResult:
        errors: List[Dict[str, str]] = []
        seen_source_urls: set = set()
        records: List[RawBidRecord] = []
        pages_visited = 0
        max_pages = int(config.get("max_pages") or 1)
        url = str(config["url"])
        query_param = str((config.get("pagination") or {}).get("param") or "").strip()
        next_selector = str(
            (config.get("pagination") or {}).get("next_selector") or ""
        ).strip()

        page = 0
        while page < max_pages:
            base = url
            if page and query_param:
                parts = urllib.parse.urlsplit(url)
                q = dict(urllib.parse.parse_qsl(parts.query))
                q[query_param] = str(page + 1)
                base = urllib.parse.urlunsplit(
                    (
                        parts.scheme,
                        parts.netloc,
                        parts.path,
                        urllib.parse.urlencode(q),
                        parts.fragment,
                    )
                )
            try:
                resp = self._safe_fetch(base, session, config)
            except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                raise
            except Exception as exc:  # noqa: BLE001
                errors.append(safe_error("html", f"page {page + 1}: {exc}"))
                break
            if resp.status_code == 404:
                errors.append(safe_error("html", f"page {page + 1}: HTTP 404"))
                break
            soup = self._to_soup(resp.text)
            rows = soup.select(str(config["row_selector"]))
            pages_visited += 1
            for row in rows:
                rec = self._extract_record(row, base, config)
                if rec is None:
                    continue
                key = (
                    (rec.source_url or (rec.gem_bid_id or rec.bid_number or ""))
                    .strip()
                    .lower()
                )
                if key and key in seen_source_urls:
                    continue
                if key:
                    seen_source_urls.add(key)
                records.append(rec)
                if config.get("max_records") and len(records) >= int(
                    config["max_records"]
                ):
                    return CollectResult(
                        records=records,
                        pages_visited=pages_visited,
                        errors=errors,
                        method="http",
                    )
            if not rows:
                break
            if config.get("page_delay_seconds"):
                time.sleep(float(config["page_delay_seconds"]))
            # Find the next page href (same-origin only).
            next_href = ""
            if next_selector:
                anchor = soup.select_one(next_selector)
                if anchor is not None:
                    next_href = str(anchor.get("href") or "").strip()
            elif not query_param:
                break
            if next_href and not query_param:
                next_abs = urllib.parse.urljoin(base, next_href)
                if (
                    urllib.parse.urlsplit(next_abs).netloc.lower()
                    == urllib.parse.urlsplit(url).netloc.lower()
                ):
                    url = next_abs
                else:
                    break
            elif query_param:
                page += 1
                continue
            else:
                break
            if not next_href:
                break
            page += 1
        return CollectResult(
            records=records, pages_visited=pages_visited, errors=errors, method="http"
        )

    def _to_soup(self, markup: str) -> Any:
        from bs4 import BeautifulSoup

        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self, config: Dict[str, Any], *, session: Any = None
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        row_selector = str(config.get("row_selector") or "").strip()
        if not row_selector:
            return ConnectionTestResult(
                ok=False,
                message="A CSS row_selector identifying listing rows is required.",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select(row_selector)
            return ConnectionTestResult(
                ok=True,
                message=f"Page reachable (HTTP {resp.status_code}); {len(rows)} row(s) matched the selector.",
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Browser-rendered HTML listing adapter
# ---------------------------------------------------------------------------
def _guard_browser_request(url: str) -> bool:
    """Return True when the browser renderer may load ``url``, else False.

    A real browser fetches far more than the initial document: scripts, images,
    iframes, fetch/XHR, workers and beacons. Each of those must satisfy the
    same SSRF policy as the main document. ``http``/``https`` destinations are
    allowed only when :func:`validate_public_url` passes; non-network browser
    schemes (``about:``, ``data:``, ``blob:``, ``javascript:``, ``chrome:``)
    are allowed; everything else (``file:``, ``ftp:``, ``ws:``/``wss:``,
    unknown schemes) is refused.
    """
    scheme = urllib.parse.urlsplit(str(url or "")).scheme.lower()
    if scheme in ("http", "https"):
        try:
            validate_public_url(url, allowed_hosts=_allowlist())
        except UrlNotPermittedError:
            return False
        return True
    if scheme in ("about", "data", "blob", "javascript", "chrome", "chromium"):
        return True
    return False


class PlaywrightListingAdapter(HtmlListingAdapter):
    adapter_key = "playwright_html"
    adapter_label = "Browser-rendered HTML listing (Playwright)"
    source_types = ("playwright_html",)
    requires_browser = True
    method = "playwright"
    integration_note = (
        "Renders the page in a real browser before selector extraction. "
        "Only for listings that genuinely need JavaScript; plain-HTTP HTML is preferred. "
        "Not part of the MVP's live-verified adapter set."
    )

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        return cfg

    def _safe_fetch(self, url: str, session: Any, config: Dict[str, Any]) -> Any:
        # SSRF validation still applies before the browser is pointed at the URL.
        validate_public_url(url, allowed_hosts=_allowlist())
        timeout_ms = max(5000, int(float(config.get("timeout_seconds") or 30) * 1000))
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise SourceConfigError(
                f"Playwright is required for browser rendering but is not installed ({exc}).",
                safe_message="Browser rendering requires Playwright, which is not available.",
            ) from exc

        user_agent = "SecuredApp-Bid-Intelligence/1.0"
        with sync_playwright() as driver:
            browser = driver.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=user_agent, locale="en-US")

                # Block every subresource (script / image / iframe / fetch /
                # worker / beacon) that does not satisfy the SSRF policy. The
                # main-document URL was already validated above; this closes the
                # gap where a page's own code would otherwise make the browser
                # contact internal addresses.
                def _route_guard(route: Any) -> None:
                    req_url = str(route.request.url or "")
                    if _guard_browser_request(req_url):
                        route.continue_()
                        return
                    logger.warning(
                        "Blocked browser renderer request to %s", url_for_log(req_url)
                    )
                    route.abort()

                page.route("**/*", _route_guard)
                response = page.goto(
                    url, wait_until="domcontentloaded", timeout=timeout_ms
                )
                status = int(response.status) if response else 0
                if status in (403, 429):
                    raise BlockedResponseError(
                        f"{url_for_log(url)} refused automated collection (HTTP {status}).",
                        url=url,
                        http_status=status,
                    )
                page.wait_for_timeout(3000)
                markup = page.content()
            finally:
                browser.close()

        class _Rendered:
            status_code = status
            text = markup
            url = url

        return _Rendered()


# ---------------------------------------------------------------------------
# Arunachal Pradesh e-Procurement Adapter
# ---------------------------------------------------------------------------
class ArunachalPradeshTenderAdapter(BaseSourceAdapter):
    """Adapter for the Arunachal Pradesh e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://bidplus.gem.gov.in/all-bids ... no, https://
    bidplus.gem.gov.in/all-bids ... no,
    https://arunachaltenders.gov.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and corrigendum
    information.
    """

    adapter_key = "arunachal_pradesh"
    adapter_label = "Arunachal Pradesh e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Arunachal Pradesh public listing.

        Uses the same requests session for listing and detail pages so that
        GeM-style session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        # Use provided session or create a new one for cookie persistence.
        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                # Check for next page via pagination controls
                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GeM-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Arunachal Pradesh",
                "source_url": detail_url,
                "source_name": "Arunachal Pradesh e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Chhattisgarh e-Procurement Adapter
# ---------------------------------------------------------------------------
class ChhattisgarhTenderAdapter(BaseSourceAdapter):
    """Adapter for the Chhattisgarh e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://eproc.cgstate.gov.in/ using HTML parsing with BeautifulSoup.
    Detail pages are fetched using the same requests session to preserve
    cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and corrigendum
    information.

    NOTE: The Chhattisgarh e-procurement portal at eproc.cgstate.gov.in
    redirects to a sign-in page (CHEPS/security/getSignInAction.do) that
    requires authentication and/or CAPTCHA. Public tender listing pages are
    not accessible without credentials. Collection will reach the portal
    but find 0 tender rows. This is expected and not a bypass of any
    access control.
    """

    adapter_key = "chhattisgarh"
    adapter_label = "Chhattisgarh e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Chhattisgarh public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        # Use provided session or create a new one for cookie persistence.
        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                # Check for next page via pagination controls
                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Chhattisgarh",
                "source_url": detail_url,
                "source_name": "Chhattisgarh e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Tamil Nadu e-Procurement Adapter
# ---------------------------------------------------------------------------
class TamilNaduTenderAdapter(BaseSourceAdapter):
    """Adapter for the Tamil Nadu e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://tntenders.gov.in/nicgep/app using HTML parsing with BeautifulSoup.
    Detail pages are fetched using the same requests session to preserve
    cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and corrigendum
    information.
    """

    adapter_key = "tamil_nadu"
    adapter_label = "Tamil Nadu e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Tamil Nadu public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        # Use provided session or create a new one for cookie persistence.
        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                # Check for next page via pagination controls
                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Tamil Nadu",
                "source_url": detail_url,
                "source_name": "Tamil Nadu e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Maharashtra e-Procurement Adapter
# ---------------------------------------------------------------------------
class MaharashtraTenderAdapter(BaseSourceAdapter):
    """Adapter for the Maharashtra e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://mahatenders.gov.in/nicgep/app using HTML parsing with BeautifulSoup.
    Detail pages are fetched using the same requests session to preserve
    cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and corrigendum
    information.
    """

    adapter_key = "maharashtra"
    adapter_label = "Maharashtra e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Maharashtra public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        # Use provided session or create a new one for cookie persistence.
        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                # Check for next page via pagination controls
                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Maharashtra",
                "source_url": detail_url,
                "source_name": "Maharashtra e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Delhi e-Procurement Adapter
# ---------------------------------------------------------------------------
class DelhiTenderAdapter(BaseSourceAdapter):
    """Adapter for the Delhi e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://govtprocurement.delhi.gov.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session to
    preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and corrigendum
    information.
    """

    adapter_key = "delhi"
    adapter_label = "Delhi e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Delhi public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        # Use provided session or create a new one for cookie persistence.
        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                # Check for next page via pagination controls
                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of NCT of Delhi",
                "source_url": detail_url,
                "source_name": "Delhi e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Rajasthan e-Procurement Adapter
# ---------------------------------------------------------------------------
class RajasthanTenderAdapter(BaseSourceAdapter):
    """Adapter for the Rajasthan e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://eproc.rajasthan.gov.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and corrigendum
    information.
    """

    adapter_key = "rajasthan"
    adapter_label = "Rajasthan e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Rajasthan public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        # Use provided session or create a new one for cookie persistence.
        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                # Check for next page via pagination controls
                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Rajasthan",
                "source_url": detail_url,
                "source_name": "Rajasthan e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Madhya Pradesh e-Procurement Adapter
# ---------------------------------------------------------------------------
class MadhyaPradeshTenderAdapter(BaseSourceAdapter):
    """Adapter for the Madhya Pradesh e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://mptenders.gov.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and corrigendum
    information.
    """

    adapter_key = "madhya_pradesh"
    adapter_label = "Madhya Pradesh e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Madhya Pradesh public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        # Use provided session or create a new one for cookie persistence.
        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                # Check for next page via pagination controls
                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Madhya Pradesh",
                "source_url": detail_url,
                "source_name": "Madhya Pradesh e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Odisha e-Procurement Adapter
# ---------------------------------------------------------------------------
class OdishaTenderAdapter(BaseSourceAdapter):
    """Adapter for the Odisha e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://tendersodisha.gov.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and corrigendum
    information.
    """

    adapter_key = "odisha"
    adapter_label = "Odisha e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Odisha public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        # Use provided session or create a new one for cookie persistence.
        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                # Check for next page via pagination controls
                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Odisha",
                "source_url": detail_url,
                "source_name": "Odisha e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Punjab e-Procurement Adapter
# ---------------------------------------------------------------------------
class PunjabTenderAdapter(BaseSourceAdapter):
    """Adapter for the Punjab e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://eproc.punjab.gov.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and corrigendum
    information.
    """

    adapter_key = "punjab"
    adapter_label = "Punjab e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Punjab public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        # Use provided session or create a new one for cookie persistence.
        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                # Check for next page via pagination controls
                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Punjab",
                "source_url": detail_url,
                "source_name": "Punjab e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Sikkim e-Procurement Adapter
# ---------------------------------------------------------------------------
class SikkimTenderAdapter(BaseSourceAdapter):
    """Adapter for the Sikkim Government Tender Portal.

    Collects bids from the public tender listing page at
    https://www.sikkim.gov.in/tender using HTML parsing with BeautifulSoup.

    Listing page format: each table row contains a single cell with
    "Title - Date - Department View" and a link to the tender detail page
    at /tender/tender-info/{id}?Tender={title}.

    Detail pages contain the tender title, file download link, and tender date.
    No login or CAPTCHA is required for public access.
    No pagination controls were found on the listing page (single page).
    """

    adapter_key = "sikkim"
    adapter_label = "Sikkim Government Tender Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Sikkim public tender listing.

        Parses the listing table and follows each tender detail link to
        extract the tender date from the detail page.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("table tr")
                pages_visited += 1

                if not rows:
                    break

                # Skip header row
                data_rows = rows[1:] if len(rows) > 1 else []

                for row in data_rows:
                    rec = self._extract_record(row, url, config, http_session)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                # No pagination controls found on Sikkim listing page
                break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(
        self,
        row,
        base_url: str,
        config: Dict[str, Any],
        http_session: requests.Session,
    ) -> Optional[RawBidRecord]:
        """Extract a single bid record from a Sikkim listing row."""
        try:
            cells = row.find_all(["td", "th"])
            if not cells:
                return None

            cell_text = cells[0].get_text(" ", strip=True)
            if not cell_text:
                return None

            # Find the View link in the row
            link = row.find("a", href=True)
            if link is None:
                return None

            detail_href = link.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            # Parse cell text: "Title - Date - Department View"
            # Format: "New <title> -<date> - <department> View"
            title = None
            closing_date = None
            department = None

            parts = cell_text.split("-")
            if len(parts) >= 3:
                title = parts[0].strip()
                # Remove "New " prefix if present
                if title.lower().startswith("new "):
                    title = title[4:].strip()
                date_part = parts[1].strip()
                dept_part = parts[2].strip()
                # Remove trailing "View" from department
                if dept_part.lower().endswith("view"):
                    dept_part = dept_part[:-4].strip()
                department = dept_part
                closing_date = date_part if date_part else None
            else:
                title = cell_text.strip()

            if not title:
                return None

            # Fetch detail page to get tender date
            detail_date = None
            try:
                detail_resp = self._safe_fetch(detail_url, http_session, config)
                detail_soup = self._to_soup(detail_resp.text)
                detail_text = detail_soup.get_text(" ", strip=True)
                # Look for "Tender Date: <date>" pattern
                import re as _re
                date_match = _re.search(r"Tender Date:\s*\(?([^)]+)\)?", detail_text)
                if date_match:
                    detail_date = date_match.group(1).strip()
            except Exception:  # noqa: BLE001 - detail fetch failure shouldn't lose the record
                pass

            kwargs: Dict[str, Any] = {
                "gem_bid_id": detail_href.split("/")[-1].split("?")[0] if detail_href else None,
                "bid_number": detail_href.split("/")[-1].split("?")[0] if detail_href else None,
                "title": title,
                "organisation": "Government of Sikkim",
                "source_url": detail_url,
                "source_name": "Sikkim Government Tender Portal",
                "published_date": detail_date or closing_date,
                "closing_date": closing_date,
                "category": None,
                "department": department,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("table tr")
            data_rows = rows[1:] if len(rows) > 1 else []
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(data_rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Kerala e-Procurement Adapter
# ---------------------------------------------------------------------------
class KeralaTenderAdapter(BaseSourceAdapter):
    """Adapter for the Kerala e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://etenders.kerala.gov.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and corrigendum
    information.
    """

    adapter_key = "kerala"
    adapter_label = "Kerala e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Kerala public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        # Use provided session or create a new one for cookie persistence.
        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                # Check for next page via pagination controls
                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Kerala",
                "source_url": detail_url,
                "source_name": "Kerala e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Assam e-Procurement Adapter
# ---------------------------------------------------------------------------
class AssamTenderAdapter(BaseSourceAdapter):
    """Adapter for the Assam e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://assamtenders.gov.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and tender ID.
    """

    adapter_key = "assam"
    adapter_label = "Assam e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Assam public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        # Use provided session or create a new one for cookie persistence.
        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                # Check for next page via pagination controls
                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Assam",
                "source_url": detail_url,
                "source_name": "Assam e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Chandigarh e-Procurement Adapter
# ---------------------------------------------------------------------------
class ChandigarhTenderAdapter(BaseSourceAdapter):
    """Adapter for the Chandigarh e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://etenders.chd.nic.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and tender ID.
    """

    adapter_key = "chandigarh"
    adapter_label = "Chandigarh e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Chandigarh public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        # Use provided session or create a new one for cookie persistence.
        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                # Check for next page via pagination controls
                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Chandigarh UT Administration",
                "source_url": detail_url,
                "source_name": "Chandigarh e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Haryana e-Procurement Adapter
# ---------------------------------------------------------------------------
class HaryanaTenderAdapter(BaseSourceAdapter):
    """Adapter for the Haryana e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://etenders.hry.nic.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and tender ID.
    """

    adapter_key = "haryana"
    adapter_label = "Haryana e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Haryana public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        # Use provided session or create a new one for cookie persistence.
        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                # Check for next page via pagination controls
                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Haryana",
                "source_url": detail_url,
                "source_name": "Haryana e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Himachal Pradesh e-Procurement Adapter
# ---------------------------------------------------------------------------
class HimachalPradeshTenderAdapter(BaseSourceAdapter):
    """Adapter for the Himachal Pradesh e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://hptenders.gov.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and tender ID.
    """

    adapter_key = "himachal_pradesh"
    adapter_label = "Himachal Pradesh e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Himachal Pradesh public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Himachal Pradesh",
                "source_url": detail_url,
                "source_name": "Himachal Pradesh e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Jammu & Kashmir e-Procurement Adapter
# ---------------------------------------------------------------------------
class JammuKashmirTenderAdapter(BaseSourceAdapter):
    """Adapter for the Jammu & Kashmir e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://jktenders.gov.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and tender ID.
    """

    adapter_key = "jammu_kashmir"
    adapter_label = "Jammu & Kashmir e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Jammu & Kashmir public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Jammu And Kashmir",
                "source_url": detail_url,
                "source_name": "Jammu & Kashmir e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Jharkhand e-Procurement Adapter
# ---------------------------------------------------------------------------
class JharkhandTenderAdapter(BaseSourceAdapter):
    """Adapter for the Jharkhand e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://jharkhandtenders.gov.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and tender ID.
    """

    adapter_key = "jharkhand"
    adapter_label = "Jharkhand e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Jharkhand public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Jharkhand",
                "source_url": detail_url,
                "source_name": "Jharkhand e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Manipur e-Procurement Adapter
# ---------------------------------------------------------------------------
class ManipurTenderAdapter(BaseSourceAdapter):
    """Adapter for the Manipur e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://manipurtenders.gov.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and tender ID.
    """

    adapter_key = "manipur"
    adapter_label = "Manipur e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Manipur public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Manipur",
                "source_url": detail_url,
                "source_name": "Manipur e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Meghalaya e-Procurement Adapter
# ---------------------------------------------------------------------------
class MeghalayaTenderAdapter(BaseSourceAdapter):
    """Adapter for the Meghalaya e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://meghalayatenders.gov.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and tender ID.
    """

    adapter_key = "meghalaya"
    adapter_label = "Meghalaya e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Meghalaya public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Meghalaya",
                "source_url": detail_url,
                "source_name": "Meghalaya e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Mizoram e-Procurement Adapter
# ---------------------------------------------------------------------------
class MizoramTenderAdapter(BaseSourceAdapter):
    """Adapter for the Mizoram e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://mizoramtenders.gov.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and tender ID.
    """

    adapter_key = "mizoram"
    adapter_label = "Mizoram e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Mizoram public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Mizoram",
                "source_url": detail_url,
                "source_name": "Mizoram e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Nagaland e-Procurement Adapter
# ---------------------------------------------------------------------------
class NagalandTenderAdapter(BaseSourceAdapter):
    """Adapter for the Nagaland e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://nagalandtenders.gov.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and tender ID.
    """

    adapter_key = "nagaland"
    adapter_label = "Nagaland e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Nagaland public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Nagaland",
                "source_url": detail_url,
                "source_name": "Nagaland e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Tripura e-Procurement Adapter
# ---------------------------------------------------------------------------
class TripuraTenderAdapter(BaseSourceAdapter):
    """Adapter for the Tripura e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://tripuratenders.gov.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and tender ID.
    """

    adapter_key = "tripura"
    adapter_label = "Tripura e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Tripura public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Tripura",
                "source_url": detail_url,
                "source_name": "Tripura e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Uttar Pradesh e-Procurement Adapter
# ---------------------------------------------------------------------------
class UttarPradeshTenderAdapter(BaseSourceAdapter):
    """Adapter for the Uttar Pradesh e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://etender.up.nic.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and tender ID.
    """

    adapter_key = "uttar_pradesh"
    adapter_label = "Uttar Pradesh e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Uttar Pradesh public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Uttar Pradesh",
                "source_url": detail_url,
                "source_name": "Uttar Pradesh e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Uttarakhand e-Procurement Adapter
# ---------------------------------------------------------------------------
class UttarakhandTenderAdapter(BaseSourceAdapter):
    """Adapter for the Uttarakhand e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://uktenders.gov.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and tender ID.
    """

    adapter_key = "uttarakhand"
    adapter_label = "Uttarakhand e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the Uttarakhand public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of Uttarakhand",
                "source_url": detail_url,
                "source_name": "Uttarakhand e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# West Bengal e-Procurement Adapter
# ---------------------------------------------------------------------------
class WestBengalTenderAdapter(BaseSourceAdapter):
    """Adapter for the West Bengal e-Procurement Portal (NIC GePNIC).

    Collects bids from the public listing page at
    https://wbtenders.gov.in/nicgep/app using HTML parsing with
    BeautifulSoup. Detail pages are fetched using the same requests session
    to preserve cookies/session tokens where the portal supports it.

    Listing page columns: Bid Title, Reference No, Closing Date,
    Bid Opening Date. Detail pages (session-bound) may contain additional
    fields such as organisation, estimated value, location, and tender ID.
    """

    adapter_key = "west_bengal"
    adapter_label = "West Bengal e-Procurement Portal"
    source_types = ("html_listing",)
    method = "http"
    requires_browser = False

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = super().validate_config(config)
        self._validate_url_field(cfg, "url")
        return cfg

    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        """Collect bids from the West Bengal public listing.

        Uses the same requests session for listing and detail pages so that
        session tokens remain valid across requests within a single
        collection run.
        """
        errors: List[Dict[str, str]] = []
        records: List[RawBidRecord] = []
        pages_visited = 0

        url = str(config["url"])
        max_pages = int(config.get("max_pages") or 1)
        max_records = int(config.get("max_records") or 0)

        http_session = session if isinstance(session, requests.Session) else requests.Session()

        try:
            current_url = url
            for page_num in range(max_pages):
                try:
                    resp = self._safe_fetch(current_url, http_session, config)
                except (BlockedResponseError, UrlNotPermittedError, SafeFetchError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    errors.append(safe_error("fetch", f"page {page_num + 1}: {exc}"))
                    break

                if resp.status_code == 404:
                    errors.append(safe_error("fetch", f"page {page_num + 1}: HTTP 404"))
                    break

                soup = self._to_soup(resp.text)
                rows = soup.select("#activeTenders tr[id^='informal']")
                pages_visited += 1

                if not rows:
                    break

                for row in rows:
                    rec = self._extract_record(row, url, config)
                    if rec is not None:
                        records.append(rec)
                        if max_records and len(records) >= max_records:
                            return CollectResult(
                                records=records,
                                pages_visited=pages_visited,
                                errors=errors,
                                method="http",
                            )

                next_selector = str((config.get("pagination") or {}).get("next_selector") or "").strip()
                if next_selector:
                    next_anchor = soup.select_one(next_selector)
                    if next_anchor:
                        next_href = str(next_anchor.get("href") or "").strip()
                        if next_href:
                            current_url = urllib.parse.urljoin(current_url, next_href)
                            continue
                    break
                else:
                    break
        except (BlockedResponseError, UrlNotPermittedError):
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(safe_error("fetch", str(exc)))

        return CollectResult(
            records=records,
            pages_visited=pages_visited,
            errors=errors,
            method="http",
        )

    def _extract_record(self, row, base_url: str, config: Dict[str, Any]) -> Optional[RawBidRecord]:
        """Extract a single bid record from a GePNIC-style listing row."""
        try:
            title_anchor = row.select_one("td a.link2")
            if title_anchor is None:
                return None

            title = title_anchor.get_text(" ", strip=True)
            if not title:
                return None

            detail_href = title_anchor.get("href", "")
            detail_url = urllib.parse.urljoin(base_url, detail_href)

            try:
                validate_public_url(detail_url, allowed_hosts=_allowed_hosts())
            except UrlNotPermittedError:
                return None

            cells = row.select("td")
            if len(cells) < 4:
                return None

            reference_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            closing_date = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            bid_opening_date = cells[3].get_text(" ", strip=True) if len(cells) > 3 else None

            kwargs: Dict[str, Any] = {
                "gem_bid_id": reference_no,
                "bid_number": reference_no,
                "title": title,
                "organisation": "Government of West Bengal",
                "source_url": detail_url,
                "source_name": "West Bengal e-Procurement",
                "published_date": bid_opening_date,
                "closing_date": closing_date,
                "category": None,
                "department": None,
                "ministry": None,
                "location": None,
                "estimated_value": None,
                "currency": "INR",
                "scope_of_work": None,
                "technical_requirements": None,
                "eligibility_criteria": None,
                "qualification_requirements": None,
                "experience_requirements": None,
                "certification_requirements": None,
                "emd_information": None,
                "tender_fee_information": None,
                "contact_information": None,
                "bid_type": None,
            }

            return RawBidRecord(**kwargs)

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
            logger.warning(f"Failed to extract bid record from row: {exc}")
            return None

    def _to_soup(self, markup: str):
        return BeautifulSoup(markup, "lxml")

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        import time as _t

        start = _t.perf_counter()
        try:
            resp = self._safe_fetch(str(config["url"]), session, config)
            soup = self._to_soup(resp.text)
            rows = soup.select("#activeTenders tr[id^='informal']")
            return ConnectionTestResult(
                ok=True,
                message=(
                    f"Portal reachable (HTTP {resp.status_code}); "
                    f"{len(rows)} tender row(s) found."
                ),
                http_status=resp.status_code,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
                method="http",
            )
        except BlockedResponseError as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Source refused automated collection (HTTP {exc.http_status}).",
                http_status=exc.http_status,
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                message=f"Connection failed: {str(exc)[:200]}",
                duration_ms=(_t.perf_counter() - start) * 1000.0,
            )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def _allowlist() -> Optional[List[str]]:
    from app.core.config import settings

    raw = str(getattr(settings, "SOURCE_ALLOWED_HOSTS", "") or "").strip()
    if not raw:
        return None
    return [h.strip() for h in raw.split(",") if h.strip()]


_ADAPTERS: Dict[str, BaseSourceAdapter] = {}


def all_adapters() -> Dict[str, BaseSourceAdapter]:
    if not _ADAPTERS:
        for adapter in (
            RssFeedAdapter(),
            JsonApiAdapter(),
            HtmlListingAdapter(),
            PlaywrightListingAdapter(),
            ArunachalPradeshTenderAdapter(),
            ChhattisgarhTenderAdapter(),
            TamilNaduTenderAdapter(),
            MaharashtraTenderAdapter(),
            DelhiTenderAdapter(),
            RajasthanTenderAdapter(),
            MadhyaPradeshTenderAdapter(),
            OdishaTenderAdapter(),
            PunjabTenderAdapter(),
            SikkimTenderAdapter(),
            KeralaTenderAdapter(),
            AssamTenderAdapter(),
            ChandigarhTenderAdapter(),
            HaryanaTenderAdapter(),
            HimachalPradeshTenderAdapter(),
            JammuKashmirTenderAdapter(),
            JharkhandTenderAdapter(),
            ManipurTenderAdapter(),
            MeghalayaTenderAdapter(),
            MizoramTenderAdapter(),
            NagalandTenderAdapter(),
            TripuraTenderAdapter(),
            UttarPradeshTenderAdapter(),
            UttarakhandTenderAdapter(),
            WestBengalTenderAdapter(),
        ):
            _ADAPTERS[adapter.adapter_key] = adapter
    return _ADAPTERS


def get_adapter(adapter_key: str) -> Optional[BaseSourceAdapter]:
    return all_adapters().get(adapter_key)


def get_adapter_for_source_type(source_type: str) -> Optional[BaseSourceAdapter]:
    for adapter in all_adapters().values():
        if source_type in adapter.source_types:
            return adapter
    return None


def adapter_catalog() -> List[Dict[str, Any]]:
    """Secret-free catalog describing every adapter for the source UI."""
    catalog = []
    for adapter in all_adapters().values():
        catalog.append(
            {
                "adapter_key": adapter.adapter_key,
                "adapter_label": adapter.adapter_label,
                "source_types": list(adapter.source_types),
                "method": adapter.method,
                "requires_credentials": adapter.requires_credentials,
                "requires_browser": adapter.requires_browser,
                "integration_note": adapter.integration_note,
            }
        )
    return catalog
