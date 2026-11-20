"""Companies API."""

from __future__ import annotations

import uuid

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, get_current_tenant
from app.core.database import get_db
from app.domain.companies import service
from app.domain.companies import market
from app.domain.companies.schemas import (
    CompanyCreate,
    CompanyOverviewRow,
    CompanyPage,
    CompanyRead,
    CompanyStatusUpdate,
    FrameworkContractWrite,
    MarketSites,
)
from app.domain.hub.schemas import Switchboard

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[CompanyRead])
async def list_companies(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[CompanyRead]:
    rows = await service.list_companies(db, tenant_id=tenant_id, limit=limit)
    return [CompanyRead.model_validate(r) for r in rows]


@router.get("/overview", response_model=list[CompanyOverviewRow])
async def companies_overview(
    kind: Literal["all", "clients", "leads"] = Query(default="all"),
    q: str | None = Query(default=None, max_length=200),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[CompanyOverviewRow]:
    """Unternehmen (ELI-33): every company here — clients (≥1 manager) and
    lead companies (≥1 new contact from Markt) — with counts, A–Z."""
    return [CompanyOverviewRow(**r) for r in await service.overview(db, tenant_id=tenant_id, kind=kind, q=q)]


@router.get("/{company_id}/page", response_model=CompanyPage)
async def company_page(
    company_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> CompanyPage:
    """One company: managers, leads, mandates, Impressum switchboard."""
    page = await service.company_page(db, tenant_id=tenant_id, company_id=company_id)
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found")
    return CompanyPage(**page)


@router.get("/{company_id}/register", response_model=Switchboard | None)
async def company_register(
    company_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> Switchboard | None:
    """ELI-39: website, VAT id and register as the company's Impressum
    publishes them (Markt's reading, else the company's own), with the page
    and fetch time — or null while none is verified. Reads only: the daily
    job fills it, never this request."""
    if await service.get_company(db, tenant_id=tenant_id, company_id=company_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found")
    from app.domain.hub.call_list import company_switchboards

    board = (await company_switchboards(db, tenant_id, [company_id])).get(company_id)
    return Switchboard(**board) if board else None


async def _page_or_404(db: AsyncSession, tenant_id: uuid.UUID, company_id: uuid.UUID) -> CompanyPage:
    page = await service.company_page(db, tenant_id=tenant_id, company_id=company_id)
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found")
    return CompanyPage(**page)


@router.post("/{company_id}/market-links", response_model=CompanyPage)
async def confirm_market_link(
    company_id: uuid.UUID,
    payload: MarketSites,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> CompanyPage:
    """ELI-33 step 2b: "Das ist unser Unternehmen" — link these Markt sites
    (same name) to this company. A receipt names the person."""
    try:
        await market.confirm(
            db,
            tenant_id=actor.tenant_id,
            company_id=company_id,
            hub_company_ids=payload.hub_company_ids,
            actor=actor.name,
            dismiss_ids=payload.dismiss_ids,
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found") from exc
    except market.NotACandidate as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except market.SiteTaken as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _page_or_404(db, actor.tenant_id, company_id)


@router.delete("/{company_id}/market-links", response_model=CompanyPage)
async def undo_market_link(
    company_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> CompanyPage:
    """ELI-33: undo a wrong link; the sites are not linked again by the job."""
    try:
        await market.unlink(db, tenant_id=actor.tenant_id, company_id=company_id, actor=actor.name)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found") from exc
    return await _page_or_404(db, actor.tenant_id, company_id)


@router.post("/{company_id}/market-dismissals", response_model=CompanyPage)
async def dismiss_market_sites(
    company_id: uuid.UUID,
    payload: MarketSites,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> CompanyPage:
    """ELI-33 step 2b: "Keiner davon" — not suggested again."""
    try:
        await market.dismiss(db, tenant_id=actor.tenant_id, company_id=company_id, hub_company_ids=payload.hub_company_ids)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found") from exc
    return await _page_or_404(db, actor.tenant_id, company_id)


@router.get("/{company_id}", response_model=CompanyRead)
async def get_company(
    company_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> CompanyRead:
    row = await service.get_company(db, tenant_id=tenant_id, company_id=company_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found")
    return CompanyRead.model_validate(row)


@router.post("", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
async def create_company(
    payload: CompanyCreate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> CompanyRead:
    """A company typed in by a person (ELI-43 "+ Unternehmen", a new
    mandate's client). 409 "company exists as <id>" for a duplicate."""
    payload.tenant_id = actor.tenant_id  # force the authenticated tenant
    try:
        row = await service.create_company(db, data=payload, actor=actor.name)
    except service.CompanyExists as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return CompanyRead.model_validate(row)


@router.put("/{company_id}/status", response_model=CompanyPage)
async def set_company_status(
    company_id: uuid.UUID,
    payload: CompanyStatusUpdate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> CompanyPage:
    """ELI-43: Lead / Kunde on the company page — a receipt names the person."""
    try:
        await service.set_status(
            db, tenant_id=actor.tenant_id, company_id=company_id, status=payload.status, actor=actor.name
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found") from exc
    return await _page_or_404(db, actor.tenant_id, company_id)

@router.put("/{company_id}/framework-contract", response_model=CompanyPage)
async def set_framework_contract(
    company_id: uuid.UUID,
    payload: FrameworkContractWrite,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> CompanyPage:
    """ELI-64: "Rahmenvertrag abgeschlossen" — counted by Tracking."""
    # `signed_on: null` takes it back. A PUT, not a DELETE: every DELETE is
    # admin-only (ELI-27), and correcting one's own date is not a deletion.
    return await _framework(db, actor, company_id, payload.signed_on)


async def _framework(db: AsyncSession, actor: Actor, company_id: uuid.UUID, signed_on) -> CompanyPage:  # noqa: ANN001
    try:
        await service.set_framework_contract(
            db,
            tenant_id=actor.tenant_id,
            company_id=company_id,
            signed_on=signed_on,
            actor_user_id=actor.user_id,
            actor_name=actor.name if actor.user_id else None,
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found") from exc
    return await _page_or_404(db, actor.tenant_id, company_id)
