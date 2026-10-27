"""
Data normalization service for bid records.

Handles date parsing, numeric/currency standardization, text cleaning,
search text generation, structural metadata JSON cleanup, and content hashing.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.ingestion.schemas import RawBidRecord

# Prefix + length of the derived composite identity used when a source declares
# that its raw identifier (e.g. a GePNIC "Reference No") is not unique per row.
# 6 + 40 = 46 chars, comfortably inside the Bid.gem_bid_id String(100) column.
_COMPOSITE_IDENTITY_PREFIX = "srcid-"
_COMPOSITE_IDENTITY_DIGEST_LEN = 40

# A listing that stamps a per-row serial number onto the title ("1. Repair ...",
# "2. Repair ...") must not let that ordinal leak into the identity: the same
# tender can be re-numbered between syncs. Only applied to the title field.
_LEADING_ORDINAL_RE = re.compile(r"^\s*\d+\s*[\.\)]\s*")


def _identity_field_text(field: str, value: Any) -> str:
    text = _clean_str(value) or ""
    if field == "title":
        text = _LEADING_ORDINAL_RE.sub("", text)
    return text.casefold()


def derive_composite_identity(
    identity_fields: List[str], values: Dict[str, Any]
) -> str:
    """Deterministic identity from several *stable* source fields.

    Used only when a source opts in (``config["identity_fields"]``) because its
    native identifier is not row-unique. The same tender always yields the same
    value; distinct tenders that share an identifier but differ in any listed
    field yield different values. Case/whitespace differences are ignored and a
    leading list serial number is stripped from the title.

    Never includes dates, so a corrigendum that only moves dates keeps the same
    identity (and is therefore treated as an update, not a new tender).
    """
    parts: List[str] = []
    for field in identity_fields:
        parts.append(f"{field}={_identity_field_text(field, values.get(field))}")
    basis = "\u0001".join(parts)
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[
        :_COMPOSITE_IDENTITY_DIGEST_LEN
    ]
    return f"{_COMPOSITE_IDENTITY_PREFIX}{digest}"


def normalize_record(
    raw: RawBidRecord, *, identity_fields: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Transform a RawBidRecord into a dictionary matching the database Bid model schema.
    """
    gem_bid_id = _clean_str(raw.gem_bid_id)
    bid_number = _clean_str(raw.bid_number)
    if identity_fields:
        # Opt-in composite identity: the source declared that its native
        # identifier is not row-unique, so identity is derived from several
        # stable fields. ``bid_number`` is kept as the human-readable reference.
        values = {name: getattr(raw, name, None) for name in RawBidRecord.model_fields}
        gem_bid_id = derive_composite_identity(identity_fields, values)
    else:
        if not gem_bid_id and bid_number:
            gem_bid_id = bid_number
        if not bid_number and gem_bid_id:
            bid_number = gem_bid_id

    title = _clean_str(raw.title) or "Untitled Bid"
    organisation = _clean_str(raw.organisation)
    department = _clean_str(raw.department)
    ministry = _clean_str(raw.ministry)
    category = _clean_str(raw.category)
    bid_type = _clean_str(raw.bid_type) or "BUYER_SPECIFIC"
    location = _clean_str(raw.location)
    scope_of_work = _clean_str(raw.scope_of_work)

    published_date = parse_datetime(raw.published_date)
    closing_date = parse_datetime(raw.closing_date)

    estimated_value = parse_numeric_value(raw.estimated_value)
    currency = _clean_str(raw.currency).upper() if raw.currency else "INR"

    # JSON fields
    technical_requirements = _ensure_json_dict(raw.technical_requirements)
    eligibility_criteria = _ensure_json_dict(raw.eligibility_criteria)
    qualification_requirements = _ensure_json_dict(raw.qualification_requirements)
    experience_requirements = _ensure_json_dict(raw.experience_requirements)
    certification_requirements = _ensure_json_dict(raw.certification_requirements)
    emd_information = _ensure_json_dict(raw.emd_information)
    tender_fee_information = _ensure_json_dict(raw.tender_fee_information)
    contact_information = _ensure_json_dict(raw.contact_information)

    # Compute combined search text for search indexing
    search_parts = [
        gem_bid_id,
        bid_number,
        title,
        organisation,
        department,
        ministry,
        category,
        location,
        scope_of_work,
    ]
    search_text = " ".join([p for p in search_parts if p])

    # Compute content hash for exact content duplicate check
    hash_payload = json.dumps({
        "gem_bid_id": gem_bid_id,
        "title": title,
        "organisation": organisation,
        "estimated_value": estimated_value,
        "closing_date": closing_date.isoformat() if closing_date else None,
    }, sort_keys=True)
    content_hash = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()

    return {
        "gem_bid_id": gem_bid_id,
        "bid_number": bid_number,
        "title": title,
        "organisation": organisation,
        "department": department,
        "ministry": ministry,
        "category": category,
        "bid_type": bid_type,
        "published_date": published_date,
        "closing_date": closing_date,
        "location": location,
        "estimated_value": estimated_value,
        "currency": currency,
        "scope_of_work": scope_of_work,
        "technical_requirements": technical_requirements,
        "eligibility_criteria": eligibility_criteria,
        "qualification_requirements": qualification_requirements,
        "experience_requirements": experience_requirements,
        "certification_requirements": certification_requirements,
        "emd_information": emd_information,
        "tender_fee_information": tender_fee_information,
        "contact_information": contact_information,
        "source_url": _clean_str(raw.source_url),
        "source_name": _clean_str(raw.source_name) or "manual_import",
        "search_text": search_text,
        "hash": content_hash,
    }


