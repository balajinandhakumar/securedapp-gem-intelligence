"""
Bid source adapters.

Every adapter converts a raw file (bytes / path) into a list of
``RawBidRecord`` instances.  The rest of the pipeline is format-agnostic.

Protocol:
    class BidSourceAdapter:
        adapter_name: str
        def parse(self, data: bytes, filename: str) -> list[RawBidRecord]: ...
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Union

from app.services.ingestion.schemas import RawBidRecord
from app.services.ingestion.field_aliases import resolve_field_name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _map_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map a dict with arbitrary column names to canonical RawBidRecord fields."""
    mapped: Dict[str, Any] = {}
    for raw_key, value in row.items():
        canonical = resolve_field_name(str(raw_key))
        if canonical is not None:
            mapped[canonical] = value
    return mapped


def _row_to_record(mapped: Dict[str, Any], raw: Dict[str, Any]) -> RawBidRecord:
    """Build a RawBidRecord from mapped fields, attaching the original raw dict."""
    # Convert any non-string scalar values to strings for date/number fields
    for key in ("estimated_value", "published_date", "closing_date"):
        if key in mapped and mapped[key] is not None:
            val = mapped[key]
            if hasattr(val, "isoformat"):
                mapped[key] = val.isoformat()
            else:
                mapped[key] = str(val)
    record = RawBidRecord(**{k: str(v) if not isinstance(v, (dict, list, bool, type(None))) else v for k, v in mapped.items() if v is not None and v != ""})
    record._raw = raw
    return record


