"""
Configurable multi-source registry API.

CRUD for configured sources, connection tests, manual sync, enable/disable and
run history. No credential value is ever stored, returned or logged: a source
references secrets only by environment-variable name and every response config
is sanitized before it leaves the backend.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.source import DataSource, SourceRun
from app.services.sources.adapters import (
    adapter_catalog,
    get_adapter,
    get_adapter_for_source_type,
)
from app.services.sources.base import SourceConfigError, sanitize_config
from app.services.sources.runner import run_source_sync
from app.services.sources.scheduler import next_run_at

router = APIRouter()


class SourceCreate(BaseModel):
    source_id: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    base_url: Optional[str] = None
    source_type: str
    adapter_key: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    collection_interval_minutes: int = Field(default=60, ge=5, le=10080)
    notes: Optional[str] = None


class SourceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    base_url: Optional[str] = None
    source_type: Optional[str] = None
    adapter_key: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None
    collection_interval_minutes: Optional[int] = Field(default=None, ge=5, le=10080)
    notes: Optional[str] = None


class RunOut(BaseModel):
    id: str
    trigger: str
    started_at: str
    finished_at: Optional[str] = None
    status: str
    pages_visited: int
    discovered: int
    validated: int
    rejected: int
    inserted: int
    updated: int
    duplicates: int
    errors: List[Dict[str, Any]] = Field(default_factory=list)
    notes: Optional[str] = None


class SourceOut(BaseModel):
    id: str
    source_id: str
    name: str
    base_url: Optional[str] = None
    source_type: str
    adapter_key: str
    adapter_label: str
    enabled: bool
    collection_interval_minutes: int
    config: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None
    status: str
    last_attempt_at: Optional[str] = None
    last_success_at: Optional[str] = None
    last_error: Optional[str] = None
    last_discovered: int
    last_validated: int
    last_rejected: int
    last_inserted: int
    last_updated: int
    last_duplicates: int
    total_runs: int
    total_inserted: int
    total_updated: int
    total_duplicates: int
    total_rejected: int
    has_credentials: bool = False
    next_run_at: Optional[str] = None


def _run_out(run: SourceRun) -> RunOut:
    return RunOut(
        id=str(run.id),
        trigger=run.trigger,
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        status=run.status,
        pages_visited=run.pages_visited or 0,
        discovered=run.records_discovered or 0,
        validated=run.validated or 0,
        rejected=run.rejected or 0,
        inserted=run.inserted or 0,
        updated=run.updated or 0,
        duplicates=run.duplicates or 0,
        errors=list(run.errors or []),
        notes=run.notes,
    )


def _source_out(source: DataSource) -> SourceOut:
    adapter = get_adapter(source.adapter_key)
    config = source.config or {}
    has_credentials = bool((config.get("auth") or {}).get("env_ref"))
    return SourceOut(
        id=str(source.id),
        source_id=source.source_id,
        name=source.name,
        base_url=source.base_url,
        source_type=source.source_type,
        adapter_key=source.adapter_key,
        adapter_label=adapter.adapter_label if adapter else "Unknown",
        enabled=source.enabled,
        collection_interval_minutes=source.collection_interval_minutes or 60,
        config=sanitize_config(config),
        notes=source.notes,
        status=source.status or "IDLE",
        last_attempt_at=source.last_attempt_at.isoformat()
        if source.last_attempt_at
        else None,
        last_success_at=source.last_success_at.isoformat()
        if source.last_success_at
        else None,
        last_error=source.last_error,
        last_discovered=source.last_discovered or 0,
        last_validated=source.last_validated or 0,
        last_rejected=source.last_rejected or 0,
        last_inserted=source.last_inserted or 0,
        last_updated=source.last_updated or 0,
        last_duplicates=source.last_duplicates or 0,
        total_runs=source.total_runs or 0,
        total_inserted=source.total_inserted or 0,
        total_updated=source.total_updated or 0,
        total_duplicates=source.total_duplicates or 0,
        total_rejected=source.total_rejected or 0,
        has_credentials=has_credentials,
        next_run_at=next_run_at(source),
    )


def _resolve_source(db: Session, source_id: str) -> DataSource:
    source = db.query(DataSource).filter(DataSource.source_id == source_id).first()
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source '{source_id}' not found.",
        )
    return source


def _validate_config_for(adapter_key: str, config: Dict[str, Any]) -> Dict[str, Any]:
    adapter = get_adapter(adapter_key)
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No adapter registered for key '{adapter_key}'.",
        )
    try:
        return adapter.validate_config(config or {})
    except SourceConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc.safe_message or exc),
        ) from exc


def _adapter_key_for(source_type: str, adapter_key: Optional[str]) -> str:
    if adapter_key and adapter_key.strip():
        key = adapter_key.strip()
        adapter = get_adapter(key)
        if adapter is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"No adapter registered for key '{key}'.",
            )
        if adapter.source_types and source_type not in adapter.source_types:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Adapter '{key}' does not support source type '{source_type}' "
                    f"(supports: {', '.join(adapter.source_types)})."
                ),
            )
        return key
    adapter = get_adapter_for_source_type(source_type)
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No adapter exists for source type '{source_type}'.",
        )
    return adapter.adapter_key


@router.get("/sources/meta")
def sources_meta():
    """Secret-free adapter catalog for the source-management UI."""
    from app.services.sources.scheduler import scheduler_status

    return {
        "adapters": adapter_catalog(),
        "scheduler": scheduler_status(),
    }


@router.get("/sources", response_model=List[SourceOut])
def list_sources(db: Session = Depends(get_db)):
    sources = db.query(DataSource).order_by(DataSource.name.asc()).all()
    return [_source_out(s) for s in sources]


@router.get("/sources/{source_id}", response_model=SourceOut)
def get_source(source_id: str, db: Session = Depends(get_db)):
    return _source_out(_resolve_source(db, source_id))


@router.post("/sources", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
def create_source(payload: SourceCreate, db: Session = Depends(get_db)):
    if db.query(DataSource).filter(DataSource.source_id == payload.source_id).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A source with id '{payload.source_id}' already exists.",
        )
    adapter_key = _adapter_key_for(payload.source_type, payload.adapter_key)
    config = _validate_config_for(adapter_key, payload.config)
    source = DataSource(
        source_id=payload.source_id.strip().lower(),
        name=payload.name.strip(),
        base_url=payload.base_url,
        source_type=payload.source_type,
        adapter_key=adapter_key,
        config=config,
        enabled=payload.enabled or True,
        collection_interval_minutes=payload.collection_interval_minutes,
        notes=payload.notes,
        status="IDLE",
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return _source_out(source)


@router.put("/sources/{source_id}", response_model=SourceOut)
def update_source(source_id: str, payload: SourceUpdate, db: Session = Depends(get_db)):
    source = _resolve_source(db, source_id)
    if payload.name is not None:
        source.name = payload.name.strip()
    if payload.base_url is not None:
        source.base_url = payload.base_url
    if payload.source_type is not None:
        source.source_type = payload.source_type
        source.adapter_key = _adapter_key_for(payload.source_type, payload.adapter_key)
    if payload.adapter_key and payload.adapter_key.strip():
        source.adapter_key = payload.adapter_key.strip()
    if payload.config is not None:
        source.config = _validate_config_for(source.adapter_key, payload.config)
    if payload.enabled is not None:
        source.enabled = payload.enabled
    if payload.collection_interval_minutes is not None:
        source.collection_interval_minutes = payload.collection_interval_minutes
    if payload.notes is not None:
        source.notes = payload.notes
    db.commit()
    db.refresh(source)
    return _source_out(source)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(source_id: str, db: Session = Depends(get_db)):
    source = _resolve_source(db, source_id)
    db.delete(source)
    db.commit()


@router.post("/sources/{source_id}/enable", response_model=SourceOut)
def enable_source(source_id: str, db: Session = Depends(get_db)):
    source = _resolve_source(db, source_id)
    source.enabled = True
    db.commit()
    db.refresh(source)
    return _source_out(source)


@router.post("/sources/{source_id}/disable", response_model=SourceOut)
def disable_source(source_id: str, db: Session = Depends(get_db)):
    source = _resolve_source(db, source_id)
    source.enabled = False
    db.commit()
    db.refresh(source)
    return _source_out(source)


@router.post("/sources/{source_id}/test")
def test_source(source_id: str, db: Session = Depends(get_db)):
    """Test connectivity to a configured source (no data ingested)."""
    source = _resolve_source(db, source_id)
    adapter = get_adapter(source.adapter_key)
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No adapter for '{source.adapter_key}'.",
        )
    config = source.config or {}
    try:
        result = adapter.test_connection(config)
    except SourceConfigError as exc:
        return {
            "ok": False,
            "message": str(exc.safe_message or exc),
            "details": {"needs_credentials": True},
        }
    return {"ok": result.ok, "message": result.message, "details": result.as_dict()}


@router.post("/sources/{source_id}/sync")
def sync_source(source_id: str, db: Session = Depends(get_db)):
    """Manually collect the source now through the existing pipeline."""
    source = _resolve_source(db, source_id)
    result = run_source_sync(db, source, trigger="manual")
    if result.get("status") == "BUSY":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=result.get("message")
        )
    if result.get("status") == "CONFIG_ERROR":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("message")
        )
    if result.get("status") == "SKIPPED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("message")
        )
    return result


@router.get("/sources/{source_id}/runs", response_model=List[RunOut])
def source_runs(source_id: str, limit: int = 30, db: Session = Depends(get_db)):
    source = _resolve_source(db, source_id)
    limit = max(1, min(200, limit))
    runs = (
        db.query(SourceRun)
        .filter(SourceRun.source_id == source.id)
        .order_by(SourceRun.started_at.desc())
        .limit(limit)
        .all()
    )
    return [_run_out(r) for r in runs]


@router.get("/sources/runs/{run_id}", response_model=RunOut)
def source_run_detail(run_id: str, db: Session = Depends(get_db)):
    run = db.get(SourceRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found."
        )
    return _run_out(run)
