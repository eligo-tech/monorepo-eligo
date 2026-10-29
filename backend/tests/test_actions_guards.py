"""Guards on the catalog itself, and the receipt every AI read leaves.

T3 — two things may never become an AI tool, whatever someone registers:
an EXTERNAL action (sends, crawls, calls a provider), and anything that wraps
ingestion (ARCHITECTURE.md RULE 1: filling the corpus is a cron's job, never
a request's). Each guard is shown failing on a bad registration first.

T4 — every call by an AI client appends one READ receipt naming the tool, the
user, the OAuth client and the record ids returned. "Every AI access is
receipted" is the pitch; this is the test that makes it a fact.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.actions import catalog  # noqa: F401 — registers the actions
from app.actions import core
from app.actions.core import REGISTRY, ActionContext, Effect
from app.actions.schemas import _Out, Source
from app.core.auth import RECRUITER, Actor
from app.core.database import SessionLocal
from app.domain.common.enums import ReceiptAction
from app.domain.hub import service as hub
from app.domain.verification import service as verification
from app.domain.verification.models import Receipt


class _Args(BaseModel):
    pass


# --- T3: catalog guards ------------------------------------------------------


def test_the_real_catalog_passes_its_guards() -> None:
    REGISTRY.check()


def test_an_external_action_is_never_exposed_to_an_agent() -> None:
    assert all(s.effect is not Effect.EXTERNAL for s in REGISTRY.agent_exposed())
    reg = core.Registry()

    @reg.action("bad.send", effect=Effect.EXTERNAL, description="x", input=_Args)
    async def _send(ctx, args):
        return None

    # Registered fine (a human-only external action is allowed to exist) …
    assert "bad.send" not in {s.name for s in reg.agent_exposed()}


async def _calls_ingest(ctx, args):
    return await hub.ingest(ctx.session, request=args)


async def _calls_fetch_missing(ctx, args):
    return await hub.fetch_missing_descriptions(ctx.session)


async def _calls_deactivate(ctx, args):
    return await hub.deactivate_stale_postings(ctx.session)


async def _hides_it_in_a_closure(ctx, args):
    async def inner():
        return await hub.fetch_missing_partner_pages(ctx.session)

    return await inner()


@pytest.mark.parametrize(
    "handler", [_calls_ingest, _calls_fetch_missing, _calls_deactivate, _hides_it_in_a_closure]
)
def test_an_action_wrapping_ingestion_is_refused(handler) -> None:
    reg = core.Registry()
    reg.action("bad.crawl", effect=Effect.READ, description="x", input=_Args)(handler)
    with pytest.raises(core.CatalogViolation):
        reg.check()


# --- T4: read receipts -------------------------------------------------------


def _actor(tenant_id: uuid.UUID, kind: str) -> Actor:
    return Actor(
        tenant_id=tenant_id,
        user_id="user_42",
        name="Dana Recruiter",
        role=RECRUITER,
        role_known=True,
        kind=kind,
        client_id="TsCnqZKIJmVBnGy2" if kind == "agent" else None,
    )


class _Result(_Out):
    pass


@pytest.fixture
def reg() -> core.Registry:
    reg = core.Registry()
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]

    @reg.action("t.read", effect=Effect.READ, description="x", input=_Args)
    async def _read(ctx, args):
        return _Result(sources=[Source(type="candidate", id=i) for i in ids])

    reg.returned_ids = ids  # type: ignore[attr-defined]
    return reg


async def _receipts(tenant_id: uuid.UUID) -> list[Receipt]:
    async with SessionLocal() as s:
        return list(
            (
                await s.execute(
                    select(Receipt)
                    .where(Receipt.tenant_id == tenant_id)
                    .order_by(Receipt.chain_index)
                )
            ).scalars()
        )


async def test_an_agent_read_leaves_one_read_receipt(reg) -> None:
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        await reg.invoke("t.read", ActionContext(session=s, actor=_actor(tenant, "agent")), {})

    [receipt] = await _receipts(tenant)
    assert receipt.action == ReceiptAction.READ
    assert receipt.subject_type == "action" and receipt.subject_id == "t.read"
    assert receipt.actor_user_id == "user_42"
    assert receipt.payload["client_id"] == "TsCnqZKIJmVBnGy2"
    assert receipt.payload["returned"] == [{"type": "candidate", "id": i} for i in reg.returned_ids]
    async with SessionLocal() as s:
        ok, why = await verification.verify_chain(s, tenant_id=tenant)
    assert ok, why


async def test_a_human_read_through_the_registry_leaves_no_read_receipt(reg) -> None:
    # Control: the browser's reads were never receipted; the registry must not
    # start writing a ledger row per page view.
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        await reg.invoke("t.read", ActionContext(session=s, actor=_actor(tenant, "human")), {})
    assert await _receipts(tenant) == []


async def test_a_real_action_called_by_an_agent_is_receipted() -> None:
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        await REGISTRY.invoke(
            "candidates.list", ActionContext(session=s, actor=_actor(tenant, "agent")), {}
        )
    [receipt] = await _receipts(tenant)
    assert receipt.subject_id == "candidates.list"
