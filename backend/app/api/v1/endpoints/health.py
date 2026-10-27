from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.config import settings
from app.core.database import get_db
from app.schemas.health import HealthResponse

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
