"""Team-Übersicht (ELI-74): every employee side by side, against their goals.

The ticket: "Ich als Admin muss das Tracking der einzelnen Mitarbeiter
überwachen können." Switching person by person existed (ELI-64); this is the
overview an admin reads without clicking through everybody.

What these pin:

1. **Each cell is the same number the person's own panel shows** — it is
   counted by the same queries, grouped by author, not by a second formula.
2. **Somebody with nothing recorded is a row of zeros, not missing.** The
   browser sends the workspace's member list; a member it names who has no
   activity still gets a row.
3. **A goal is the person's own, else the Team-Standard** — and a shared goal
   is a row of its own for the group, never folded into one person's quota.
4. **Admins only**, and one workspace never sees another's people.
"""

from __future__ import annotations

import datetime as dt
import uuid

from httpx import ASGITransport, AsyncClient

from app.core.auth import RECRUITER, Actor, get_current_actor
from app.core.config import settings
from app.core.context import ActorRef, current_actor_var
from app.core.database import SessionLocal
from app.domain.activity import kpis, service
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager, ManagerInteraction
from app.domain.pipeline.models import Application, ProcessStep

TENANT = settings.default_tenant_id
OTHER = uuid.uuid4()
JONAS = "user_jonas"
TOBIAS = "user_tobias"
XAVER = "user_xaver"
STRANGER = "user_stranger"

NOV = dt.datetime(2026, 11, 15, tzinfo=dt.UTC)
TEAM_KPIS = [k.key for k in kpis.KPIS if k.group in ("business", "bd")]


async def _note(actor: str | None, kind: str = "business_call", *, tenant: uuid.UUID = TENANT) -> None:
    async with SessionLocal() as s:
        company = Company(tenant_id=tenant, name="ACME")
        s.add(company)
        await s.flush()
        manager = Manager(tenant_id=tenant, company_id=company.id, full_name="M")
        s.add(manager)
        await s.flush()
        s.add(
            ManagerInteraction(
                tenant_id=tenant,
                manager_id=manager.id,
                interaction_type=kind,
                occurred_at=NOV,
                actor_user_id=actor,
                actor_name=actor,
            )
        )
        await s.commit()


async def _deal(fee: int | None, actor: str) -> None:
    from app.domain.candidates.models import Candidate

    async with SessionLocal() as s:
        company = Company(tenant_id=TENANT, name="Kunde")
        s.add(company)
        await s.flush()
        job = Job(tenant_id=TENANT, title="CFO", client_company_id=company.id)
        cand = Candidate(tenant_id=TENANT, full_name="Kim")
        s.add_all([job, cand])
        await s.flush()
        app = Application(tenant_id=TENANT, candidate_id=cand.id, job_id=job.id, fee_eur=fee)
        s.add(app)
        await s.flush()
        s.add(
            ProcessStep(
                tenant_id=TENANT,
                application_id=app.id,
                step_key="vertrag",
                position=0,
                done_at=dt.datetime(2026, 11, 3, tzinfo=dt.UTC),
                actor_user_id=actor,
                actor_name=actor,
            )
        )
        await s.commit()


async def _lead(by: str) -> None:
    token = current_actor_var.set(ActorRef(user_id=by, name=by))
    try:
        async with SessionLocal() as s:
            company = Company(tenant_id=TENANT, name="Z")
            s.add(company)
            await s.flush()
            s.add(
                Manager(
                    tenant_id=TENANT, company_id=company.id, full_name="Lead",
                    stage="bus_dev", created_at=NOV,
                )
            )
            await s.commit()
    finally:
        current_actor_var.reset(token)


async def _team(members: list[str] | None = None, tenant: uuid.UUID = TENANT) -> dict:
    async with SessionLocal() as s:
        return await service.team(
            s, tenant_id=tenant, period="monat", at=NOV, members=members or []
        )


def _row(team: dict, who: str | None) -> dict:
    return next(r for r in team["rows"] if r["kind"] != "group" and r["actor_user_id"] == who)


def _cell(row: dict, key: str) -> dict:
    return next(c for c in row["cells"] if c["key"] == key)


async def _seed() -> None:
    await _deal(12_000, JONAS)
    await _deal(None, JONAS)
    await _deal(8_000, TOBIAS)
    await _note(JONAS)
    await _note(JONAS, "meeting")
    await _note(TOBIAS, "message")
    await _note(TOBIAS, "na")  # not a contact
    await _note(None)  # imported, nobody recorded
    await _lead(TOBIAS)


async def test_every_cell_is_the_number_the_persons_own_panel_shows() -> None:
    await _seed()
    team = await _team()
    assert [k["key"] for k in team["kpis"]] == TEAM_KPIS
    for who in (JONAS, TOBIAS, None):
        async with SessionLocal() as s:
            own = await service.tracking(
                s, tenant_id=TENANT, period="monat", at=NOV,
                everyone=False, actor_user_id=who,
            )
        row = _row(team, who)
        for kpi in own["kpis"]:
            if kpi["key"] not in TEAM_KPIS:
                continue
            cell = _cell(row, kpi["key"])
            assert cell["ist"] == kpi["ist"], (who, kpi["key"])
            assert cell["missing"] == kpi["missing"], (who, kpi["key"])
    jonas = _row(team, JONAS)
    assert _cell(jonas, "revenue")["ist"] == 12_000
    assert _cell(jonas, "revenue")["missing"] == 1
    assert _cell(jonas, "business_calls")["ist"] == 2
    assert _cell(_row(team, TOBIAS), "leads_added")["ist"] == 1
    assert _cell(_row(team, TOBIAS), "contact_points")["ist"] == 1


