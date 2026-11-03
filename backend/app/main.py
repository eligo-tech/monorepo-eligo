"""FastAPI application entrypoint.

Run locally (zero external services, SQLite fallback):

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import api_router
from app.core.config import settings
from app.core.auth import assert_auth_configured
from app.core.body_limit import BodySizeLimit
from app.core.database import assert_runtime_rls_enforced, create_all
from app.core.logging import configure_logging, get_logger
from app.core.observability import configure_error_reporting
from app.domain.erasure import service as _erasure
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
    # MCP switched on with a config that would fail every login: refuse now.
    mcp_server.assert_mcp_configured()
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


# Erasure (GDPR Art. 17/21) answers the same way from every endpoint that can
# create a person, so it is mapped here once rather than in each router.


@app.exception_handler(_erasure.Suppressed)
async def _suppressed(_: Request, exc: _erasure.Suppressed) -> JSONResponse:
    # The date the person asked, never their address: the caller typed it, and
    # an error body ends up in logs and crash reports.
    return JSONResponse(
        status_code=409,
        content={"detail": {
            "code": "suppressed",
            "requested_on": exc.requested_on.isoformat(),
            "message": "Diese Person hat die Löschung ihrer Daten verlangt. Nur anlegen, "
                       "wenn sie sich seitdem selbst wieder gemeldet hat.",
        }},
    )


@app.exception_handler(_erasure.NotConfigured)
async def _erasure_not_configured(_: Request, __: _erasure.NotConfigured) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": {
            "code": "erasure_not_configured",
            "message": "Löschung ist auf diesem Server nicht eingerichtet "
                       "(ELIGO_SUPPRESSION_KEY fehlt).",
        }},
    )


@app.get("/", tags=["system"])
async def root() -> dict[str, str]:
    """Service banner."""
    return {
        "service": settings.app_name,
        "docs": "/docs",
        "health": f"{settings.api_v1_prefix}/health",
    }


# `/mcp` and `/.well-known/oauth-protected-resource/mcp` (ADR 0003), dispatched
# by exact path before anything else — see `MCPRoutes` for why not a mount.
app.add_middleware(mcp_server.MCPRoutes)

# Outermost: bounds every request body while it arrives, /mcp included
# (review 2026-10-31 #5 B). See app/core/body_limit.py.
app.add_middleware(BodySizeLimit)
