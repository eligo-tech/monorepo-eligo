"""The call list (ELI-22): who to call next, and what happened when we did.

Two tabs. "Anrufen": people open ads name, across the market, that this
workspace has not called yet — direct lines first. "Wiedervorlage": people this
workspace has called, by when the next call is due. The first logged call takes
the person into the workspace (company + manager, Art. 14 owed) and records the
outcome on the contact history.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.domain.companies.models import Company
from app.domain.hub import call_list
from app.domain.hub.models import HubAdContact, HubCompany, HubJobPosting
from app.domain.managers.models import Manager, ManagerInteraction

TENANT = uuid.uuid4()
OTHER = uuid.uuid4()
NOW = dt.datetime(2026, 11, 11, 9, 0, tzinfo=dt.UTC)


async def _employer(s, name: str, normalized: str, *, kind: str = "employer", city: str = "Spaichingen") -> HubCompany:
    now = dt.datetime.now(dt.UTC)
    c = HubCompany(name=name, normalized_name=normalized, dedupe_key=f"k-{uuid.uuid4()}", resolution_basis="name_place",
                   city=city, source="bundesagentur", first_seen_at=now, last_seen_at=now, kind=kind)
    s.add(c)
    await s.flush()
    return c


async def _ad(s, company: HubCompany, title: str, *, active: bool = True) -> HubJobPosting:
    now = dt.datetime.now(dt.UTC)
    p = HubJobPosting(hub_company_id=company.id, title=title, source="bundesagentur", external_id=f"x-{uuid.uuid4()}",
                      content_hash="h", first_seen_at=now, last_seen_at=now, is_active=active,
                      source_url="https://example.invalid/ad")
    s.add(p)
    await s.flush()
    return p


def _person(posting: HubJobPosting, first: str | None, last: str, *, phone=None, kind=None, role=None) -> HubAdContact:
    full = f"{first} {last}" if first else last
    return HubAdContact(
        hub_job_posting_id=posting.id, hub_company_id=posting.hub_company_id, person_key=last.lower(),
        full_name=full, salutation="Frau", first_name=first, last_name=last, role_title=role, phone=phone,
        phone_kind=kind, quote=f"Ihr Ansprechpartner: Frau {full}", text_source="ad",
    )


@pytest.fixture
async def market() -> dict:
    """Forschner names Denkinger (direct line) in two ads; Linde names Kraft
    (switchboard) once and Weber (no phone); Brunel is an agency; a closed ad
    names Alt."""
    async with SessionLocal() as s:
        forschner = await _employer(s, "Eugen Forschner GmbH", "eugen forschner")
        linde = await _employer(s, "Gasthaus Linde GmbH", "gasthaus linde", city="Berlin")
        brunel = await _employer(s, "Brunel GmbH", "brunel", kind="private_recruiter")
        f1, f2 = await _ad(s, forschner, "Konstrukteur"), await _ad(s, forschner, "Entwicklungsingenieur")
        l1, b1 = await _ad(s, linde, "Koch"), await _ad(s, brunel, "Embedded Entwickler")
        closed = await _ad(s, linde, "Kellner", active=False)
        s.add_all([
            _person(f1, "Leonie", "Denkinger", phone="+49 7424 943 126", kind="direct", role="Sachbearbeiter/in Personal"),
            _person(f2, None, "Denkinger", phone="+49 7424 943 126", kind="direct"),
            _person(l1, "Anna", "Kraft", phone="030 2295 0", kind="switchboard"),
            _person(l1, "Jan", "Weber"),
            _person(b1, "Tim", "Agent", phone="0711 1234567", kind="direct"),
            _person(closed, "Olaf", "Alt", phone="030 1111111", kind="direct"),
        ])
        await s.commit()
        return {"forschner": forschner.id, "linde": linde.id}


async def _market(**kw) -> list[dict]:
    async with SessionLocal() as s:
        return (await call_list.market(s, tenant_id=kw.pop("tenant", TENANT), **kw))["rows"]


async def _call(hub_company_id, person_key, outcome, *, tenant=TENANT, **kw) -> dict:
    async with SessionLocal() as s:
        return await call_list.log_call(
            s, tenant_id=tenant, hub_company_id=hub_company_id, person_key=person_key, outcome=outcome, **kw
        )


async def test_the_market_tab_lists_named_people_direct_lines_first(market) -> None:
    rows = await _market()
    assert [r["last_name"] for r in rows] == ["Denkinger", "Kraft", "Weber"]
    denkinger = rows[0]
    # Merged across the employer's ads, the fuller mention wins.
    assert denkinger["full_name"] == "Leonie Denkinger"
    assert (denkinger["phone"], denkinger["phone_kind"]) == ("+49 7424 943 126", "direct")
    assert denkinger["role_title"] == "Sachbearbeiter/in Personal"
    assert denkinger["open_ads"] == 2
    assert denkinger["company_name"] == "Eugen Forschner GmbH"
    assert denkinger["reach"] == "named_phone"
    assert "Denkinger" in denkinger["quote"] and denkinger["source_url"]
    assert rows[2]["reach"] == "named"
    # An agency's ad and a closed ad name nobody to call.
    assert not {"Agent", "Alt"} & {r["last_name"] for r in rows}


async def test_the_market_tab_filters(market) -> None:
    assert [r["last_name"] for r in await _market(phone_only=True)] == ["Denkinger", "Kraft"]
    assert [r["last_name"] for r in await _market(q="linde")] == ["Kraft", "Weber"]
    assert [r["last_name"] for r in await _market(limit=1, offset=1)] == ["Kraft"]


async def test_the_first_call_takes_the_person_into_the_workspace(market) -> None:
    result = await _call(market["forschner"], "denkinger", "not_reached")
    async with SessionLocal() as s:
        company = await s.get(Company, result["company_id"])
        manager = await s.get(Manager, result["manager_id"])
        calls = (await s.scalars(select(ManagerInteraction).where(ManagerInteraction.manager_id == manager.id))).all()
    assert company.name == "Eugen Forschner GmbH" and company.tenant_id == TENANT
    assert (manager.full_name, manager.phone, manager.role_title) == (
        "Leonie Denkinger", "+49 7424 943 126", "Sachbearbeiter/in Personal")
    assert manager.source == "public_web" and manager.source_detail == "https://example.invalid/ad"
    assert manager.art14_outstanding is True and result["art14_outstanding"] is True
    assert [(c.interaction_type, c.outcome) for c in calls] == [("business_call", "not_reached")]


async def test_a_called_person_moves_from_the_market_tab_to_follow_ups(market) -> None:
    when = NOW + dt.timedelta(days=2)
    await _call(market["forschner"], "denkinger", "call_back", next_action_at=when, summary="Donnerstag")
    assert "Denkinger" not in {r["last_name"] for r in await _market()}
    async with SessionLocal() as s:
        (row,) = await call_list.follow_ups(s, tenant_id=TENANT, now=NOW)
    assert (row["full_name"], row["outcome"], row["company_name"]) == ("Leonie Denkinger", "call_back", "Eugen Forschner GmbH")
    assert row["next_action_at"].replace(tzinfo=dt.UTC) == when and row["due"] is False


async def test_follow_ups_due_first_and_wrong_person_dropped(market) -> None:
    await _call(market["forschner"], "denkinger", "call_back", next_action_at=NOW + dt.timedelta(days=3))
    await _call(market["linde"], "kraft", "call_back", next_action_at=NOW - dt.timedelta(hours=1))
    await _call(market["linde"], "weber", "wrong_person")
    async with SessionLocal() as s:
        rows = await call_list.follow_ups(s, tenant_id=TENANT, now=NOW)
    assert [(r["last_name"], r["due"]) for r in rows] == [("Kraft", True), ("Denkinger", False)]


async def test_the_second_call_reuses_the_manager_and_company(market) -> None:
    first = await _call(market["forschner"], "denkinger", "voicemail")
    second = await _call(market["forschner"], "denkinger", "meeting_booked")
    assert (second["manager_id"], second["company_id"]) == (first["manager_id"], first["company_id"])
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count(Manager.id)).where(Manager.tenant_id == TENANT)) == 1
        (row,) = await call_list.follow_ups(s, tenant_id=TENANT, now=NOW)
    assert row["outcome"] == "meeting_booked"


async def test_calls_are_per_workspace(market) -> None:
    await _call(market["forschner"], "denkinger", "not_reached")
    assert "Denkinger" in {r["last_name"] for r in await _market(tenant=OTHER)}
    async with SessionLocal() as s:
        assert await call_list.follow_ups(s, tenant_id=OTHER, now=NOW) == []


async def test_an_unknown_person_is_not_invented(market) -> None:
    with pytest.raises(call_list.NotOnTheList):
        await _call(market["forschner"], "mustermann", "not_reached")


async def _erase_manager(manager_id: uuid.UUID, name: str) -> None:
    from app.domain.erasure import service as erasure

    async with SessionLocal() as s:
        await erasure.erase_manager(
            s, tenant_id=TENANT, manager_id=manager_id, confirm_name=name, reason="erasure",
            requested_on=dt.date(2026, 11, 11), actor_user_id="u1", actor_name="Test",
        )
        await s.commit()  # the route commits; the service only flushes


async def test_an_erased_person_is_not_brought_back(market, monkeypatch) -> None:
    """GDPR Art. 17: a contact this workspace erased must not come back because
    an ad names them again — not on the list, and not by logging a call. Ad
    contacts almost never carry an e-mail, so the e-mail fingerprint alone
    would not hold them back."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "suppression_key", "k" * 40)
    first = await _call(market["linde"], "kraft", "not_reached")
    await _erase_manager(first["manager_id"], "Anna Kraft")
    assert "Kraft" not in {r["last_name"] for r in await _market()}
    with pytest.raises(call_list.Erased):
        await _call(market["linde"], "kraft", "not_reached")
    # Only this workspace erased her.
    assert "Kraft" in {r["last_name"] for r in await _market(tenant=OTHER)}


async def test_an_erased_number_is_not_brought_back_under_another_name(market, monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "suppression_key", "k" * 40)
    first = await _call(market["forschner"], "denkinger", "not_reached")
    await _erase_manager(first["manager_id"], "Leonie Denkinger")
    async with SessionLocal() as s:
        p = await _ad(s, await s.get(HubCompany, market["linde"]), "Spüler")
        s.add(_person(p, "L.", "Dengler", phone="+49 7424 943 126", kind="direct"))
        await s.commit()
    assert "Dengler" not in {r["last_name"] for r in await _market()}

