"""
Multi-source run orchestrator.

``run_source_sync`` drives one configured source through the *existing*
pipeline without creating a parallel ingestion architecture::

    adapter.collect()  -> canonical RawBidRecord
    -> same-run de-duplication
    -> existing validate_records -> existing normalize_record
    -> existing check_duplicate -> DB persist (new / update)
    -> existing process_bid_intelligence (+ notifications)

Every run writes a ``SourceRun`` audit row with per-stage counters and safe
(trimmed, secret-free) error details, then updates the source row's live
status/last-run counts. Per-source in-process locks guarantee a source is
never collected concurrently (manual vs scheduled), while independent sources
fail and recover on their own.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.models.bid import Bid
from app.models.source import DataSource, SourceRun
from app.services.ingestion.duplicate_detector import check_duplicate
from app.services.ingestion.normalizer import (
    derive_composite_identity,
    normalize_record,
)
from app.services.ingestion.schemas import RawBidRecord
from app.services.ingestion.validator import validate_records
from app.services.intelligence.batch_processor import process_bid_intelligence
from app.services.intelligence.opportunity_analyzer import OpportunityAnalyzer
from app.services.intelligence.providers import DeterministicLLMProvider
from app.services.sources.base import SourceConfigError, safe_error
from app.services.sources.safe_http import (
    BlockedResponseError,
    SafeFetchError,
    UrlNotPermittedError,
)

logger = logging.getLogger(__name__)

_run_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _source_lock(source_id: str) -> threading.Lock:
    with _locks_guard:
        lock = _run_locks.get(source_id)
        if lock is None:
            lock = threading.Lock()
            _run_locks[source_id] = lock
        return lock


def _safe_text(value: Any, trim: int = 500) -> str:
    text = str(value or "").strip().replace("\n", " ")
    return text[:trim] + ("..." if len(text) > trim else "")


def run_source_sync(
    db: Session,
    source: DataSource,
    *,
    trigger: str = "manual",
    preview: bool = False,
    session: Any = None,
    now: Optional[datetime] = None,
    allow_update_duplicates: bool = True,
    auto_notify: bool = True,
) -> Dict[str, Any]:
    """Collect one configured source and push it through the existing pipeline.

    Returns a secret-free result dict. ``session`` is the SSRF-safe transport
    (injectable for tests). ``now`` injects the clock (for scheduler tests).
    """
    now = now or datetime.now(timezone.utc)
    start = time.perf_counter()
    run: Optional[SourceRun] = None

    def _result(status: str, message: str, **extra: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "run_id": str(run.id) if run is not None else None,
            "source_id": source.source_id,
            "source_name": source.name,
            "source_type": source.source_type,
            "adapter_key": source.adapter_key,
            "status": status,
            "trigger": trigger,
            "preview": preview,
            "message": message,
            "pages_visited": int(
                run.pages_visited if run is not None else extra.pop("pages_visited", 0)
            ),
            "discovered": int(
                run.records_discovered
                if run is not None
                else extra.pop("discovered", 0)
            ),
            "validated": int(
                run.validated if run is not None else extra.pop("validated", 0)
            ),
            "rejected": int(
                run.rejected if run is not None else extra.pop("rejected", 0)
            ),
            "inserted": int(
                run.inserted if run is not None else extra.pop("inserted", 0)
            ),
            "updated": int(run.updated if run is not None else extra.pop("updated", 0)),
            "duplicates": int(
                run.duplicates if run is not None else extra.pop("duplicates", 0)
            ),
            "errors": list(run.errors or [])
            if run is not None
            else list(extra.pop("errors", [])),
            "duration_seconds": round(time.perf_counter() - start, 3),
        }
        payload.update(extra)
        return payload

    if not source.enabled:
        _mark_run(
            db,
            source,
            "SKIPPED",
            "Source is disabled. Enable it before collecting.",
            now=now,
            trigger=trigger,
        )
        return _result("SKIPPED", "Source is disabled. Enable it before collecting.")

    lock = _source_lock(str(source.id))
    if not lock.acquire(blocking=False):
        _mark_run(
            db,
            source,
            "BUSY",
            "A run for this source is already in progress.",
            now=now,
            trigger=trigger,
        )
        return _result("BUSY", "A run for this source is already in progress.")

    try:
        try:
            adapter = _adapter_for(source)
        except SourceConfigError:
            raise

        try:
            config = adapter.validate_config(source.config or {})
        except SourceConfigError as exc:
            _finalize_run(
                db,
                source,
                status="CONFIG_ERROR",
                message=_safe_text(exc.safe_message),
                errors=[safe_error("config", exc.safe_message)],
                now=now,
                trigger=trigger,
            )
            return _result(
                "CONFIG_ERROR",
                _safe_text(exc.safe_message),
                errors=[safe_error("config", exc.safe_message)],
            )

        run = SourceRun(
            id=uuid.uuid4(),
            source_id=source.id,
            trigger=trigger,
            started_at=now,
            status="RUNNING",
        )
        db.add(run)
        db.flush()

        # Mark the source running (bare minimum broadcast).
        source.last_attempt_at = now
        source.status = "RUNNING"
        db.flush()

        try:
            collected = adapter.collect(config, name=source.name, session=session)
        except BlockedResponseError as exc:
            _finalize_run(
                db,
                source,
                status="BLOCKED",
                message=_safe_text(exc.message),
                errors=[safe_error("blocked", exc.message)],
                run=run,
                now=now,
                trigger=trigger,
            )
            return _result(
                "BLOCKED",
                _safe_text(exc.message),
                errors=[safe_error("blocked", exc.message)],
            )
        except SourceConfigError as exc:
            _finalize_run(
                db,
                source,
                status="CONFIG_ERROR",
                message=_safe_text(exc.safe_message),
                errors=[safe_error("config", exc.safe_message)],
                run=run,
                now=now,
                trigger=trigger,
            )
            return _result(
                "CONFIG_ERROR",
                _safe_text(exc.safe_message),
                errors=[safe_error("config", exc.safe_message)],
            )
        except (SafeFetchError, UrlNotPermittedError) as exc:
            _finalize_run(
                db,
                source,
                status="ERROR",
                message=_safe_text(exc.message or exc),
                errors=[safe_error("fetch", exc)],
                run=run,
                now=now,
                trigger=trigger,
            )
            return _result(
                "ERROR",
                _safe_text(exc.message or exc),
                errors=[safe_error("fetch", exc)],
            )
        except Exception as exc:  # noqa: BLE001 - one source must not kill the run/scheduler
            logger.exception("Source %s collection crashed", source.source_id)
            _finalize_run(
                db,
                source,
                status="ERROR",
                message=_safe_text(exc),
                errors=[safe_error("collect", exc)],
                run=run,
                now=now,
                trigger=trigger,
            )
            return _result(
                "ERROR", _safe_text(exc), errors=[safe_error("collect", exc)]
            )

        run.pages_visited = int(collected.pages_visited or 0)
        errors: List[Dict[str, str]] = list(collected.errors or [])

        # Opt-in composite identity for sources whose native identifier is not
        # row-unique (e.g. GePNIC "Reference No"). Absent -> unchanged behaviour.
        identity_fields = _source_identity_fields(source.config)

        # Source attribution: every record entering the pipeline knows exactly
        # which configured source it came from.
        for record in collected.records:
            record.source_name = record.source_name or source.name

        try:
            # --- Same-run de-duplication (a source repeating a row in one run) ---
            unique_records, duplicate_rows = _dedupe_run(
                collected.records, identity_fields
            )
            if duplicate_rows:
                errors.append(
                    safe_error(
                        "dedup",
                        f"{duplicate_rows} record(s) repeated inside the run and were counted once.",
                    )
                )

            if not unique_records:
                status = "NO_RECORDS" if not errors else "FAILED"
                _finalize_run(
                    db,
                    source,
                    status=status,
                    message=(
                        "The source was reachable but produced no record that could be mapped. "
                        + (
                            _safe_text(errors[0]["message"])
                            if errors
                            else "Nothing was persisted."
                        )
                    ),
                    errors=errors[:20],
                    run=run,
                    now=now,
                    trigger=trigger,
                )
                return _result(
                    status,
                    "Source produced no usable records; nothing persisted.",
                    errors=errors[:20],
                )

            # --- Existing validation layer -------------------------------------
            valid_records, invalid_records = validate_records(unique_records)
            for index, inv in enumerate(invalid_records):
                for err in inv.errors:
                    errors.append(safe_error(f"validation:row{index}", err.message))
            run.records_discovered = len(unique_records)
            run.validated = len(valid_records)
            run.rejected = len(invalid_records)
            db.flush()

            if preview:
                _finalize_run(
                    db,
                    source,
                    status="PREVIEW",
                    message=(
                        f"Fetched {len(collected.records)} record(s) ({len(valid_records)} valid, "
                        f"{len(invalid_records)} rejected). Nothing persisted (preview)."
                    ),
                    errors=errors[:20],
                    run=None,
                    now=now,
                    trigger=trigger,
                )
                return _result(
                    "PREVIEW",
                    f"Fetched {len(collected.records)} record(s); nothing persisted (preview).",
                    validated=len(valid_records),
                    rejected=len(invalid_records),
                    errors=errors[:20],
                )

            # --- Existing normalize + dedup + persistence -----------------------
            inserted: List[Bid] = []
            updated: List[Bid] = []
            duplicates = 0
            seen_keys: Set[str] = set()
            for val_rec in valid_records:
                if val_rec.raw.source_url:
                    key = f"url:{val_rec.raw.source_url.strip().lower()}"
                    if key in seen_keys:
                        duplicates += 1
                        continue
                    # guard against dupes within the valid list that share a URL
                normalized = normalize_record(
                    val_rec.raw, identity_fields=identity_fields
                )
                if normalized.get("source_url"):
                    seen_keys.add(
                        f"url:{str(normalized['source_url']).strip().lower()}"
                    )

                dup = check_duplicate(
                    db,
                    normalized,
                    use_bid_number_identity=not identity_fields,
                )
                if dup.is_duplicate:
                    duplicates += 1
                    if allow_update_duplicates and dup.existing_bid:
                        bid = dup.existing_bid
                        if (
                            normalized.get("hash")
                            and normalized["hash"] != bid.content_hash
                        ):
                            _apply_update(bid, normalized)
                            db.flush()
                            updated.append(bid)
                        elif not normalized.get("hash"):
                            _apply_update(bid, normalized)
                            db.flush()
                            updated.append(bid)
                    continue

                bid_data = dict(normalized)
                bid_data["content_hash"] = bid_data.pop("hash", None)
                bid_data["status"] = "NEW"
                valid_bid_keys = {c.name for c in Bid.__table__.columns}
                new_bid = Bid(
                    **{k: v for k, v in bid_data.items() if k in valid_bid_keys}
                )
                db.add(new_bid)
                db.flush()
                inserted.append(new_bid)

            run.inserted = len(inserted)
            run.updated = len(updated)
            run.duplicates = duplicates

            if duplicates:
                errors.append(
                    safe_error(
                        "dedup",
                        f"{duplicates} record(s) already known in the database.",
                    )
                )

            # --- Existing matching / analysis / notifications --------------------
            notifications = 0
            if not preview:
                llm = DeterministicLLMProvider()
                opp = OpportunityAnalyzer()
                for bid in inserted + updated:
                    try:
                        intel = process_bid_intelligence(
                            db=db,
                            bid=bid,
                            llm_provider=llm,
                            opp_analyzer=opp,
                            auto_notify=auto_notify,
                            commit=False,
                        )
                        if intel.get("notification_created"):
                            notifications += 1
                    except Exception as exc:  # noqa: BLE001 - intelligence failure must not abort the run
                        logger.warning(
                            "intelligence processing failed for bid %s: %s", bid.id, exc
                        )
                        errors.append(
                            safe_error("intelligence", f"bid {bid.id}: {exc}")
                        )
                run.notes = f"intelligence_processed={len(inserted) + len(updated)};notifications_created={notifications}"

            status = "SUCCESS"
            if invalid_records and valid_records:
                status = "PARTIAL"
            elif (len(invalid_records) == len(unique_records)) and unique_records:
                status = "FAILED"
            elif not valid_records:
                status = "NO_RECORDS"
            if errors and status == "SUCCESS":
                status = "NEEDS_ATTENTION"

            _finalize_run(
                db,
                source,
                status=status,
                message=_build_message(status, run, errors),
                errors=errors[:20],
                run=run,
                now=now,
                trigger=trigger,
            )
            return _result(
                status, _build_message(status, run, errors), errors=errors[:20]
            )
        except Exception as exc:  # noqa: BLE001 - a pipeline crash must not wedge the source or lose the audit trail
            return _record_crashed_run(
                db,
                source,
                run,
                collected,
                errors,
                exc,
                now=now,
                trigger=trigger,
                preview=preview,
            )
    finally:
        lock.release()


def _mark_run(
    db: Session,
    source: DataSource,
    status: str,
    message: str,
    *,
    now: datetime,
    trigger: str,
) -> None:
    db.add(
        SourceRun(
            id=uuid.uuid4(),
            source_id=source.id,
            trigger=trigger,
            started_at=now,
            finished_at=now,
            status=status,
            notes=message[:500],
        )
    )
    source.status = status
    source.last_attempt_at = now
    if status == "BLOCKED":
        source.last_error = message[:500]
    db.commit()


def _record_crashed_run(
    db: Session,
    source: DataSource,
    run: SourceRun,
    collected,
    errors: List[Dict[str, str]],
    exc: Exception,
    *,
    now: datetime,
    trigger: str,
    preview: bool = False,
) -> Dict[str, Any]:
    """Roll back a crashed mid-pipeline run and persist a safe ERROR audit row.

    An unexpected exception between collection success and the final commit must
    never leave the source stuck ``RUNNING`` or hide the run. The counters are
    captured *before* the rollback (they are client-side defaults, never lazy
    loads), everything uncommitted is discarded (so no half-inserted bids), and
    a fresh ``SourceRun`` reusing the original id is committed as ``ERROR``.
    """
    snapshot = {
        "run_id": run.id,
        "started_at": run.started_at if run.started_at is not None else now,
        "pages_visited": int(run.pages_visited or 0),
        "discovered": int(run.records_discovered or 0),
        "validated": int(run.validated or 0),
        "rejected": int(run.rejected or 0),
        "inserted": int(run.inserted or 0),
        "updated": int(run.updated or 0),
        "duplicates": int(run.duplicates or 0),
    }
    collected_errors = list(errors or [])
    message = _safe_text(exc, 500)
    logger.exception("Source %s pipeline crashed mid-run", source.source_id)
    db.rollback()

    crash_errors: List[Dict[str, str]] = (
        collected_errors + [safe_error("pipeline", exc)]
    )[:20]
    crash_run = SourceRun(
        id=snapshot["run_id"],
        source_id=source.id,
        trigger=trigger,
        started_at=snapshot["started_at"],
        finished_at=now,
        status="ERROR",
        pages_visited=snapshot["pages_visited"],
        records_discovered=snapshot["discovered"],
        validated=snapshot["validated"],
        rejected=snapshot["rejected"],
        inserted=snapshot["inserted"],
        updated=snapshot["updated"],
        duplicates=snapshot["duplicates"],
        errors=crash_errors,
        notes=message[:500],
    )
    db.add(crash_run)
    db.flush()

    source.status = "ERROR"
    source.last_attempt_at = now
    source.last_success_at = None
    source.last_error = (crash_errors[0]["message"] if crash_errors else message)[:500]
    source.last_discovered = snapshot["discovered"]
    source.last_validated = snapshot["validated"]
    source.last_rejected = snapshot["rejected"]
    source.last_inserted = snapshot["inserted"]
    source.last_updated = snapshot["updated"]
    source.last_duplicates = snapshot["duplicates"]
    source.total_runs += 1
    db.commit()

    return {
        "run_id": str(snapshot["run_id"]),
        "source_id": source.source_id,
        "source_name": source.name,
        "source_type": source.source_type,
        "adapter_key": source.adapter_key,
        "status": "ERROR",
        "trigger": trigger,
        "preview": preview,
        "message": message,
        "pages_visited": snapshot["pages_visited"],
        "discovered": snapshot["discovered"],
        "validated": snapshot["validated"],
        "rejected": snapshot["rejected"],
        "inserted": snapshot["inserted"],
        "updated": snapshot["updated"],
        "duplicates": snapshot["duplicates"],
        "errors": crash_errors,
        "duration_seconds": 0.0,
    }


def _finalize_run(
    db: Session,
    source: DataSource,
    *,
    status: str,
    message: str,
    errors: List[Dict[str, str]],
    now: datetime,
    trigger: str,
    run: Optional[SourceRun] = None,
) -> None:
    if run is not None:
        run.status = status if status != "PREVIEW" else "SUCCESS"
        run.finished_at = now
        run.errors = errors[:20]
        if not run.notes:
            run.notes = message[:500]
    # Refresh the source row's live state.
    source.status = "SUCCESS" if status == "PREVIEW" else status
    source.last_attempt_at = now
    if status in ("SUCCESS", "PARTIAL", "NEEDS_ATTENTION", "NO_RECORDS", "PREVIEW"):
        source.last_success_at = now
        source.last_error = None
    else:
        source.last_error = (errors[0]["message"] if errors else message)[:500]
    if run is not None:
        source.last_discovered = run.records_discovered
        source.last_validated = run.validated
        source.last_rejected = run.rejected
        source.last_inserted = run.inserted
        source.last_updated = run.updated
        source.last_duplicates = run.duplicates
        source.total_runs += 1
        source.total_inserted += run.inserted
        source.total_updated += run.updated
        source.total_duplicates += run.duplicates
        source.total_rejected += run.rejected
    db.commit()


def _adapter_for(source: DataSource):
    from app.services.sources.adapters import get_adapter

    adapter = get_adapter(source.adapter_key)
    if adapter is None:
        raise SourceConfigError(
            f"No adapter registered for key '{source.adapter_key}'.",
            safe_message=f'No adapter is registered for "{source.adapter_key}".',
        )
    return adapter


def _source_identity_fields(config: Optional[Dict[str, Any]]) -> Optional[List[str]]:
    """Return the source's opt-in composite identity fields, or ``None``.

    Absent/blank means the source keeps the default (native identifier)
    behaviour, so non-GePNIC sources are completely unaffected.
    """
    fields = (config or {}).get("identity_fields")
    if not isinstance(fields, list):
        return None
    cleaned = [str(f).strip() for f in fields if str(f or "").strip()]
    return cleaned or None


def _dedupe_run(
    records: List[RawBidRecord],
    identity_fields: Optional[List[str]] = None,
):
    unique: List[RawBidRecord] = []
    seen: Set[str] = set()
    dupes = 0
    for record in records:
        key = ""
        if identity_fields:
            values = {
                name: getattr(record, name, None) for name in RawBidRecord.model_fields
            }
            key = "cid:" + derive_composite_identity(identity_fields, values)
        elif record.gem_bid_id or record.bid_number:
            key = f"id:{(record.gem_bid_id or record.bid_number or '').strip().upper()}"
        elif record.title:
            key = f"title:{record.title.strip().casefold()}"
        elif record.source_url:
            key = f"url:{record.source_url.strip().lower()}"
        if key and key in seen:
            dupes += 1
            continue
        if key:
            seen.add(key)
        unique.append(record)
    return unique, dupes


def _apply_update(bid: Bid, normalized: Dict[str, Any]) -> None:
    for key, value in normalized.items():
        column = "content_hash" if key == "hash" else key
        if (
            column not in ("id", "created_at")
            and hasattr(bid, column)
            and value is not None
        ):
            setattr(bid, column, value)
    bid.last_updated_at = datetime.now(timezone.utc)


def _build_message(status: str, run: SourceRun, errors: List[Dict[str, str]]) -> str:
    base = (
        f"Collected {run.records_discovered} record(s): {run.inserted} inserted, "
        f"{run.updated} updated, {run.duplicates} duplicates, {run.rejected} rejected."
    )
    if errors:
        base += f" {len(errors)} issue(s) recorded."
    return base
