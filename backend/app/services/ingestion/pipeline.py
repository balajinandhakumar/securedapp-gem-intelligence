"""
Bid Ingestion Pipeline Orchestrator.

Orchestrates raw data ingestion from adapters, validation, normalization,
duplicate detection, DB persistence, and audit logging into CollectionRun & RawBidPayload.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import BinaryIO, Optional, Union
from sqlalchemy.orm import Session

from app.models.bid import Bid
from app.models.collection import CollectionRun, RawBidPayload
from app.services.ingestion.adapters import get_adapter
from app.services.ingestion.duplicate_detector import check_duplicate
from app.services.ingestion.normalizer import normalize_record
from app.services.ingestion.schemas import ImportResult, RecordValidationError
from app.services.ingestion.validator import validate_records

logger = logging.getLogger(__name__)


def run_ingestion_pipeline(
    db: Session,
    file_content: Union[bytes, str, BinaryIO],
    file_type: str,
    source_name: str = "manual_file_upload",
    allow_update_duplicates: bool = False,
) -> ImportResult:
    """
    Runs the complete bid ingestion pipeline for a given file or raw content.
    """
    run_id = uuid.uuid4()
    run = CollectionRun(
        id=run_id,
        source_adapter=f"{file_type.upper()}_Adapter",
        started_at=datetime.now(timezone.utc),
        status="RUNNING",
        notes=f"Ingesting file from source: {source_name}",
    )
    db.add(run)
    db.flush()

    try:
        # 1. Select Adapter and Parse Raw Records
        adapter = get_adapter(file_type)
        raw_records = adapter.parse(file_content, source_name=source_name)

        run.records_found = len(raw_records)

        # Preserve raw payloads in DB
        for raw in raw_records:
            payload_dict = raw.model_dump(exclude_none=True)
            db.add(RawBidPayload(
                collection_run_id=run.id,
                raw_content=payload_dict,
                source_reference=source_name,
            ))
        db.flush()

        # 2. Validation Step
        valid_records, invalid_records = validate_records(raw_records)

        errors: list[RecordValidationError] = []
        for inv in invalid_records:
            errors.extend(inv.errors)

        created_count = 0
        updated_count = 0
        duplicate_count = 0

        # 3. Normalization & Duplicate Detection & Persistence
        for val_rec in valid_records:
            raw = val_rec.raw
            normalized = normalize_record(raw)

            # Duplicate Check
            dup_result = check_duplicate(db, normalized)

            if dup_result.is_duplicate:
                duplicate_count += 1
                if allow_update_duplicates and dup_result.existing_bid:
                    bid = dup_result.existing_bid
                    for k, v in normalized.items():
                        if k not in ("id", "created_at", "hash") and v is not None:
                            setattr(bid, k if k != "hash" else "content_hash", v)
                    bid.last_updated_at = datetime.now(timezone.utc)
                    updated_count += 1
            else:
                bid_data = dict(normalized)
                content_hash = bid_data.pop("hash", None)
                bid_data["content_hash"] = content_hash
                bid_data["status"] = "NEW"

                # Filter fields to match columns on Bid model
                valid_bid_keys = {c.name for c in Bid.__table__.columns}
                filtered_bid_data = {k: v for k, v in bid_data.items() if k in valid_bid_keys}

                bid = Bid(**filtered_bid_data)
                db.add(bid)
                db.flush()
                created_count += 1





        run.records_new = created_count
        run.records_duplicate = duplicate_count
        run.error_count = len(invalid_records)
        run.finished_at = datetime.now(timezone.utc)

        if len(invalid_records) == len(raw_records) and len(raw_records) > 0:
            run.status = "FAILED"
        elif len(invalid_records) > 0:
            run.status = "PARTIAL"
        else:
            run.status = "SUCCESS"

        db.commit()

        return ImportResult(
            run_id=run_id,
            status=run.status.lower(),
            total_records=len(raw_records),
            created=created_count,
            updated=updated_count,
            duplicates=duplicate_count,
            failed=len(invalid_records),
            errors=errors,
        )

    except Exception as e:
        db.rollback()
        logger.exception("Ingestion pipeline failed")
        run_fail = db.get(CollectionRun, run_id)
        if run_fail:
            run_fail.status = "FAILED"
            run_fail.notes = f"Pipeline execution failed: {str(e)}"
            run_fail.finished_at = datetime.now(timezone.utc)
            db.commit()


        raise e
