"""
API endpoints for bid ingestion runs, the data-source status, and file upload imports.
"""
from typing import Any, Dict, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.api.v1.dependencies import require_admin, require_operator, require_viewer
from app.models.collection import CollectionRun, RawBidPayload
from app.models.user import User
from app.services.ingestion.gem_direct_service import gem_direct_status_payload
from app.services.ingestion.pipeline import run_ingestion_pipeline
from app.services.ingestion.schemas import ImportResult

router = APIRouter()


class DataSourceStatusResponse(BaseModel):
    """
    Status of the active GeM data source: the Direct GeM Public Collector.

    This is public GeM web pages. It is not a GeM API and must never be
    labelled as one.
    """

    provider_name: str
    provider_label: str = "Direct GeM Public Collector"
    source_label: str = "Direct GeM Public Collector - public GeM web pages"
    base_url: str
    configured: bool
    status: str  # NOT_CONFIGURED, READY, SYNCING, SUCCESS, ERROR
    is_syncing: bool
    last_sync: Dict[str, Any]


def _data_source_status() -> Dict[str, Any]:
    """
    Build the secret-free status of the active data source.

    The live source is the Direct GeM Public Collector, which reads GeM's own
    public listing pages. No credential is involved and none is exposed.
    """
    direct = gem_direct_status_payload()
    configured = bool(direct.get("configured"))
    syncing = bool(direct.get("is_running"))
    last_run = direct.get("last_run") or {}
    last_status = last_run.get("status")

    if not configured:
        current_status = "NOT_CONFIGURED"
    elif syncing:
        current_status = "SYNCING"
    elif last_status in ("ERROR", "FAILED"):
        current_status = "ERROR"
    elif last_status == "SUCCESS":
        current_status = "SUCCESS"
    else:
        current_status = "READY"

    return {
        "provider_name": "gem_direct_public",
        "provider_label": "Direct GeM Public Collector",
        "source_label": "Direct GeM Public Collector - public GeM web pages",
        "base_url": direct.get("listing_url") or settings.GEM_DIRECT_LISTING_URL,
        "configured": configured,
        "status": current_status,
        "is_syncing": syncing,
        "last_sync": {k: v for k, v in last_run.items() if k != "last_result"},
    }


@router.get("/provider/status", response_model=DataSourceStatusResponse, status_code=status.HTTP_200_OK)
def get_provider_status_endpoint(
    current_user: Optional[User] = Depends(require_viewer),
):
    """
    Returns the current configuration and operational status of the active data
    source, the Direct GeM Public Collector.
    Distinguishes: NOT_CONFIGURED, READY, SYNCING, SUCCESS, ERROR.
    """
    return _data_source_status()


@router.post("/import", response_model=ImportResult, status_code=status.HTTP_200_OK)
async def import_bids_file(
    file: UploadFile = File(...),
    file_format: Optional[str] = Form(None),
    allow_update: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_operator),
):
    """
    Ingest bids from an uploaded CSV, XLSX, or JSON file.
    Format is automatically inferred from file extension if file_format is omitted.
    """
    filename = file.filename or "unknown_file"
    if not file_format:
        ext = filename.split(".")[-1].lower()
        if ext in ("csv", "json", "xlsx"):
            file_format = ext
        else:
            file_format = "csv"  # default fallback

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    try:
        result = run_ingestion_pipeline(
            db=db,
            file_content=file_bytes,
            file_type=file_format,
            source_name=filename,
            allow_update_duplicates=allow_update,
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to process ingestion file: {str(e)}",
        )


@router.get("/runs", status_code=status.HTTP_200_OK)
def list_ingestion_runs(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_viewer),
):
    """List collection/ingestion audit runs."""
    limit = min(limit, 1000)
    runs = db.query(CollectionRun).order_by(CollectionRun.started_at.desc()).offset(skip).limit(limit).all()
    return runs


@router.get("/runs/{run_id}", status_code=status.HTTP_200_OK)
def get_ingestion_run(
    run_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_viewer),
):
    """Get detailed information for a specific ingestion run."""
    run = db.query(CollectionRun).filter(CollectionRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion run not found")
    payloads = db.query(RawBidPayload).filter(RawBidPayload.collection_run_id == run_id).limit(100).all()
    return {
        "run": run,
        "sample_raw_payloads": payloads,
    }