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
    # A cold call is business development: the employer is a prospect.
    assert company.is_client is False
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



# --- routes ------------------------------------------------------------------


def _client(tenant: uuid.UUID = TENANT):
    from httpx import ASGITransport, AsyncClient

    from app.core.auth import Actor, get_current_actor, get_current_tenant
    from app.main import app

    app.dependency_overrides[get_current_tenant] = lambda: tenant
    app.dependency_overrides[get_current_actor] = lambda: Actor(tenant_id=tenant, user_id="u1", name="Dima", role="recruiter", role_known=True)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _no_overrides():
    yield
    from app.main import app

    app.dependency_overrides.clear()


async def test_the_routes_list_log_and_follow_up(market) -> None:
    from app.core.config import settings

    base = f"{settings.api_v1_prefix}/hub/call-list"
    async with _client() as c:
        page = (await c.get(f"{base}/market?phone_only=true")).json()
        assert [r["last_name"] for r in page["rows"]] == ["Denkinger", "Kraft"]
        first = page["rows"][0]
        logged = await c.post(f"{base}/calls", json={
            "hub_company_id": first["hub_company_id"], "person_key": first["person_key"],
            "outcome": "call_back", "next_action_at": "2026-11-13T09:00:00Z", "summary": "Donnerstag",
        })
        assert logged.status_code == 201, logged.text
        assert logged.json()["art14_outstanding"] is True
        follow = (await c.get(f"{base}/follow-ups")).json()
        assert [(r["full_name"], r["outcome"], r["last_call_by"]) for r in follow] == [
            ("Leonie Denkinger", "call_back", "Dima")]
        missing_date = await c.post(f"{base}/calls", json={
            "hub_company_id": first["hub_company_id"], "person_key": first["person_key"], "outcome": "call_back"})
        assert missing_date.status_code == 422
        unknown = await c.post(f"{base}/calls", json={
            "hub_company_id": first["hub_company_id"], "person_key": "mustermann", "outcome": "voicemail"})
        assert unknown.status_code == 404


async def test_the_routes_are_per_workspace(market) -> None:
    from app.core.config import settings

    base = f"{settings.api_v1_prefix}/hub/call-list"
    async with _client() as c:
        await c.post(f"{base}/calls", json={
            "hub_company_id": str(market["forschner"]), "person_key": "denkinger", "outcome": "voicemail"})
    async with _client(OTHER) as c:
        assert (await c.get(f"{base}/follow-ups")).json() == []


# --- review of the call list ---------------------------------------------------


@pytest.fixture
def key(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "suppression_key", "k" * 40)


SURNAMES = ["Albers", "Brandt", "Claasen", "Dietz", "Ebert", "Fuchs", "Gerber", "Hahn", "Imhof", "Jäger",
            "Kühn", "Lorenz"]


async def _many(n: int) -> uuid.UUID:
    """One employer naming n people (letter-only surnames: names are folded
    to letters for fingerprints), each with a direct line."""
    async with SessionLocal() as s:
        co = await _employer(s, "Grossbetrieb AG", "grossbetrieb")
        for i in range(n):
            p = await _ad(s, co, f"Stelle {i}")
            s.add(_person(p, "Kim", SURNAMES[i], phone=f"0711 1000{i:03d}", kind="direct"))
        await s.commit()
        return co.id


async def test_paging_skips_no_one_and_repeats_no_one_around_an_erased_person(key) -> None:
    co = await _many(12)
    first = await _call(co, "brandt", "not_reached")
    await _erase_manager(first["manager_id"], "Kim Brandt")
    seen: list[str] = []
    offset = 0
    async with SessionLocal() as s:
        while True:
            page = await call_list.market(s, tenant_id=TENANT, limit=4, offset=offset)
            seen += [r["last_name"] for r in page["rows"]]
            if not page["has_more"]:
                break
            offset = page["next_offset"]
    assert sorted(seen) == sorted(n for n in SURNAMES if n != "Brandt")


async def test_an_erased_switchboard_number_does_not_hide_the_colleagues(market, key) -> None:
    """Erasing someone reached through the reception must not take everyone
    else at that employer behind the same reception off the list."""
    async with SessionLocal() as s:
        linde = await s.get(HubCompany, market["linde"])
        p = await _ad(s, linde, "Spüler")
        s.add(_person(p, "Paul", "Brandt", phone="030 2295 0", kind="switchboard"))
        await s.commit()
    first = await _call(market["linde"], "kraft", "not_reached")
    await _erase_manager(first["manager_id"], "Anna Kraft")
    assert "Brandt" in {r["last_name"] for r in await _market()}


