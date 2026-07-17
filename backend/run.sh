#!/usr/bin/env bash
# Foolproof backend launcher — always uses the project venv, never system Python.
# (The "No module named 'sqlalchemy'" error happens when `uvicorn` is run from the
# system install instead of ./.venv, where the dependencies actually live.)
set -euo pipefail
cd "$(dirname "$0")"

PY=python3

if [ ! -d .venv ]; then
  echo "▸ Creating virtualenv (.venv)…"
  "$PY" -m venv .venv
fi

echo "▸ Installing dependencies…"
./.venv/bin/pip install -q -e ".[dev]"

if [ ! -f eligo.db ]; then
  echo "▸ Seeding demo data…"
  ./.venv/bin/python -m app.seed
fi

echo "▸ Starting API on http://localhost:8000  (docs: /docs)"
exec ./.venv/bin/uvicorn app.main:app --reload --port 8000 "$@"