"""Documents API — CV upload & extraction."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.auth import get_current_tenant
from app.core.database import get_db
from app.domain.documents import service
from app.domain.documents.gate import PreconditionFailed
from app.domain.documents.schemas import CVExtractionResult

router = APIRouter(prefix="/documents", tags=["documents"])

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("/extract-cv", response_model=CVExtractionResult)
async def extract_cv(
    file: UploadFile = File(...),
    persist: bool = Query(
        default=False,
        description="If true, create a candidate from the accepted fields and record receipts.",
    ),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> CVExtractionResult:
    """Parse an uploaded PDF CV into structured fields with per-field confidence.

    Low-confidence fields are flagged for human review (never silently trusted).
    Set ``persist=true`` to create a candidate from the accepted fields.
    """
    if file.content_type not in ("application/pdf", "application/octet-stream", None):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "only PDF uploads are supported"
        )
    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty file")
    if len(content) > _MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file too large (max 10 MB)")

    try:
        return await service.extract_cv(
            db,
            filename=file.filename or "cv.pdf",
            content=content,
            tenant_id=tenant_id,
            persist=persist,
        )
    except PreconditionFailed as exc:
        # A blocking pre/postcondition did not hold — reject rather than write.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc