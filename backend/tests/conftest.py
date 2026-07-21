"""Test environment defaults.

Force a hermetic, auth-free SQLite setup *before* the app imports its settings,
so `pytest` works out of the box regardless of a local `.env` (which may enable
Clerk auth or point at Postgres). `setdefault` means an explicit inline env var
still wins, and CI — which has no `.env` — is unaffected.
"""

from __future__ import annotations

import os

os.environ.setdefault("ELIGO_AUTH_ENABLED", "false")  # noqa: E402 — must precede app import
os.environ.setdefault("ELIGO_DATABASE_URL", "sqlite+aiosqlite:///./ci_test.db")
# Pin the ADMIN url too (create_all/DDL runs on it). Otherwise it is read from a
# local `.env` and DDL lands on the real Postgres while the runtime engine is
# this hermetic SQLite — so DB-backed tests would see "no such table".
os.environ.setdefault("ELIGO_ADMIN_DATABASE_URL", os.environ["ELIGO_DATABASE_URL"])
os.environ.setdefault("ELIGO_LLM_PROVIDER", "heuristic")
os.environ.setdefault("ELIGO_DB_SSL", "false")

import pytest  # noqa: E402 — after the env is pinned, before fixtures use the app


@pytest.fixture(autouse=True)
async def _fresh_db():
    """Give every test an empty schema.

    With auth disabled every request resolves to the single default tenant, so
    rows created by one test are visible to the next; the SQLite file also
    persists across the session. Drop + recreate before each test so counts
    (e.g. "matching returns exactly one candidate") are deterministic.
    """
    from app.core.database import Base, admin_engine
    from app.domain import registry  # noqa: F401 — registers every table on Base

    async with admin_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
