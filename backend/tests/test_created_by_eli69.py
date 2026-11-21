"""ELI-69: "Angelegt von" — every lead, manager and company shows who added it.

Each person logs in with an own account inside the shared workspace (a Clerk
organization). The creator is the logged-in account at the moment the row is
INSERTed — set by the system, never typed, never changed afterwards:

  * every create path a person takes stamps it: "+ Unternehmen", "+ Lead"
    (and the company it creates), adoption from Markt, a manager typed in;
  * an import or a system job has no person behind it, so it stays NULL;
  * editing, promoting a lead to manager, removing and restoring keep it;
  * the lists filter by it (`created_by=<user id>|me`), only inside the
    workspace — a creator from another workspace never shows;
  * existing rows get a creator only where a creation receipt proves it
    (`scripts/backfill_created_by.py`); everything else stays NULL.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.auth import ADMIN, Actor, get_current_actor
from app.core.config import settings
from app.core.context import ActorRef, current_actor_var
from app.core.database import SessionLocal
from app.domain.common.enums import ConfidenceSource, ReceiptAction
from app.domain.companies.models import Company
from app.domain.hub import service as hub_service
from app.domain.hub.models import HubCompany
from app.domain.managers.models import Manager
from app.domain.verification import service as verification

DEFAULT = settings.default_tenant_id
OTHER = uuid.uuid4()
API = settings.api_v1_prefix
JONAS = "user_jonas"
XAVER = "user_xaver"
STRANGER = "user_stranger"

LEAD = {
    "job_title": "Senior Java Entwickler (m/w/d)",
    "source_url": "https://www.stepstone.de/stellenangebote--Senior-Java-12345.html",
    "full_name": "Anna Kraft",
    "role_title": "Head of Engineering",
    "company_name": "Nordlicht Software GmbH",
}


@pytest.fixture(autouse=True)
def _no_ambient_actor():
    token = current_actor_var.set(None)
    yield
    current_actor_var.reset(token)


def _as(user_id: str | None, name: str, tenant: uuid.UUID = DEFAULT) -> None:
    """Every request from now on is this person's, as `get_current_actor`
    would resolve it from the token — including publishing the actor."""
    from app.core import auth
    from app.main import app

    async def actor() -> Actor:
        return auth._remembered(
            Actor(tenant_id=tenant, user_id=user_id, name=name, role=ADMIN, role_known=True)
        )

    app.dependency_overrides[get_current_actor] = actor


@pytest.fixture
def api():
    from app.main import app

    yield lambda: AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.pop(get_current_actor, None)


class _acting:
    """`current_actor_var` for service-level calls, as a request would set it."""

    def __init__(self, user_id: str | None, name: str = "") -> None:
        self.ref = ActorRef(user_id=user_id, name=name)

    def __enter__(self):
        self.token = current_actor_var.set(self.ref)

    def __exit__(self, *exc):
        current_actor_var.reset(self.token)


async def _row(model, row_id) -> object:
    async with SessionLocal() as s:
        return await s.get(model, uuid.UUID(str(row_id)))


# --- every create path stamps the account ----------------------------------


async def test_plus_unternehmen_records_who_added_it(api) -> None:
    _as(JONAS, "Jonas")
    async with api() as c:
        r = await c.post(f"{API}/companies", json={"name": "Bergfreunde GmbH"})
    assert r.status_code == 201, r.text
    assert r.json()["created_by_name"] == "Jonas"
    company = await _row(Company, r.json()["id"])
    assert (company.created_by_user_id, company.created_by_name) == (JONAS, "Jonas")


async def test_a_lead_by_hand_stamps_the_lead_and_the_company_it_creates(api) -> None:
    _as(XAVER, "Xaver")
    async with api() as c:
        r = await c.post(f"{API}/managers/leads", json=LEAD)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created_by_name"] == "Xaver"
    assert body["created_by_user_id"] == XAVER
    company = await _row(Company, body["company_id"])
    assert (company.created_by_user_id, company.created_by_name) == (XAVER, "Xaver")


async def test_a_manager_typed_in_is_stamped(api) -> None:
    async with SessionLocal() as s:
        company = Company(tenant_id=DEFAULT, name="Acme")
        s.add(company)
        await s.commit()
        company_id = company.id
    _as(JONAS, "Jonas")
    async with api() as c:
        r = await c.post(
            f"{API}/managers",
            json={"company_id": str(company_id), "full_name": "Max Muster", "source": "human_verified"},
        )
    assert r.status_code == 201, r.text
    assert r.json()["created_by_name"] == "Jonas"
    # Created outside any request: no person, no creator.
    assert (await _row(Company, company_id)).created_by_user_id is None


@pytest.fixture
async def corpus_company() -> uuid.UUID:
    now = dt.datetime.now(dt.UTC)
    async with SessionLocal() as s:
        company = HubCompany(
            name="Bayoonet AG", normalized_name="bayoonet", dedupe_key=f"k-{uuid.uuid4()}",
            resolution_basis="name_place", website_domain="bayoonet.de", city="Berlin",
            source="bundesagentur", first_seen_at=now, last_seen_at=now,
        )
        s.add(company)
        await s.commit()
        return company.id


async def test_adopting_from_markt_stamps_the_company(corpus_company) -> None:
    with _acting(JONAS, "Jonas"):
        async with SessionLocal() as s:
            company, _link, manager = await hub_service.adopt_company(
                s, tenant_id=DEFAULT, hub_company_id=corpus_company,
                manager={"full_name": "Frau Weber", "source": ConfidenceSource.PUBLIC_WEB.value},
            )
    assert (company.created_by_user_id, company.created_by_name) == (JONAS, "Jonas")
    assert manager is not None and manager.created_by_user_id == JONAS


async def test_adopting_via_the_api_stamps_the_company(api, corpus_company) -> None:
    _as(XAVER, "Xaver")
    async with api() as c:
        r = await c.post(f"{API}/hub/companies/{corpus_company}/adopt", json={})
    assert r.status_code in (200, 201), r.text
    async with SessionLocal() as s:
        company = (await s.scalars(select(Company))).one()
    assert company.created_by_name == "Xaver"


async def test_an_import_leaves_the_creator_empty() -> None:
    from app.domain.imports import parser
    from app.domain.imports import service as imports

    async def _import(entity: str, raw: bytes) -> dict:
        sheet = parser.read("f.csv", raw)
        mapping = imports.suggest_mapping(entity, sheet.columns)
        async with SessionLocal() as s:
            return await imports.commit(s, tenant_id=DEFAULT, entity=entity, rows=sheet.rows, mapping=mapping)

    # A person uploads the file, but the rows are the old system's, not theirs.
    with _acting(JONAS, "Jonas"):
        await _import("companies", b"Firma,Ort\nAlpha GmbH,Berlin\n")
        await _import("managers", b"Name,Firma\nAnna Schmidt,Beta AG\n")
    async with SessionLocal() as s:
        companies = (await s.scalars(select(Company))).all()
        managers = (await s.scalars(select(Manager))).all()
    assert {c.name for c in companies} == {"Alpha GmbH", "Beta AG"}
    assert all(c.created_by_user_id is None and c.created_by_name is None for c in companies)
    assert len(managers) == 1 and managers[0].created_by_user_id is None


# --- set once, never changed -------------------------------------------------


async def test_edit_promote_remove_and_restore_keep_the_creator(api) -> None:
    _as(JONAS, "Jonas")
    async with api() as c:
        lead = (await c.post(f"{API}/managers/leads", json=LEAD)).json()
    lead_id, company_id = lead["id"], lead["company_id"]

    _as(XAVER, "Xaver")
    async with api() as c:
        assert (await c.patch(f"{API}/managers/{lead_id}", json={"role_title": "CTO"})).status_code == 200
        assert (await c.post(f"{API}/managers/{lead_id}/remove", json={"reason": "other"})).status_code == 200
        assert (await c.delete(f"{API}/managers/{lead_id}/no-interest")).status_code == 200
        r = await c.post(f"{API}/managers/{lead_id}/promote")
        assert r.status_code == 200, r.text
        assert r.json()["stage"] == "manager"
        assert r.json()["created_by_name"] == "Jonas"
        assert (await c.put(f"{API}/companies/{company_id}/status", json={"status": "client"})).status_code == 200
        assert (
            await c.put(f"{API}/companies/{company_id}/framework-contract", json={"signed_on": "2026-11-02"})
        ).status_code == 200

    manager = await _row(Manager, lead_id)
    assert (manager.created_by_user_id, manager.created_by_name) == (JONAS, "Jonas")
    company = await _row(Company, company_id)
    assert (company.created_by_user_id, company.created_by_name) == (JONAS, "Jonas")


async def test_the_creator_cannot_be_set_by_hand(api) -> None:
    _as(JONAS, "Jonas")
    async with api() as c:
        lead = (await c.post(f"{API}/managers/leads", json=LEAD)).json()
        await c.patch(
            f"{API}/managers/{lead['id']}",
            json={"created_by_user_id": XAVER, "created_by_name": "Xaver"},
        )
    manager = await _row(Manager, lead["id"])
    assert manager.created_by_user_id == JONAS


# --- shown on the lists and pages --------------------------------------------


async def _seed() -> dict[str, uuid.UUID]:
    """Two people in this workspace, one in another, one row with nobody."""
    ids: dict[str, uuid.UUID] = {}

    async def add(key: str, tenant: uuid.UUID, by: str | None, name: str, stage: str) -> None:
        with _acting(by, name):
            async with SessionLocal() as s:
                company = Company(tenant_id=tenant, name=f"Firma {key}")
                s.add(company)
                await s.flush()
                manager = Manager(
                    tenant_id=tenant, company_id=company.id, full_name=f"Person {key}",
                    source=ConfidenceSource.HUMAN_VERIFIED.value, stage=stage,
                )
                s.add(manager)
                await s.commit()
                ids[key], ids[f"c_{key}"] = manager.id, company.id

    await add("jonas_lead", DEFAULT, JONAS, "Jonas", "bus_dev")
    await add("xaver_lead", DEFAULT, XAVER, "Xaver", "bus_dev")
    await add("jonas_mgr", DEFAULT, JONAS, "Jonas", "manager")
    await add("nobody_lead", DEFAULT, None, "", "bus_dev")
    await add("stranger_lead", OTHER, STRANGER, "Fremd", "bus_dev")
    return ids


async def test_the_rows_carry_the_creator_name(api) -> None:
    ids = await _seed()
    _as(XAVER, "Xaver")
    async with api() as c:
        leads = (await c.get(f"{API}/hub/call-list/contacts")).json()["rows"]
        managers = (await c.get(f"{API}/managers", params={"stage": "manager"})).json()
        companies = (await c.get(f"{API}/companies/overview")).json()
        page = (await c.get(f"{API}/companies/{ids['c_jonas_lead']}/page")).json()
        nobody = (await c.get(f"{API}/companies/{ids['c_nobody_lead']}/page")).json()
        one = (await c.get(f"{API}/managers/{ids['jonas_lead']}")).json()
    by_name = {r["full_name"]: r["created_by_name"] for r in leads}
    assert by_name == {"Person jonas_lead": "Jonas", "Person xaver_lead": "Xaver", "Person nobody_lead": None}
    assert [m["created_by_name"] for m in managers] == ["Jonas"]
    assert {r["name"]: r["created_by_name"] for r in companies}["Firma xaver_lead"] == "Xaver"
    assert page["company"]["created_by_name"] == "Jonas"
    assert nobody["company"]["created_by_name"] is None
    assert one["created_by_name"] == "Jonas"


# --- the filter --------------------------------------------------------------


async def test_leads_filter_by_creator_and_me(api) -> None:
    await _seed()
    _as(JONAS, "Jonas")
    async with api() as c:
        mine = (await c.get(f"{API}/hub/call-list/contacts", params={"created_by": "me"})).json()
        xaver = (await c.get(f"{API}/hub/call-list/contacts", params={"created_by": XAVER})).json()
        everyone = (await c.get(f"{API}/hub/call-list/contacts")).json()
    assert [r["full_name"] for r in mine["rows"]] == ["Person jonas_lead"]
    assert mine["total"] == 1
    assert [r["full_name"] for r in xaver["rows"]] == ["Person xaver_lead"]
    assert everyone["total"] == 3


async def test_managers_filter_by_creator(api) -> None:
    await _seed()
    _as(XAVER, "Xaver")
    async with api() as c:
        jonas = (await c.get(f"{API}/managers", params={"created_by": JONAS})).json()
        mine = (await c.get(f"{API}/managers", params={"created_by": "me", "stage": "manager"})).json()
    assert sorted(m["full_name"] for m in jonas) == ["Person jonas_lead", "Person jonas_mgr"]
    assert mine == []


async def test_companies_filter_by_creator(api) -> None:
    await _seed()
    _as(JONAS, "Jonas")
    async with api() as c:
        mine = (await c.get(f"{API}/companies/overview", params={"created_by": "me"})).json()
    assert sorted(r["name"] for r in mine) == ["Firma jonas_lead", "Firma jonas_mgr"]


async def test_me_without_an_account_matches_nobody(api) -> None:
    """The auth-disabled demo has no account: "Ich" is nobody, not everybody
    and not the rows without a creator."""
    await _seed()
    _as(None, "Demo")
    async with api() as c:
        leads = (await c.get(f"{API}/hub/call-list/contacts", params={"created_by": "me"})).json()
    assert leads["rows"] == []


async def test_the_creator_choices_are_this_workspaces_people_only(api) -> None:
    await _seed()
    _as(JONAS, "Jonas")
    async with api() as c:
        leads = (await c.get(f"{API}/managers/creators", params={"stage": "bus_dev"})).json()
        managers = (await c.get(f"{API}/managers/creators", params={"stage": "manager"})).json()
        companies = (await c.get(f"{API}/companies/creators")).json()
    assert leads == [{"user_id": JONAS, "name": "Jonas"}, {"user_id": XAVER, "name": "Xaver"}]
    assert managers == [{"user_id": JONAS, "name": "Jonas"}]
    assert {c["user_id"] for c in companies} == {JONAS, XAVER}


async def test_a_creator_from_another_workspace_never_shows(api) -> None:
    await _seed()
    _as(JONAS, "Jonas")
    async with api() as c:
        leads = (await c.get(f"{API}/hub/call-list/contacts", params={"created_by": STRANGER})).json()
        managers = (await c.get(f"{API}/managers", params={"created_by": STRANGER})).json()
        companies = (await c.get(f"{API}/companies/overview", params={"created_by": STRANGER})).json()
        creators = (await c.get(f"{API}/companies/creators")).json()
    assert leads["rows"] == [] and managers == [] and companies == []
    assert STRANGER not in {c["user_id"] for c in creators}


async def test_the_latest_name_of_a_creator_is_the_one_offered() -> None:
    """A renamed account is one choice, not two."""
    from app.domain.common.creators import creators

    with _acting(JONAS, "Jonas"):
        async with SessionLocal() as s:
            s.add(Company(tenant_id=DEFAULT, name="A", created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC)))
            await s.commit()
    with _acting(JONAS, "Jonas Berger"):
        async with SessionLocal() as s:
            s.add(Company(tenant_id=DEFAULT, name="B", created_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC)))
            await s.commit()
    async with SessionLocal() as s:
        got = await creators(s, Company, tenant_id=DEFAULT)
    assert got == [{"user_id": JONAS, "name": "Jonas Berger"}]


# --- backfill: only where a receipt proves it ------------------------------


async def _receipt(tenant, *, agent, subject_type, subject_id, summary, actor, payload=None) -> None:
    names = {JONAS: "Jonas", XAVER: "Xaver", STRANGER: "Fremd"}
    with _acting(actor, names.get(actor, "")):
        async with SessionLocal() as s:
            await verification.append_receipt(
                s, tenant_id=tenant, agent=agent, action=ReceiptAction.WRITE,
                subject_type=subject_type, subject_id=str(subject_id), verified=True,
                summary=summary, payload=payload or {},
            )
            await s.commit()


async def test_the_backfill_copies_only_proven_creators() -> None:
    from scripts import backfill_created_by as backfill

    same_moment = dt.datetime(2026, 11, 10, 9, 0, tzinfo=dt.UTC)
    async with SessionLocal() as s:
        proven_co = Company(tenant_id=DEFAULT, name="Neu", created_at=same_moment)
        older_co = Company(tenant_id=DEFAULT, name="Alt", created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
        adopted = Company(tenant_id=DEFAULT, name="Aus Markt")
        silent = Company(tenant_id=DEFAULT, name="Ohne Beleg")
        s.add_all([proven_co, older_co, adopted, silent])
        await s.flush()
        lead_new_co = Manager(tenant_id=DEFAULT, company_id=proven_co.id, full_name="A", stage="bus_dev",
                              source="third_party_source", created_at=same_moment)
        lead_old_co = Manager(tenant_id=DEFAULT, company_id=older_co.id, full_name="B", stage="bus_dev",
                              source="third_party_source", created_at=same_moment)
        no_actor = Manager(tenant_id=DEFAULT, company_id=older_co.id, full_name="C", stage="bus_dev",
                           source="third_party_source")
        no_receipt = Manager(tenant_id=DEFAULT, company_id=older_co.id, full_name="D", stage="bus_dev",
                             source="public_web")
        already = Manager(tenant_id=DEFAULT, company_id=older_co.id, full_name="E", stage="bus_dev",
                          source="third_party_source", created_by_user_id=XAVER, created_by_name="Xaver")
        s.add_all([lead_new_co, lead_old_co, no_actor, no_receipt, already])
        await s.commit()
        ids = {k: v.id for k, v in {
            "proven_co": proven_co, "older_co": older_co, "adopted": adopted, "silent": silent,
            "lead_new_co": lead_new_co, "lead_old_co": lead_old_co, "no_actor": no_actor,
            "no_receipt": no_receipt, "already": already,
        }.items()}

    manual = dict(agent="recruiter", subject_type="manager", summary="Lead von Hand angelegt")
    await _receipt(DEFAULT, subject_id=ids["lead_new_co"], actor=JONAS,
                   payload={"company_id": str(ids["proven_co"])}, **manual)
    await _receipt(DEFAULT, subject_id=ids["lead_old_co"], actor=JONAS,
                   payload={"company_id": str(ids["older_co"])}, **manual)
    await _receipt(DEFAULT, subject_id=ids["no_actor"], actor=None, **manual)
    await _receipt(DEFAULT, subject_id=ids["already"], actor=JONAS, **manual)
    # A later edit is not a creation.
    await _receipt(DEFAULT, subject_id=ids["no_receipt"], actor=JONAS, agent="recruiter",
                   subject_type="manager", summary="Lead entfernt")
    await _receipt(DEFAULT, subject_id=ids["adopted"], actor=XAVER, agent="recruiter_adopt_company",
                   subject_type="company", summary="write hub_company_id")
    # Another workspace's receipt naming this workspace's row proves nothing.
    await _receipt(OTHER, subject_id=ids["silent"], actor=STRANGER, agent="recruiter_adopt_company",
                   subject_type="company", summary="write hub_company_id")

    first = await backfill.run(apply=True)
    assert first == {"managers": 2, "companies": 2}
    second = await backfill.run(apply=True)
    assert second == {"managers": 0, "companies": 0}

    async def by(model, key):
        row = await _row(model, ids[key])
        return row.created_by_user_id, row.created_by_name

    assert await by(Manager, "lead_new_co") == (JONAS, "Jonas")
    assert await by(Manager, "lead_old_co") == (JONAS, "Jonas")
    assert await by(Manager, "no_actor") == (None, None)
    assert await by(Manager, "no_receipt") == (None, None)
    assert await by(Manager, "already") == (XAVER, "Xaver")
    # Created in the same transaction as the lead: the lead's receipt proves it.
    assert await by(Company, "proven_co") == (JONAS, "Jonas")
    # Existed before the lead: the receipt says nothing about who created it.
    assert await by(Company, "older_co") == (None, None)
    assert await by(Company, "adopted") == (XAVER, "Xaver")
    assert await by(Company, "silent") == (None, None)


async def test_the_backfill_dry_run_writes_nothing() -> None:
    from scripts import backfill_created_by as backfill

    async with SessionLocal() as s:
        company = Company(tenant_id=DEFAULT, name="Aus Markt")
        s.add(company)
        await s.commit()
        company_id = company.id
    await _receipt(DEFAULT, subject_id=company_id, actor=XAVER, agent="recruiter_adopt_company",
                   subject_type="company", summary="write hub_company_id")
    assert await backfill.run(apply=False) == {"managers": 0, "companies": 1}
    assert (await _row(Company, company_id)).created_by_user_id is None
