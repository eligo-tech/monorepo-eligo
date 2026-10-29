"""FastAPI application entrypoint.

Run locally (zero external services, SQLite fallback):

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api_router
from app.core.config import settings
from app.core.auth import assert_auth_configured
from app.core.database import assert_runtime_rls_enforced, create_all
from app.core.logging import configure_logging, get_logger
from app.core.observability import configure_error_reporting
from app.mcp import server as mcp_server

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup (scaffold convenience; use Alembic in prod)."""
    configure_logging()
    # Before the first request, so a failure during startup is reported too.
    # No-op unless ELIGO_SENTRY_DSN is set; see `core/observability.py` for
    # what is stripped before any event leaves the process.
    configure_error_reporting()
    # Before anything is served: a Postgres database with auth off would hand
    # every anonymous caller the default tenant (see `assert_auth_configured`).
    assert_auth_configured()
    if settings.auto_create_tables:
        await create_all()
        logger.info("tables ensured (%s)", settings.safe_database_url)
    # Verify the runtime connection actually enforces RLS (fail-closed isolation).
    await assert_runtime_rls_enforced()
    logger.info("%s started in %s mode", settings.app_name, settings.env)
    # A mounted app's lifespan is not run by FastAPI; the MCP session manager
    # needs its task group, so it runs here, around the whole app.
    async with mcp_server.server.session_manager.run():
        yield


app = FastAPI(
    title=f"{settings.app_name} API",
    version="0.1.0",
    description=(
        "AI-native recruitment platform. Layered architecture with a "
        "verification gate: agents propose, verification commits, receipts are "
        "append-only."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # A browser cannot read a response header unless it is named here, and a
    # list that does not say how much of the set it is showing is a list that
    # silently lies — see `X-Total-Count` on /candidates.
    expose_headers=["X-Total-Count"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", tags=["system"])
async def root() -> dict[str, str]:
    """Service banner."""
    return {
        "service": settings.app_name,
        "docs": "/docs",
        "health": f"{settings.api_v1_prefix}/health",
    }


# `/mcp` and `/.well-known/oauth-protected-resource/mcp` (ADR 0003). Mounted at
# the root because the metadata path is fixed by RFC 9728, and LAST, so every
# FastAPI route above wins and the MCP app only sees what they do not match.
app.mount("/", mcp_server.asgi_app)