async def test_erasure_holds_after_the_company_was_renamed(market, key) -> None:
    # No phone: only the surname-at-employer fingerprint can hold her back.
    async with SessionLocal() as s:
        for row in (await s.scalars(select(HubAdContact).where(HubAdContact.last_name == "Denkinger"))).all():
            row.phone, row.phone_kind = None, None
        await s.commit()
    first = await _call(market["forschner"], "denkinger", "not_reached")
    async with SessionLocal() as s:
        (await s.get(Company, first["company_id"])).name = "Forschner (Spaichingen)"
        await s.commit()
    await _erase_manager(first["manager_id"], "Leonie Denkinger")
    assert "Denkinger" not in {r["last_name"] for r in await _market()}


async def test_a_surname_only_ad_does_not_land_on_a_hand_saved_namesake(market) -> None:
    """"Frau Weber" in an ad is not the "Peter Weber" a recruiter saved by hand."""
    from app.domain.managers import service as managers
    from app.domain.managers.schemas import ManagerCreate

    async with SessionLocal() as s:
        weber_ad = (await s.scalars(select(HubAdContact).where(HubAdContact.last_name == "Weber"))).one()
        weber_ad.first_name, weber_ad.full_name = None, "Weber"
        await s.commit()
    first = await _call(market["linde"], "kraft", "not_reached")
    async with SessionLocal() as s:
        peter = await managers.create_manager(
            s, tenant_id=TENANT, payload=ManagerCreate(company_id=first["company_id"], full_name="Peter Weber",
                                                       first_name="Peter", last_name="Weber"))
    result = await _call(market["linde"], "weber", "voicemail")
    assert result["manager_id"] != peter.id and result["created_manager"] is True


async def test_an_erased_person_does_not_come_back_through_markt_or_by_hand(market, key) -> None:
    from app.domain.erasure import service as erasure
    from app.domain.hub import service as hub
    from app.domain.managers import service as managers
    from app.domain.managers.schemas import ManagerCreate

    first = await _call(market["linde"], "kraft", "not_reached")
    await _erase_manager(first["manager_id"], "Anna Kraft")
    # Markt "Ansprechpartner" on an adopted employer → createManager.
    async with SessionLocal() as s:
        with pytest.raises(erasure.Suppressed):
            await managers.create_manager(s, tenant_id=TENANT, payload=ManagerCreate(
                company_id=first["company_id"], full_name="Anna Kraft", last_name="Kraft", phone="030 2295 0"))
    # The recruiter confirms she came back of her own accord: allowed.
    async with SessionLocal() as s:
        back = await managers.create_manager(s, tenant_id=TENANT, payload=ManagerCreate(
            company_id=first["company_id"], full_name="Anna Kraft", last_name="Kraft",
            override_suppression=True))
    # …and calls to her are logged on that record, not refused.
    again = await _call(market["linde"], "kraft", "meeting_booked")
    assert again["manager_id"] == back.id
    # Markt adopt-with-contact on a not-yet-adopted employer drops the person.
    async with SessionLocal() as s:
        other = await _employer(s, "Gasthaus Linde GmbH", "gasthaus linde", city="Potsdam")
        await s.commit()
    # (a fresh workspace has nothing erased: the person is created there)
    async with SessionLocal() as s:
        _c, _l, m = await hub.adopt_company(s, tenant_id=OTHER, hub_company_id=other.id,
                                            manager={"full_name": "Anna Kraft", "phone": "030 2295 0"})
    assert m is not None


async def test_the_market_guard_reads_the_email_too(market, key) -> None:
    async with SessionLocal() as s:
        row = (await s.scalars(select(HubAdContact).where(HubAdContact.last_name == "Weber"))).one()
        row.email = "jan.weber@linde.example"
        await s.commit()
    first = await _call(market["linde"], "weber", "not_reached")
    async with SessionLocal() as s:
        m = await s.get(Manager, first["manager_id"])
        m.email, m.last_name, m.full_name = "jan.weber@linde.example", "Weber-Lang", "Jan Weber-Lang"
        await s.commit()
    await _erase_manager(first["manager_id"], "Jan Weber-Lang")
    assert "Weber" not in {r["last_name"] for r in await _market()}


async def test_follow_ups_take_the_latest_call_even_on_a_tie(market) -> None:
    at = dt.datetime(2026, 11, 11, 9, 0, tzinfo=dt.UTC)
    first = await _call(market["linde"], "kraft", "call_back", next_action_at=at + dt.timedelta(days=1))
    async with SessionLocal() as s:
        call = (await s.scalars(select(ManagerInteraction).where(ManagerInteraction.manager_id == first["manager_id"]))).one()
        call.occurred_at = at
        # Same call time, written a moment later (e.g. a correction).
        s.add(ManagerInteraction(tenant_id=TENANT, manager_id=first["manager_id"], interaction_type="business_call",
                                 occurred_at=at, outcome="wrong_person",
                                 created_at=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=5)))
        await s.commit()
    async with SessionLocal() as s:
        assert await call_list.follow_ups(s, tenant_id=TENANT, now=NOW) == []


def test_a_prefixed_international_number_is_the_national_one() -> None:
    from app.domain.erasure.service import phone_value

    assert phone_value("Tel. +49 30 1234567") == phone_value("030 1234567") == "0301234567"