# ---------------------------------------------------------------------------
# JSON adapter
# ---------------------------------------------------------------------------
class JSONBidAdapter:
    adapter_name = "JSONBidAdapter"

    def parse(self, data: Union[bytes, str], filename: str = "upload.json", **kwargs) -> List[RawBidRecord]:
        if isinstance(data, str):
            data = data.encode("utf-8")
        # `utf-8-sig` transparently strips a byte-order mark if present. JSON
        # exports produced by spreadsheet and government tooling frequently carry
        # one, and a bare `utf-8` decode would reject those files outright.
        try:
            parsed = json.loads(data.decode("utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"Invalid JSON file: {exc}") from exc

        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            raise ValueError("JSON must be an array of bid objects or a single bid object.")

        records: List[RawBidRecord] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            mapped = _map_row(item)
            records.append(_row_to_record(mapped, dict(item)))
        return records


# ---------------------------------------------------------------------------
# CSV adapter
# ---------------------------------------------------------------------------
class CSVBidAdapter:
    adapter_name = "CSVBidAdapter"

    def parse(self, data: Union[bytes, str], filename: str = "upload.csv", **kwargs) -> List[RawBidRecord]:
        if isinstance(data, str):
            data = data.encode("utf-8")
        # `utf-8-sig` strips a byte-order mark if present, which would otherwise
        # corrupt the first column header and break field mapping.
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = data.decode("latin-1")
            except UnicodeDecodeError as exc:
                raise ValueError(f"Cannot decode CSV file: {exc}") from exc

        reader = csv.DictReader(io.StringIO(text))
        records: List[RawBidRecord] = []
        for row in reader:
            if not any(v for v in row.values() if v and str(v).strip()):
                continue
            mapped = _map_row(row)
            records.append(_row_to_record(mapped, dict(row)))
        return records


# ---------------------------------------------------------------------------
# XLSX adapter
# ---------------------------------------------------------------------------
class XLSXBidAdapter:
    adapter_name = "XLSXBidAdapter"

    def parse(self, data: bytes, filename: str = "upload.xlsx", **kwargs) -> List[RawBidRecord]:
        try:
            import openpyxl
        except ImportError as exc:
            raise RuntimeError("openpyxl is required for XLSX support") from exc

        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:
            raise ValueError(f"Invalid XLSX file: {exc}") from exc

        try:
            ws = wb.active
            if ws is None and len(wb.sheetnames) > 0:
                ws = wb[wb.sheetnames[0]]
            if ws is None:
                return []

            raw_rows = list(ws.iter_rows(values_only=True))
            if not raw_rows:
                return []

            # Find first non-empty row as header row
            header_idx = -1
            headers: list[str] = []
            for idx, r in enumerate(raw_rows):
                if r and any(c is not None and str(c).strip() for c in r):
                    headers = [str(c).strip() if c is not None else "" for c in r]
                    header_idx = idx
                    break

            if header_idx == -1 or len(raw_rows) <= header_idx + 1:
                return []

            records: List[RawBidRecord] = []
            for row_values in raw_rows[header_idx + 1:]:
                if not row_values or all(v is None or str(v).strip() == "" for v in row_values):
                    continue

                raw_dict: Dict[str, Any] = {}
                for idx, header in enumerate(headers):
                    if idx < len(row_values) and header:
                        val = row_values[idx]
                        if val is not None and str(val).strip() != "":
                            raw_dict[header] = val

                if not raw_dict:
                    continue

                mapped = _map_row(raw_dict)
                records.append(_row_to_record(mapped, raw_dict))

            return records
        finally:
            try:
                wb.close()
            except Exception:
                pass



# ---------------------------------------------------------------------------
# Approved GeM / Licensed Provider Source Adapters (Future Authorized Extensibility)
# ---------------------------------------------------------------------------
class ApprovedGeMAdapter:
    adapter_name = "ApprovedGeMAdapter"

    def parse(self, data: bytes, filename: str = "gem_api.json", **kwargs) -> List[RawBidRecord]:
        """
        Parses structured payloads from official, authorized GeM API or data feeds.
        Strict compliance: Does NOT scrape, bypass CAPTCHA, or use unauthorized access.
        """
        json_adapter = JSONBidAdapter()
        return json_adapter.parse(data, filename=filename, **kwargs)


class LicensedProviderAdapter:
    adapter_name = "LicensedProviderAdapter"

    def parse(self, data: bytes, filename: str = "provider_feed.json", **kwargs) -> List[RawBidRecord]:
        """
        Parses structured payloads from licensed procurement data providers.
        """
        json_adapter = JSONBidAdapter()
        return json_adapter.parse(data, filename=filename, **kwargs)


class ThirdPartyGeMAdapter:
    adapter_name = "ThirdPartyGeMProviderAdapter"

    def parse(
        self,
        data: Union[bytes, str, List[Dict[str, Any]], Dict[str, Any]],
        source_name: str = "third_party_feed",
        **kwargs
    ) -> List[RawBidRecord]:
        """
        Parses structured payloads received from a third-party structured
        procurement feed or dataset export (list of bid objects, or JSON).
        """
        if isinstance(data, (bytes, str)):
            json_adapter = JSONBidAdapter()
            return json_adapter.parse(data, filename=source_name, **kwargs)

        if isinstance(data, dict):
            data = [data]

        if not isinstance(data, list):
            raise ValueError(f"Expected list of bid objects or JSON payload, got {type(data)}")

        records: List[RawBidRecord] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            mapped = _map_row(item)
            records.append(_row_to_record(mapped, dict(item)))
        return records


# ---------------------------------------------------------------------------
# Direct GeM Public Collector Adapter
# ---------------------------------------------------------------------------
# The direct collector reads publicly reachable GeM pages itself. It is
# registered here so the collected markup flows through the very same adapter
# interface as every other source rather than a parallel ingestion path.
from app.services.ingestion.gem_direct_adapter import GeMPublicAdapter  # noqa: E402


# ---------------------------------------------------------------------------
# Registry & Aliases
# ---------------------------------------------------------------------------
JSONAdapter = JSONBidAdapter
CSVAdapter = CSVBidAdapter
XLSXAdapter = XLSXBidAdapter
GeMProviderAdapter = ThirdPartyGeMAdapter

ADAPTER_MAP = {
    "json": JSONBidAdapter,
    "csv": CSVBidAdapter,
    "xlsx": XLSXBidAdapter,
    "gem_api": ApprovedGeMAdapter,
    "licensed_provider": LicensedProviderAdapter,
    "gem_provider": ThirdPartyGeMAdapter,
    "third_party_gem": ThirdPartyGeMAdapter,
    "gem_direct": GeMPublicAdapter,
}
registry = ADAPTER_MAP


def get_adapter_for_extension(extension: str):
    """Return an adapter instance for the given file extension or provider key (without dot)."""
    ext = extension.lower().lstrip(".")
    cls = ADAPTER_MAP.get(ext)
    if cls is None:
        raise ValueError(f"Unsupported file format / provider: {ext}  (supported: {', '.join(ADAPTER_MAP)})")
    return cls()


get_adapter = get_adapter_for_extension


