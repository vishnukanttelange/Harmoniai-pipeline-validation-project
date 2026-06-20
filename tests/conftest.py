"""
Shared pytest fixtures.

Design goals (per the assignment's "pass reliably... regardless of order"
requirement):
  - Each test gets a clean `jobs` table (TRUNCATE before every test function),
    so no test can depend on rows left behind by another.
  - The FastAPI app + background worker pool are started once per test
    session (cheap to share - they're stateless aside from the DB).
  - Tests talk to the app in-process via Starlette's TestClient rather than
    a separately-launched uvicorn process. This avoids host/port flakiness
    in CI and still exercises the real ASGI app, real Postgres, and real
    background worker threads.
"""

import os
import sys

import pytest
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/pipeline_test",
)

from mock_service.db import init_db, SessionLocal, engine  # noqa: E402
from mock_service.app import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_database():
    init_db()
    yield


@pytest.fixture(autouse=True)
def _clean_jobs_table():
    """Runs before every test: guarantees no cross-test state leakage."""
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE jobs"))
    yield


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