# ---------------------------------------------------------------------------
# Helper parsers
# ---------------------------------------------------------------------------
def _clean_str(val: Optional[Any]) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("none", "null", "nan", "n/a"):
        return None
    # normalize multiple spaces / newlines
    return re.sub(r"\s+", " ", s)


def parse_datetime(val: Optional[Any]) -> Optional[datetime]:
    """Parse various date/time formats into UTC datetime."""
    if not val:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)

    s = str(val).strip()
    if not s:
        return None

    # Common formats including CPPP / GeM tender date formats.
    #
    # Numeric day-first formats are listed BEFORE dateutil is consulted.
    # dateutil's default is month-first, so a bare "05-10-2026" would silently
    # become 10 May. The live GeM listing is day-first: its start_date values
    # reach 24 and 31 in the first component, which no month can, so DD-MM is
    # the only reading consistent with the source.
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d-%b-%Y %I:%M %p",      # e.g. "24-Sep-2026 09:22 PM" (CPPP / GeM standard)
        "%d-%b-%Y %I:%M:%S %p",   # e.g. "24-Sep-2026 09:22:00 PM"
        "%d-%b-%Y %H:%M:%S",
        "%d-%b-%Y %H:%M",
        "%d-%b-%Y",
        # Day-first numeric forms, including the exact shape the live GeM
        # listing renders: "05-10-2026 9:00 PM".
        "%d-%m-%Y %I:%M:%S %p",
        "%d-%m-%Y %I:%M %p",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%d-%m-%Y",
        "%d/%m/%Y %I:%M:%S %p",
        "%d/%m/%Y %I:%M %p",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue

    # dateutil and ISO fallback.
    # dayfirst=True: every remaining numeric form reaching here is day-first,
    # and a month-first guess would move a bid's deadline by months.
    try:
        from dateutil import parser as dt_parser
        dt = dt_parser.parse(s, dayfirst=True)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass

    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass

    return None


def parse_numeric_value(val: Optional[Any]) -> Optional[float]:
    """Extract and parse numeric values handling currency strings, commas, multipliers, etc."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)

    s = str(val).strip()
    if not s:
        return None

    # Check for multiplier terms like Cr, Lakh, Million
    multiplier = 1.0
    if re.search(r"\b(?:crores?|cr\.?)\b", s, re.IGNORECASE):
        multiplier = 10_000_000.0
    elif re.search(r"\b(?:lakhs?|lacs?)\b", s, re.IGNORECASE):
        multiplier = 100_000.0
    elif re.search(r"\b(?:millions?|m)\b", s, re.IGNORECASE):
        multiplier = 1_000_000.0

    # Remove currency words, symbols, commas, and trailing / -
    cleaned = re.sub(r"(?i)\b(?:rs\.?|inr\.?|usd\.?|eur\.?|crores?|cr\.?|lakhs?|lacs?|millions?)\b", "", s)
    cleaned = re.sub(r"[₹$,\s/\\-]", "", cleaned)

    match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
    if match:
        try:
            return float(match.group()) * multiplier
        except ValueError:
            return None
    return None


def _ensure_json_dict(val: Optional[Any]) -> Optional[Dict[str, Any]]:
    if val is None:
        return None
    if isinstance(val, dict):
        return val
    if isinstance(val, list):
        return {"items": val}
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        try:
            parsed = json.loads(s)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                return {"items": parsed}
            return {"raw": parsed}
        except json.JSONDecodeError:
            return {"raw": s}
    return {"raw": str(val)}
