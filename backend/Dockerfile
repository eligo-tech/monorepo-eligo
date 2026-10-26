# Eligo Labs backend — production image (Railway, Fly, Render, any Docker host).
FROM python:3.12-slim

WORKDIR /app

# git is required to install the laufwise dependency (a git URL).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Dependencies come from the LOCK, not from the floors in pyproject.
#
# `pip install ".[postgres,llm]"` re-resolved on every build, so two deploys of
# identical application code could ship different libraries — and did: on
# 2026-10-26 the laufwise pin was a bare branch URL and three environments held
# three different commits of it. A green CI run says nothing about a later
# build unless both install the same thing.
#
# Regenerate BOTH locks with (uv 0.10.7, the version CI pins):
#   uv pip compile pyproject.toml --extra postgres --extra llm --extra monitoring \
#       --python-version 3.12 --no-header -o requirements.lock
#   uv pip compile pyproject.toml --extra postgres --extra llm --extra monitoring \
#       --extra dev --python-version 3.12 --no-header -o requirements-dev.lock
#
# `--no-header` is not cosmetic: uv writes the --output-file path into the
# header, so a lock compiled to a temporary file never compares equal to the
# committed one. The CI "Dependency locks" job fails if either is stale.
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

# The app itself, with --no-deps: everything it needs is already installed
# above, and without the flag pip would resolve the floors all over again.
COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir --no-deps .

# Managed Postgres (Supabase) needs TLS. Override the rest via platform env vars:
#   ELIGO_DATABASE_URL, ELIGO_DB_SSL_VERIFY, OPENAI_API_KEY, ELIGO_CORS_ORIGINS
ENV ELIGO_DB_SSL=true \
    ELIGO_ENV=production \
    ELIGO_DEBUG=false

EXPOSE 8000
# Apply DB migrations, then start. Railway/Render inject $PORT.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
