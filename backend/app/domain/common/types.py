"""Portable column types.

``JSONDict`` / ``JSONList`` use SQLAlchemy's generic ``JSON`` type, which maps
to native ``JSONB`` on Postgres and a serialized ``TEXT`` column on SQLite — so
the same models run on both backends.

Embeddings note: on Postgres the ``pgvector`` extension provides a real
``Vector`` column for similarity search. The scaffold stores embeddings as a
JSON list (``JSONList``) so it runs on SQLite; swap to ``pgvector.sqlalchemy.
Vector`` in the Postgres profile.
"""

from __future__ import annotations

from sqlalchemy import JSON

# Aliases documenting intent at the call site.
JSONDict = JSON
JSONList = JSON