async def test_a_member_with_nothing_recorded_is_a_row_of_zeros() -> None:
    await _note(JONAS)
    team = await _team(members=[JONAS, XAVER])
    xaver = _row(team, XAVER)
    assert xaver["kind"] == "person"
    assert {c["key"]: c["ist"] for c in xaver["cells"]} == dict.fromkeys(TEAM_KPIS, 0)
    # Somebody with activity in the record is listed without being sent.
    await _note(TOBIAS)
    assert _row(await _team(), TOBIAS)["kind"] == "person"


async def test_the_unattributed_bucket_shows_only_when_it_has_something() -> None:
    await _note(JONAS)
    assert all(r["kind"] != "unassigned" for r in (await _team())["rows"])
    await _note(None)
    row = _row(await _team(), None)
    assert row["kind"] == "unassigned"
    # Nobody's goal applies to nobody.
    assert all(c["ziel"] is None for c in row["cells"])


async def test_a_goal_is_the_persons_own_else_the_team_default() -> None:
    async with SessionLocal() as s:
        await service.set_target(s, tenant_id=TENANT, kpi="business_calls", period="monat", value=10)
        await service.set_target(
            s, tenant_id=TENANT, kpi="business_calls", period="monat", value=4, actor_user_id=JONAS
        )
        # Another period's goal does not apply to the month.
        await service.set_target(
            s, tenant_id=TENANT, kpi="leads_added", period="woche", value=3, actor_user_id=JONAS
        )
    await _note(JONAS)
    team = await _team(members=[JONAS, XAVER])
    jonas = _cell(_row(team, JONAS), "business_calls")
    assert (jonas["ist"], jonas["ziel"], jonas["ziel_from"]) == (1, 4, "own")
    xaver = _cell(_row(team, XAVER), "business_calls")
    assert (xaver["ist"], xaver["ziel"], xaver["ziel_from"]) == (0, 10, "team")
    leads = _cell(_row(team, JONAS), "leads_added")
    assert (leads["ziel"], leads["ziel_from"]) == (None, None)


async def test_a_shared_goal_is_a_row_for_the_group_not_a_persons_quota() -> None:
    await _deal(12_000, JONAS)
    await _deal(8_000, TOBIAS)
    async with SessionLocal() as s:
        await service.set_target(
            s, tenant_id=TENANT, kpi="revenue", period="monat", value=40_000,
            members=[JONAS, TOBIAS], label="Jonas & Tobias",
        )
    team = await _team()
    groups = [r for r in team["rows"] if r["kind"] == "group"]
    assert len(groups) == 1
    group = groups[0]
    assert group["members"] == [JONAS, TOBIAS] and group["name"] == "Jonas & Tobias"
    revenue = _cell(group, "revenue")
    assert (revenue["ist"], revenue["ziel"], revenue["ziel_from"]) == (20_000, 40_000, "shared")
    # The group's goal is not Jonas's own goal.
    assert _cell(_row(team, JONAS), "revenue")["ziel"] is None
    # A KPI the group has no goal for is still counted, with no goal.
    assert _cell(group, "business_calls")["ziel"] is None


async def test_one_workspace_never_sees_anothers_people() -> None:
    await _note(JONAS)
    await _note(STRANGER, tenant=OTHER)
    team = await _team()
    ids = {r["actor_user_id"] for r in team["rows"]}
    assert STRANGER not in ids and JONAS in ids
    # Even when the browser names somebody from another workspace, it only
    # gets this workspace's record for them — which is nothing.
    named = _row(await _team(members=[STRANGER]), STRANGER)
    assert all(c["ist"] == 0 for c in named["cells"])
    other = await _team(tenant=OTHER)
    assert {r["actor_user_id"] for r in other["rows"]} == {STRANGER}


async def test_the_endpoint_returns_the_overview_to_an_admin() -> None:
    from app.main import app

    await _note(JONAS)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        res = await c.get(
            "/api/v1/activity/tracking/team",
            params={"period": "monat", "members": [JONAS, XAVER]},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert {r["actor_user_id"] for r in body["rows"]} >= {JONAS, XAVER}
        bad = await c.get("/api/v1/activity/tracking/team", params={"period": "jahr"})
        assert bad.status_code == 422


async def test_a_recruiter_gets_403() -> None:
    from app.main import app

    app.dependency_overrides[get_current_actor] = lambda: Actor(
        tenant_id=TENANT, user_id="u_rec", name="R", role=RECRUITER, role_known=True,
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            res = await c.get("/api/v1/activity/tracking/team", params={"period": "monat"})
            # The per-person view stays open to them, as before.
            own = await c.get("/api/v1/activity/tracking", params={"period": "monat", "who": "u_rec"})
    finally:
        app.dependency_overrides.clear()
    assert res.status_code == 403
    assert own.status_code == 200
