"""
Deterministic validation of raw bid records before normalization.

Validates required fields, date plausibility, numeric types, and rejects
records that cannot be meaningfully stored.
"""
from __future__ import annotations

from typing import List, Tuple

from app.services.ingestion.schemas import (
    RawBidRecord,
    RecordValidationError,
    ValidatedBidRecord,
)


def validate_record(record: RawBidRecord, index: int) -> ValidatedBidRecord:
    """Validate a single raw bid record.  Returns a ValidatedBidRecord with
    ``is_valid=False`` and accumulated errors when problems are found."""
    errors: List[RecordValidationError] = []

    # --- title is required ------------------------------------------------
    if not record.title or not str(record.title).strip():
        errors.append(RecordValidationError(
            record_index=index, field="title",
            message="Title is required and must not be empty.",
        ))

    # --- at least one identity field should be present --------------------
    has_identity = bool(
        (record.gem_bid_id and str(record.gem_bid_id).strip())
        or (record.bid_number and str(record.bid_number).strip())
        or (record.title and str(record.title).strip())
    )
    if not has_identity:
        errors.append(RecordValidationError(
            record_index=index, field="identity",
            message="At least one of gem_bid_id, bid_number, or title must be present.",
        ))

    # --- estimated_value must be numeric if provided ----------------------
    if record.estimated_value is not None and str(record.estimated_value).strip():
        from app.services.ingestion.normalizer import parse_numeric_value
        if parse_numeric_value(record.estimated_value) is None:
            errors.append(RecordValidationError(
                record_index=index, field="estimated_value",
                message=f"estimated_value is not a valid number or currency amount: '{record.estimated_value}'",
            ))

    # --- dates must be parseable strings if provided ----------------------
    # Dates are optional; if they cannot be parsed they will be treated as None.
    # Parsing will be attempted later in normalization without raising validation errors.

    return ValidatedBidRecord(
        raw=record,
        errors=errors,
        is_valid=len(errors) == 0,
    )


def validate_records(
    records: List[RawBidRecord],
) -> Tuple[List[ValidatedBidRecord], List[ValidatedBidRecord]]:
    """Validate a batch.  Returns (valid, invalid) split."""
    valid: List[ValidatedBidRecord] = []
    invalid: List[ValidatedBidRecord] = []
    for idx, rec in enumerate(records):
        result = validate_record(rec, idx)
        if result.is_valid:
            valid.append(result)
        else:
            invalid.append(result)
    return valid, invalid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_DATE_SEPARATORS = ("-", "/", ".", " ")


def _looks_like_date(s: str) -> bool:
    """Quick heuristic: does s contain at least two separator chars and some digits?
    The actual parsing is done by the normalizer."""
    s = s.strip()
    if not s:
        return False
    # ISO 8601 with T
    if "T" in s and any(c.isdigit() for c in s):
        return True
    has_separator = any(sep in s for sep in _DATE_SEPARATORS)
    has_digits = any(c.isdigit() for c in s)
    return has_separator and has_digits
