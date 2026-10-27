import sys
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import Base, get_db
from app.main import app
from app.seed import seed_products

from sqlalchemy.pool import StaticPool

# Use in-memory SQLite for tests
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    def _override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def no_live_gem_requests(monkeypatch):
    """
    Fail fast if a test reaches a real GeM network or browser boundary.

    The direct collector fetches the public listing over HTTP and walks its pages
    in a rendered browser. A test that forgets to fake one of those boundaries
    would otherwise start a real Chromium session and hang the whole suite.

    The HTTP guard is installed on ``requests.Session.request`` rather than on the
    collector, so tests that inject their own session object keep working while
    any real socket call fails immediately with an explanation.
    """
    import requests

    from app.core.config import settings
    from app.services.ingestion import gem_direct_service as gem_service
    from app.services.ingestion import gem_public_collector as gem_collector

    # Automatic BoQ enrichment makes per-bid network calls during collection.
    # Force it off so no test depends on the ambient .env value and no test can
    # reach the network through it. Tests that exercise it enable it explicitly
    # and inject a fake session (see tests/test_gem_boq_auto.py).
    monkeypatch.setattr(settings, "GEM_BOQ_AUTO_ENRICH_ENABLED", False)

    def _no_browser(*args, **kwargs):
        raise AssertionError(
            "A test tried to open a real rendered GeM listing. Patch "
            "gem_direct_service.open_listing_session with a fake session "
            "(see tests/gem_pagination_fixtures.py)."
        )

    def _no_session(*args, **kwargs):
        raise AssertionError(
            "A test tried to start Playwright. Patch "
            "gem_public_collector.open_listing_session explicitly."
        )

    def _no_live_request(self, *args, **kwargs):
        raise AssertionError(
            "A test made a real HTTP request. Inject a fake session (see "
            "tests/test_gem_direct_collector.py::make_session) or patch "
            "gem_direct_service._shared_collector."
        )

    monkeypatch.setattr(gem_service, "open_listing_session", _no_browser)
    monkeypatch.setattr(gem_collector, "open_listing_session", _no_session)
    monkeypatch.setattr(requests.Session, "request", _no_live_request)
