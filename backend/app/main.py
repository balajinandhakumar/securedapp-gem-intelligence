from contextlib import asynccontextmanager
import time
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.database import engine, Base
from app.api.v1.router import api_router
from app.seed import seed_products
from app.services.ingestion import gem_scheduler
from app.services.sources import scheduler as source_scheduler
import uuid
import os
import threading

# Setup application logging
setup_logging()

# ---------------------------------------------------------------------------
# Simple in-memory sliding-window rate limiter (Task E).
#
# Tracks request timestamps per client IP. Not distributed (single-process),
# which is acceptable for a single-backend deployment. For multi-instance
# deployments, replace with Redis-backed rate limiting.
# ---------------------------------------------------------------------------
_rate_limit_lock = threading.Lock()
_rate_limit_clients: dict[str, list[float]] = {}


def _rate_limit_check(client_ip: str) -> bool:
    """Return True when the request is allowed, False when rate-limited."""
    if not settings.RATE_LIMIT_ENABLED or settings.ENVIRONMENT != "production":
        return True
    now = time.time()
    window = 60.0  # 1-minute sliding window
    with _rate_limit_lock:
        timestamps = _rate_limit_clients.get(client_ip, [])
        # Keep only timestamps within the window
        timestamps = [t for t in timestamps if now - t < window]
        if len(timestamps) >= settings.RATE_LIMIT_REQUESTS_PER_MINUTE:
            _rate_limit_clients[client_ip] = timestamps
            return False
        timestamps.append(now)
        _rate_limit_clients[client_ip] = timestamps
        return True


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Reliable product-catalogue seed on every startup. Guarantees the 11
    # official SecuredApp products (and their knowledge vectors) exist in the
    # database so the catalogue and the bid-to-product matching engine work
    # immediately after a restart. Idempotent: never creates duplicates and
    # never overwrites administrator edits made through the Product API.
    seed_products()
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

# Trusted host restriction: only accept requests for the configured hosts.
# In production this must be set to the actual domain(s) to prevent
# host-header attacks. Defaults to allowing all hosts in development
# (AUTH_REQUIRED=False). The CORS origins list contains full URLs (e.g.
# "http://localhost:3000") which are not valid TrustedHost hostnames, so we
# do not derive trusted hosts from it.
if settings.ENVIRONMENT == "production" and settings.AUTH_REQUIRED:
    # Production: require explicit trusted hosts. Operators must configure
    # TRUSTED_HOSTS (comma-separated hostnames) via environment.
    _trusted_hosts = [
        h.strip() for h in os.environ.get("TRUSTED_HOSTS", "*").split(",") if h.strip()
    ]
else:
    _trusted_hosts = ["*"]
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=_trusted_hosts,
)


# Request-ID middleware for observability. Every request gets a unique
# X-Request-ID header (echoed back on the response) so logs and traces can
# be correlated across services.
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id

    # Rate limiting (skip auth endpoints which have their own brute-force
    # protection, and health checks which should always be reachable).
    path = request.url.path
    if not path.startswith("/api/v1/auth/") and not path.startswith("/api/v1/health"):
        if not _rate_limit_check(_client_ip(request)):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Try again later.",
                headers={"Retry-After": "60"},
            )

    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    # Secure response headers (Task E).
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    # Do not advertise the server framework in production responses.
    # Starlette's MutableHeaders has no .pop() method (DEF-002); use __delitem__
    # instead. Note: uvicorn re-adds a "server" header at the socket level
    # after the ASGI app returns, so full removal requires an edge reverse
    # proxy (e.g. nginx). The application-level header is suppressed here.
    if settings.ENVIRONMENT == "production":
        try:
            del response.headers["server"]
        except KeyError:
            pass
    return response


@app.get("/")
def root():
    return {
        "message": "Welcome to SecuredApp GeM Bid Intelligence Platform API",
        "docs": "/docs",
        "version": "0.1.0"
    }
