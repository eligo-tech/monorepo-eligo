# eligo-tech backend — production image (Railway, Fly, Render, any Docker host).
FROM python:3.12-slim

WORKDIR /app

# git is required to install the laufwise dependency (a git URL).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Install deps first for better layer caching.
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir ".[postgres,llm]"

# Managed Postgres (Supabase) needs TLS. Override the rest via platform env vars:
#   ELIGO_DATABASE_URL, ELIGO_DB_SSL_VERIFY, OPENAI_API_KEY, ELIGO_CORS_ORIGINS
ENV ELIGO_DB_SSL=true \
    ELIGO_ENV=production \
    ELIGO_DEBUG=false

EXPOSE 8000
# Railway/Render inject $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
