"""Import API — upload a file, see what it would do, then do it.

Two calls, both tenant-scoped and both cheap: parsing and matching happen in
the request because there is no outbound call and no credential involved —
unlike the ATS pull, which is a scheduled job for exactly those reasons.

The file is uploaded twice (once to preview, once to commit) rather than held
server-side between the two. Onboarding files are small, and a stateless pair
of calls has no sessions to expire, nothing to clean up, and no way for two
tabs to confuse each other's upload.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_tenant
from app.core.database import get_db
from app.domain.imports import parser, service
from app.domain.imports.schemas import (
    EntityFieldRead,
    EntityRead,
    ImportResultRead,
    PreviewRead,
    RowPlanRead,
)
from app.domain.imports.spec import SPECS

router = APIRouter(prefix="/imports", tags=["imports"])

#: Onboarding files are lists, not archives.
_MAX_BYTES = 20 * 1024 * 1024
#: How many planned rows the preview returns. Enough to see a wrong mapping,
#: small enough to render.
_SAMPLE = 25


@router.get("/entities", response_model=list[EntityRead])
async def entities(
    _tenant_id: uuid.UUID = Depends(get_current_tenant),
) -> list[EntityRead]:
    """What can be imported, and which fields each kind understands."""
    return [
        EntityRead(
            key=key,
            label=spec.label,
            hint=spec.hint,
            fields=[
                EntityFieldRead(
                    name=f.name, label=f.label, required=f.name in spec.required
                )
                for f in spec.fields
            ],
        )
        for key, spec in SPECS.items()
    ]


async def _read_file(file: UploadFile):
    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Die Datei ist leer.")
    if len(content) > _MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Datei zu groß (max. 20 MB)."
        )
    try:
        return parser.read(file.filename or "import.csv", content)
    except parser.UnreadableFile as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("/preview", response_model=PreviewRead)
async def preview(
    file: UploadFile = File(...),
    entity: str = Form(...),
    mapping: str | None = Form(default=None),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> PreviewRead:
    """Read the file and say what importing it would do. Writes nothing."""
    sheet = await _read_file(file)
    try:
        chosen = (
            json.loads(mapping) if mapping else service.suggest_mapping(entity, sheet.columns)
        )
        planned = await service.plan(
            db, tenant_id=tenant_id, entity=entity, rows=sheet.rows, mapping=chosen
        )
    except service.UnknownEntity as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "mapping is not JSON") from exc

    return PreviewRead(
        entity=entity,
        note=sheet.note,
        columns=sheet.columns,
        mapping=chosen,
        row_count=len(sheet.rows),
        counts=planned.counts,
        sample=[
            RowPlanRead(
                line=row.line, action=row.action, reason=row.reason, values=row.values
            )
            for row in planned.rows[:_SAMPLE]
        ],
        problems=sheet.problems + planned.problems,
    )


@router.post("/commit", response_model=ImportResultRead)
async def commit(
    file: UploadFile = File(...),
    entity: str = Form(...),
    mapping: str = Form(...),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ImportResultRead:
    """Import the file with the mapping the recruiter confirmed."""
    sheet = await _read_file(file)
    try:
        result = await service.commit(
            db,
            tenant_id=tenant_id,
            entity=entity,
            rows=sheet.rows,
            mapping=json.loads(mapping),
        )
    except service.UnknownEntity as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "mapping is not JSON") from exc
    return ImportResultRead(**result)
