"""Verification API — read-only views into the append-only ledger.

There is deliberately NO endpoint to create or mutate receipts directly; they
are only ever produced as a side effect of ``verify_and_commit``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.auth import get_current_tenant
from app.core.database import get_db
from app.domain.verification import service
from app.domain.verification.schemas import ReceiptRead

router = APIRouter(prefix="/verification", tags=["verification"])


@router.get("/receipts", response_model=list[ReceiptRead])
async def list_receipts(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[ReceiptRead]:
    """Return the tenant's receipt ledger, newest first."""
    receipts = await service.list_receipts(db, tenant_id=tenant_id, limit=limit)
    return [ReceiptRead.model_validate(r) for r in receipts]


@router.get("/receipts/verify-chain")
async def verify_chain(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Recompute the hash chain and report whether it is intact."""
    ok, reason = await service.verify_chain(db, tenant_id=tenant_id)
    return {"intact": ok, "detail": reason}