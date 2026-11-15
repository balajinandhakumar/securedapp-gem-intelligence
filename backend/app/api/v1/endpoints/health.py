from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.config import settings
from app.core.database import get_db
from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def get_health(db: Session = Depends(get_db)):
    db_connected = False
    try:
        db.execute(text("SELECT 1"))
        db_connected = True
    except Exception:
        db_connected = False

    return HealthResponse(
        status="ok" if db_connected else "degraded",
        project_name=settings.PROJECT_NAME,
        environment=settings.ENVIRONMENT,
        database_connected=db_connected
    )


@router.get("/ready", response_model=ReadinessResponse)
def get_readiness(db: Session = Depends(get_db)):
    """Readiness probe: checks database connectivity and returns per-check status.

    Returns 200 when all checks pass, 503 when any check fails.
    """
    checks = {}
    overall = "ok"

    # Database check
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "failed"
        overall = "degraded"

    if overall == "degraded":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ReadinessResponse(status=overall, checks=checks),
        )

    return ReadinessResponse(status=overall, checks=checks)
