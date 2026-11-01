"""Portable column types.

Two families, because production has both and the models must say which:

* ``JSONDict`` / ``JSONList`` — SQLAlchemy's generic ``JSON``: **``json`` on
  Postgres** (text, kept verbatim), serialized ``TEXT`` on SQLite. This is
  what ``create_all`` made, so the older tables are ``json`` in production —
  including ``receipts.payload``, which stays ``json``: ``jsonb`` reorders
  keys, and the receipt ledger is hash-chained.
* ``JSONBDict`` / ``JSONBList`` — **``jsonb`` on Postgres**, ``TEXT`` on
  SQLite. What the migrations create (0007, 0008, 0021, 0043, 0044 …). Use
  these for a new column whose migration makes ``jsonb``.

Until 2026-11-01 this module claimed ``JSON`` "maps to native JSONB on
Postgres". It does not, and a database built by ``create_all`` silently
differed from one built by migrations. ``scripts/schema_drift.py`` now fails
CI on any such difference.

Embeddings note: on Postgres the ``pgvector`` extension provides a real
``Vector`` column for similarity search. The scaffold stores embeddings as a
JSON list (``JSONList``) so it runs on SQLite; swap to ``pgvector.sqlalchemy.
Vector`` in the Postgres profile.
"""

from __future__ import annotations

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

# Aliases documenting intent at the call site.
JSONDict = JSON
JSONList = JSON

JSONBDict = JSON().with_variant(JSONB(), "postgresql")
JSONBList = JSONBDict
