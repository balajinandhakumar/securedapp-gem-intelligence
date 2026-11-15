import time
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import OperationalError
from app.core.config import settings
import sqlite3

# Configure engine options based on database dialect (e.g. SQLite requires check_same_thread=False)
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    # Shorter busy timeout so interactive operations (e.g. login) fail fast on
    # SQLite write-lock contention instead of blocking for a full minute.
    # Retries are handled by execute_with_retry at the call site.
    connect_args["timeout"] = 10

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

if settings.DATABASE_URL.startswith("sqlite"):
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=60000;")
        cursor.close()


# ---------------------------------------------------------------------------
# Retry helper for SQLite "database is locked" errors.
#
# SQLite allows only one writer at a time. When the scheduler or another
# request holds a write lock, concurrent writes fail with
# ``sqlite3.OperationalError: database is locked``. Instead of surfacing a
# 500 to the user, retry a bounded number of times with a short backoff.
# ---------------------------------------------------------------------------
def _is_sqlite_locked_error(exc: Exception) -> bool:
    if isinstance(exc, OperationalError):
        orig = getattr(exc, "orig", None)
        return isinstance(orig, sqlite3.OperationalError) and "database is locked" in str(orig)
    return isinstance(exc, sqlite3.OperationalError) and "database is locked" in str(exc)


def execute_with_retry(func, max_retries: int = 5, base_delay: float = 0.25):
    """Execute ``func`` with retries on SQLite database-locked errors.

    Each retry waits ``base_delay * 2**attempt`` seconds before trying again,
    giving the holding transaction time to commit or roll back.
    """
    last_exc = None
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as exc:
            last_exc = exc
            if not _is_sqlite_locked_error(exc):
                raise
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
    raise last_exc


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        # Always roll back on any error so the session is never left in a
        # broken (PendingRollbackError) state for the next request.
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        db.close()
