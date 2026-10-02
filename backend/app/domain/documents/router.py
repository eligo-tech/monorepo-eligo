"""Documents API — uploads (CV, Transkript, Zeugnisse) & extraction."""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_tenant
from app.core.database import get_db
from app.domain.common.enums import DocumentKind
from app.domain.documents import service
from app.domain.documents.gate import PreconditionFailed
from app.domain.documents.schemas import CVExtractionResult, DocumentRead

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


#: What may be attached. A Zeugnis is usually a scan, a transcript is often a
#: text export — both belong on the record even when nothing can parse them.
_ALLOWED_TYPES = {
    "application/pdf",
    "application/octet-stream",
    "text/plain",
    "image/png",
    "image/jpeg",
}
#: What the transcript reader can actually turn into text.
_READABLE_TYPES = {"application/pdf", "application/octet-stream", "text/plain"}


async def _read_upload(file: UploadFile, allowed: set[str]) -> bytes:
    if file.content_type not in allowed:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"unsupported type {file.content_type!r}",
        )
    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty file")
    if len(content) > _MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file too large (max 10 MB)"
        )
    return content


@router.post(
    "/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED
)
async def upload_document(
    file: UploadFile = File(...),
    candidate_id: uuid.UUID = Form(...),
    kind: DocumentKind = Form(DocumentKind.SONSTIGES),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> DocumentRead:
    """Attach a file to a candidate — Zeugnis, Zertifikat, CV, anything.

    Storing is not parsing: a scanned Zeugnis has no machine-readable content
    and still belongs on the record, because the client asks for it before the
    interview.
    """
    content = await _read_upload(file, _ALLOWED_TYPES)
    doc = await service.store_document(
        db,
        tenant_id=tenant_id,
        candidate_id=candidate_id,
        filename=file.filename or "dokument",
        content=content,
        content_type=file.content_type or "application/octet-stream",
        kind=kind.value,
    )
    return DocumentRead.model_validate(doc)


@router.get("/candidate/{candidate_id}", response_model=list[DocumentRead])
async def list_candidate_documents(
    candidate_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentRead]:
    """Every file on a candidate, newest first (metadata only)."""
    return [
        DocumentRead.model_validate(d)
        for d in await service.list_documents(
            db, tenant_id=tenant_id, candidate_id=candidate_id
        )
    ]


@router.get("/{document_id}/content")
async def download_document(
    document_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Stream one stored file."""
    doc = await service.get_document(db, tenant_id=tenant_id, document_id=document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return Response(
        content=doc.content,
        media_type=doc.content_type,
        headers={"Content-Disposition": f'inline; filename="{doc.filename}"'},
    )


@router.post("/extract-transcript", response_model=CVExtractionResult)
async def extract_transcript(
    file: UploadFile = File(...),
    candidate_id: uuid.UUID = Form(...),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> CVExtractionResult:
    """Read a Gesprächstranskript for the qualification fields.

    Returns PROPOSALS with their confidence and stores the transcript as
    evidence. Nothing is written to the candidate: the recruiter confirms the
    values, and that PATCH is what the record then records as a human edit.
    """
    content = await _read_upload(file, _READABLE_TYPES)
    try:
        return await service.extract_transcript(
            db,
            tenant_id=tenant_id,
            candidate_id=candidate_id,
            filename=file.filename or "transkript.txt",
            content=content,
            content_type=file.content_type or "application/pdf",
        )
    except PreconditionFailed as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
