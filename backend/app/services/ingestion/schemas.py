"""
Pydantic schemas for the ingestion pipeline.

These schemas are internal to the ingestion service layer and define the
canonical raw-record shape that every adapter must produce, independent of
the source format (CSV, XLSX, JSON, future API).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Canonical raw record – every adapter converts its source rows into this
# ---------------------------------------------------------------------------
class RawBidRecord(BaseModel):
    @property
    def certifications_required(self) -> Optional[Any]:
        """Alias for certification_requirements to maintain backward compatibility with tests."""
        return self.certification_requirements
    """One raw bid record as extracted by an adapter, before validation/normalization."""
    gem_bid_id: Optional[str] = None
    bid_number: Optional[str] = None
    title: Optional[str] = None
    organisation: Optional[str] = None
    department: Optional[str] = None
    ministry: Optional[str] = None
    category: Optional[str] = None
    bid_type: Optional[str] = None
    published_date: Optional[str] = None
    closing_date: Optional[str] = None
    location: Optional[str] = None
    estimated_value: Optional[str] = None  # kept as str until normalizer parses it
    currency: Optional[str] = None
    scope_of_work: Optional[str] = None
    technical_requirements: Optional[Any] = None
    eligibility_criteria: Optional[Any] = None
    qualification_requirements: Optional[Any] = None
    experience_requirements: Optional[Any] = None
    certification_requirements: Optional[Any] = None
    emd_information: Optional[Any] = None
    tender_fee_information: Optional[Any] = None
    contact_information: Optional[Any] = None
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    # Original source row preserved for raw-payload storage
    _raw: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Validation result for a single record
# ---------------------------------------------------------------------------
class RecordValidationError(BaseModel):
    record_index: int
    field: str
    message: str


class ValidatedBidRecord(BaseModel):
    """A bid record that passed validation, with dates/numbers still as strings."""
    raw: RawBidRecord
    errors: List[RecordValidationError] = []
    is_valid: bool = True


# ---------------------------------------------------------------------------
# Import / collection-run result returned to callers
# ---------------------------------------------------------------------------
class ImportResult(BaseModel):
    run_id: uuid.UUID
    status: str  # completed, partial, failed
    total_records: int = 0
    created: int = 0
    updated: int = 0
    duplicates: int = 0
    failed: int = 0
    errors: List[RecordValidationError] = []
