"""Projects API — named sets of target companies belonging to one workspace."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_tenant
from app.core.database import get_db
from app.domain.projects import service
from app.domain.projects.schemas import (
    AddCompaniesRequest,
    ProjectCreate,
    ProjectDetail,
    ProjectRead,
    ProjectUpdate,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
async def list_projects(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectRead]:
    rows = await service.list_projects(db, tenant_id=tenant_id)
    return [ProjectRead.model_validate(r) for r in rows]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ProjectRead:
    try:
        project = await service.create_project(db, tenant_id=tenant_id, payload=payload)
    except service.DuplicateName as exc:
        # 409, not 400: the request is well-formed and the state is the objection.
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"a project named {exc} already exists"
        ) from exc
    return ProjectRead.model_validate(
        {
            "id": project.id,
            "name": project.name,
            "note": project.note,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }
    )


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(
    project_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ProjectDetail:
    detail = await service.project_detail(
        db, tenant_id=tenant_id, project_id=project_id
    )
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return ProjectDetail.model_validate(detail)


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ProjectRead:
    try:
        project = await service.update_project(
            db, tenant_id=tenant_id, project_id=project_id, payload=payload
        )
    except service.DuplicateName as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"a project named {exc} already exists"
        ) from exc
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return ProjectRead.model_validate(
        {
            "id": project.id,
            "name": project.name,
            "note": project.note,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Drop the grouping only. The corpus companies and this workspace's
    contacts are untouched."""
    if not await service.delete_project(db, tenant_id=tenant_id, project_id=project_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")


@router.get("/{project_id}/candidates")
async def candidate_companies(
    project_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Watched employers not yet in this project."""
    if await service.get_project(db, tenant_id=tenant_id, project_id=project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return await service.candidate_companies(
        db, tenant_id=tenant_id, project_id=project_id
    )


@router.post("/{project_id}/companies", response_model=ProjectDetail)
async def add_companies(
    project_id: uuid.UUID,
    payload: AddCompaniesRequest,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ProjectDetail:
    """Put corpus companies in the project. Idempotent."""
    try:
        await service.add_companies(
            db,
            tenant_id=tenant_id,
            project_id=project_id,
            hub_company_ids=payload.hub_company_ids,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    detail = await service.project_detail(
        db, tenant_id=tenant_id, project_id=project_id
    )
    return ProjectDetail.model_validate(detail)


@router.delete(
    "/{project_id}/companies/{hub_company_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_company(
    project_id: uuid.UUID,
    hub_company_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    removed = await service.remove_company(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        hub_company_id=hub_company_id,
    )
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not in this project")
