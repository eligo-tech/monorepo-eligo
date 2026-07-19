"""Test environment defaults.

Force a hermetic, auth-free SQLite setup *before* the app imports its settings,
so `pytest` works out of the box regardless of a local `.env` (which may enable
Clerk auth or point at Postgres). `setdefault` means an explicit inline env var
still wins, and CI — which has no `.env` — is unaffected.
"""

from __future__ import annotations

import os

os.environ.setdefault("ELIGO_AUTH_ENABLED", "false")
os.environ.setdefault("ELIGO_DATABASE_URL", "sqlite+aiosqlite:///./ci_test.db")
os.environ.setdefault("ELIGO_LLM_PROVIDER", "heuristic")
os.environ.setdefault("ELIGO_DB_SSL", "false")
