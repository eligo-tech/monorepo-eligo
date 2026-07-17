"""Top-level API router mounted at ``/api/v1``.

Aggregates every domain router plus the health probe. New domains are wired in
here (see backend/CLAUDE.md, "adding a new domain").
"""

from __future__ import annotations

from fastapi import APIRouter

from app.domain.candidates.router import router as candidates_router
from app.domain.companies.router import router as companies_router
from app.domain.jobs.router import router as jobs_router
from app.domain.matching.router import router as matching_router
from app.domain.pipeline.router import router as pipeline_router
from app.domain.verification.router import router as verification_router

api_router = APIRouter()


@api_router.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Liveness probe. Runs with SQLite and no external services."""
    return {"status": "ok"}


api_router.include_router(candidates_router)
api_router.include_router(companies_router)
api_router.include_router(jobs_router)
api_router.include_router(pipeline_router)
api_router.include_router(matching_router)
api_router.include_router(verification_router)