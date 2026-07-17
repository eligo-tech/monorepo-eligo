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
from app.core.database import create_all
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup (scaffold convenience; use Alembic in prod)."""
    configure_logging()
    if settings.auto_create_tables:
        await create_all()
        logger.info("tables ensured (%s)", settings.database_url)
    logger.info("%s started in %s mode", settings.app_name, settings.env)
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
