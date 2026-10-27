from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.database import engine, Base
from app.api.v1.router import api_router
from app.services.ingestion import gem_scheduler
from app.services.sources import scheduler as source_scheduler

# Setup application logging
setup_logging()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Automatic GeM collection: one background thread that runs the existing
    # direct collector once per configured interval when enabled. Disabled by
    # configuration means collections stay manual and no thread is started.
    gem_scheduler.start()
    # Configurable multi-source collection (RSS / JSON API / HTML listing).
    # Off by default (SOURCE_SCHEDULER_ENABLED=false); never runs during
    # development or automated testing unless an operator enables it.
    source_scheduler.start()
    try:
        yield
    finally:
        source_scheduler.stop()
        gem_scheduler.stop()


# Explicit aliases so the scheduler lifecycle is visible on the app module.
start_gem_scheduler = gem_scheduler.start
stop_gem_scheduler = gem_scheduler.stop
start_source_scheduler = source_scheduler.start
stop_source_scheduler = source_scheduler.stop

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Compress large responses (the bid intelligence feed is tens of megabytes of
# JSON). Content-Encoding is negotiated via Accept-Encoding, so every existing
# client keeps working and API compatibility is unchanged.
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Configure CORS
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Include API v1 router
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
def root():
    return {
        "message": "Welcome to SecuredApp GeM Bid Intelligence Platform API",
        "docs": "/docs",
        "version": "0.1.0"
    }
