"""Top-level API router mounted at ``/api/v1``.

Aggregates every domain router plus the health probe. New domains are wired in
here (see backend/CLAUDE.md, "adding a new domain").
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import Actor, get_current_actor

from app.domain.candidates.router import router as candidates_router
from app.domain.companies.router import router as companies_router
from app.domain.documents.router import router as documents_router
from app.domain.imports.router import router as imports_router
from app.domain.tenantsources.router import router as tenantsources_router
from app.domain.hub.router import router as hub_router
from app.domain.jobs.router import router as jobs_router
from app.domain.managers.router import router as managers_router
from app.domain.matching.router import router as matching_router
from app.domain.pipeline.router import router as pipeline_router
from app.domain.projects.router import router as projects_router
from app.domain.reporting.router import router as reporting_router
from app.domain.searches.router import router as searches_router
from app.domain.verification.router import router as verification_router

api_router = APIRouter()


@api_router.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Liveness probe. Runs with SQLite and no external services."""
    return {"status": "ok"}


@api_router.get("/me", tags=["system"])
async def me(actor: Actor = Depends(get_current_actor)) -> dict:
    """Who the server thinks you are, and what you may do.

    The UI needs this to show the role and to explain a closed panel instead
    of rendering a form that will be refused. It is NOT the authorization —
    every admin-only endpoint checks the same token itself, so hiding a
    button is a courtesy, never the control.
    """
    return {
        "tenant_id": str(actor.tenant_id),
        "user_id": actor.user_id,
        "name": actor.name,
        "role": actor.role,
        "role_known": actor.role_known,
    }


api_router.include_router(candidates_router)
api_router.include_router(companies_router)
api_router.include_router(documents_router)
api_router.include_router(imports_router)
api_router.include_router(tenantsources_router)
api_router.include_router(jobs_router)
api_router.include_router(hub_router)
api_router.include_router(pipeline_router)
api_router.include_router(projects_router)
api_router.include_router(managers_router)
api_router.include_router(matching_router)
api_router.include_router(reporting_router)
api_router.include_router(searches_router)
api_router.include_router(verification_router)