"""
Ingestion package: adapters, normalizer, validator, duplicate detector, and pipeline orchestrator.
"""
from app.services.ingestion.adapters import (
    CSVAdapter,
    JSONAdapter,
    XLSXAdapter,
    ApprovedGeMAdapter,
    LicensedProviderAdapter,
    ThirdPartyGeMAdapter,
    GeMProviderAdapter,
    get_adapter,
    registry,
)
from app.services.ingestion.duplicate_detector import (
    DuplicateCheckResult,
    check_duplicate,
)
from app.services.ingestion.normalizer import normalize_record
from app.services.ingestion.pipeline import run_ingestion_pipeline
from app.services.ingestion.schemas import (
    ImportResult,
    RawBidRecord,
    ValidatedBidRecord,
)
from app.services.ingestion.validator import validate_record, validate_records

__all__ = [
    "JSONAdapter",
    "CSVAdapter",
    "XLSXAdapter",
    "ApprovedGeMAdapter",
    "LicensedProviderAdapter",
    "ThirdPartyGeMAdapter",
    "GeMProviderAdapter",
    "get_adapter",
    "registry",
    "check_duplicate",
    "DuplicateCheckResult",
    "normalize_record",
    "run_ingestion_pipeline",
    "ImportResult",
    "RawBidRecord",
    "ValidatedBidRecord",
    "validate_record",
    "validate_records",
]
