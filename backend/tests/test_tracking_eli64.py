"""Tracking (ELI-64): Umsatz, Business Development and the Prozess funnel.

The ticket names three groups: Business (Umsatz against a monthly goal —
shared by two people, or one person's from a start date), Business
Development (Kontaktpunkte, Business Calls/Meetings, Leads, Rahmenverträge,
Mandate) and Prozess (the ratio and the days between each step from
Vorgestellt to Deal).

What these pin:

1. **Every number is counted live from the row that records it** — a fee on
   the deal, a date on the company, a manager created as a lead — and
   follows the record when it changes.
2. **A goal can belong to a group.** "Bei Jonas und mir gilt der Umsatz
   zusammen" is one goal measured on two people's deals.
3. **A goal can start later.** Xaver's goal starts 1 January; before that
   it is not a goal of zero, it is no goal.
4. **The funnel shows n/m and blanks, never a misleading 0.**
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from app.core.context import ActorRef, current_actor_var
from app.core.database import SessionLocal
from app.domain.activity import kpis, service
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager, ManagerInteraction
from app.domain.pipeline.models import Application, ProcessStep

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
JONAS = "user_jonas"
TOBIAS = "user_tobias"
XAVER = "user_xaver"

NOV = dt.datetime(2026, 11, 15, tzinfo=dt.UTC)
NOV_WINDOW = kpis.window("monat", NOV)


def _kpi(panel: dict, key: str) -> dict:
    return next(k for k in panel["kpis"] if k["key"] == key)


async def _company(name: str = "ACME AG") -> uuid.UUID:
    async with SessionLocal() as s:
        row = Company(tenant_id=TENANT, name=name)
        s.add(row)
        await s.commit()
        return row.id


async def _application() -> uuid.UUID:
    """An application with a real candidate and job behind it."""
    from app.domain.candidates.models import Candidate

    async with SessionLocal() as s:
        company = Company(tenant_id=TENANT, name="Kunde GmbH")
        s.add(company)
        await s.flush()
        job = Job(tenant_id=TENANT, title="CFO", client_company_id=company.id)
        cand = Candidate(tenant_id=TENANT, full_name="Kim Beispiel")
        s.add_all([job, cand])
        await s.flush()
        app = Application(tenant_id=TENANT, candidate_id=cand.id, job_id=job.id)
        s.add(app)
        await s.commit()
        return app.id


async def _step(
    application_id: uuid.UUID,
    key: str,
    when: dt.datetime | None,
    *,
    actor: str | None = JONAS,
    outcome: str = "open",
    label: str | None = None,
) -> None:
    async with SessionLocal() as s:
        s.add(
            ProcessStep(
                tenant_id=TENANT,
                application_id=application_id,
                step_key=key,
                position=0,
                done_at=when,
                outcome=outcome,
                actor_user_id=actor,
                actor_name=actor,
                label=label,
            )
        )
        await s.commit()


async def _deal(fee: int | None, when: dt.datetime, actor: str | None = JONAS) -> uuid.UUID:
    app_id = await _application()
    async with SessionLocal() as s:
        app = await s.get(Application, app_id)
        app.fee_eur = fee
        await s.commit()
    await _step(app_id, "vertrag", when, actor=actor)
    return app_id


async def _panel(**kw) -> dict:
    async with SessionLocal() as s:
        return await service.tracking(s, tenant_id=TENANT, period="monat", at=NOV, **kw)


# ── Umsatz ────────────────────────────────────────────────────────────────


async def test_revenue_is_the_fee_of_deals_closed_in_the_period() -> None:
    await _deal(12_000, dt.datetime(2026, 11, 3, tzinfo=dt.UTC))
    await _deal(8_000, dt.datetime(2026, 11, 20, tzinfo=dt.UTC), actor=TOBIAS)
    # October's deal belongs to October.
    await _deal(5_000, dt.datetime(2026, 10, 30, tzinfo=dt.UTC))
    panel = await _panel()
    assert _kpi(panel, "revenue")["ist"] == 20_000
    assert _kpi(panel, "revenue")["unit"] == "eur"
    assert (await _panel(everyone=False, actor_user_id=TOBIAS))["kpis"][0]["ist"] == 8_000


async def test_a_deal_with_no_fee_entered_adds_nothing_and_says_so() -> None:
    await _deal(None, dt.datetime(2026, 11, 3, tzinfo=dt.UTC))
    revenue = _kpi(await _panel(), "revenue")
    assert revenue["ist"] == 0
    # The figure is honest about what it could not add up.
    assert revenue["missing"] == 1


async def test_the_fee_is_entered_on_the_vertrag_step() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    app_id = await _application()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.patch(
            f"/api/v1/pipeline/applications/{app_id}/steps/vertrag",
            json={"done_at": dt.datetime.now(dt.UTC).isoformat(), "fee_eur": 25_000},
        )
        assert r.status_code == 200, r.text
        # A fee on any other step is refused: Umsatz is a closed deal.
        bad = await c.patch(
            f"/api/v1/pipeline/applications/{app_id}/steps/offer",
            json={"fee_eur": 1},
        )
        assert bad.status_code == 422
        panel = (await c.get("/api/v1/activity/tracking?period=monat")).json()
        processes = (await c.get("/api/v1/pipeline/processes")).json()
    assert _kpi(panel, "revenue")["ist"] == 25_000
    assert processes[0]["candidates"][0]["fee_eur"] == 25_000


# ── Business Development ──────────────────────────────────────────────────


async def _note(kind: str, when: dt.datetime = NOV, actor: str | None = JONAS) -> None:
    async with SessionLocal() as s:
        company = Company(tenant_id=TENANT, name="X")
        s.add(company)
        await s.flush()
        m = Manager(tenant_id=TENANT, company_id=company.id, full_name="Frau Y")
        s.add(m)
        await s.flush()
        s.add(
            ManagerInteraction(
                tenant_id=TENANT,
                manager_id=m.id,
                interaction_type=kind,
                occurred_at=when,
                actor_user_id=actor,
            )
        )
        await s.commit()


async def test_contact_points_count_every_contact_but_not_an_unanswered_call() -> None:
    for kind in ("business_call", "meeting", "message", "profiles_sent", "BD Call"):
        await _note(kind)
    for kind in ("na", "N/A", "note"):
        await _note(kind)
    assert _kpi(await _panel(), "contact_points")["ist"] == 5


async def test_business_calls_include_meetings_and_their_legacy_spelling() -> None:
    for kind in ("business_call", "client_call", "conversation", "meeting", "Meeting Notes", "BD Call"):
        await _note(kind)
    for kind in ("message", "na", "candidate_call", "profiles_sent"):
        await _note(kind)
    calls = _kpi(await _panel(), "business_calls")
    assert calls["ist"] == 6
    assert calls["label"] == "Business Call oder Meeting"


async def _manager(stage: str, *, created: dt.datetime = NOV, by: str | None = JONAS, promoted: bool = False) -> None:
    token = current_actor_var.set(ActorRef(user_id=by, name=by or "")) if by else None
    try:
        async with SessionLocal() as s:
            company = Company(tenant_id=TENANT, name="Z")
            s.add(company)
            await s.flush()
            s.add(
                Manager(
                    tenant_id=TENANT,
                    company_id=company.id,
                    full_name="Lead",
                    stage=stage,
                    created_at=created,
                    promoted_at=created if promoted else None,
                )
            )
            await s.commit()
    finally:
        if token is not None:
            current_actor_var.reset(token)


async def test_leads_added_are_managers_created_as_leads() -> None:
    await _manager("bus_dev")
    # Promoted to manager since: it was still added as a lead.
    await _manager("manager", promoted=True, by=TOBIAS)
    # A manager entered as a manager is not a lead.
    await _manager("manager")
    await _manager("bus_dev", created=dt.datetime(2026, 10, 1, tzinfo=dt.UTC))
    assert _kpi(await _panel(), "leads_added")["ist"] == 2
    mine = await _panel(everyone=False, actor_user_id=TOBIAS)
    assert _kpi(mine, "leads_added")["ist"] == 1


async def test_the_creator_is_recorded_from_the_request() -> None:
    token = current_actor_var.set(ActorRef(user_id=XAVER, name="Xaver"))
    try:
        await _manager("bus_dev", by=None)
    finally:
        current_actor_var.reset(token)
    async with SessionLocal() as s:
        from sqlalchemy import select

        row = (await s.execute(select(Manager))).scalars().one()
    assert row.created_by_user_id == XAVER
    assert row.created_by_name == "Xaver"


async def test_mandates_added_count_own_jobs_not_imports() -> None:
    token = current_actor_var.set(ActorRef(user_id=JONAS, name="Jonas"))
    try:
        async with SessionLocal() as s:
            s.add(Job(tenant_id=TENANT, title="A", created_at=NOV))
            s.add(Job(tenant_id=TENANT, title="B", created_at=NOV, external_source="aifind", external_id="1"))
            await s.commit()
    finally:
        current_actor_var.reset(token)
    panel = await _panel()
    assert _kpi(panel, "mandates_added")["ist"] == 1
    assert _kpi(await _panel(everyone=False, actor_user_id=JONAS), "mandates_added")["ist"] == 1


async def test_a_framework_contract_is_a_dated_mark_on_the_company() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    company_id = await _company()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        put = await c.put(
            f"/api/v1/companies/{company_id}/framework-contract",
            json={"signed_on": dt.date.today().isoformat()},
        )
        assert put.status_code == 200, put.text
        assert put.json()["company"]["framework_contract_on"] == dt.date.today().isoformat()
        panel = (await c.get("/api/v1/activity/tracking?period=monat")).json()
        assert _kpi(panel, "framework_contracts")["available"] is True
        assert _kpi(panel, "framework_contracts")["ist"] == 1

        gone = await c.put(
            f"/api/v1/companies/{company_id}/framework-contract", json={"signed_on": None}
        )
        assert gone.status_code == 200
        assert gone.json()["company"]["framework_contract_on"] is None
        panel = (await c.get("/api/v1/activity/tracking?period=monat")).json()
    assert _kpi(panel, "framework_contracts")["ist"] == 0


def test_every_kpi_names_its_source() -> None:
    for kpi in kpis.KPIS:
        assert kpi.source, kpi.key
        assert kpi.group in ("business", "bd", "prozess"), kpi.key


# ── goals: shared and dated ───────────────────────────────────────────────


async def test_a_shared_goal_is_measured_on_everybody_in_it() -> None:
    await _deal(12_000, dt.datetime(2026, 11, 3, tzinfo=dt.UTC), actor=JONAS)
    await _deal(9_000, dt.datetime(2026, 11, 4, tzinfo=dt.UTC), actor=TOBIAS)
    await _deal(7_000, dt.datetime(2026, 11, 5, tzinfo=dt.UTC), actor=XAVER)
    async with SessionLocal() as s:
        await service.set_target(
            s, tenant_id=TENANT, kpi="revenue", period="monat", value=30_000,
            members=[JONAS, TOBIAS], label="Jonas & Tobias",
        )
    goals = (await _panel())["goals"]
    assert len(goals) == 1
    goal = goals[0]
    assert goal["label"] == "Jonas & Tobias"
    assert goal["ziel"] == 30_000
    assert goal["ist"] == 21_000  # Xaver's deal is not theirs


async def test_a_goal_with_a_start_date_is_no_goal_before_it() -> None:
    await _deal(4_000, dt.datetime(2026, 12, 10, tzinfo=dt.UTC), actor=XAVER)
    await _deal(6_000, dt.datetime(2027, 1, 10, tzinfo=dt.UTC), actor=XAVER)
    async with SessionLocal() as s:
        await service.set_target(
            s, tenant_id=TENANT, kpi="revenue", period="monat", value=15_000,
            actor_user_id=XAVER, valid_from=dt.date(2027, 1, 1),
        )
        december = await service.tracking(
            s, tenant_id=TENANT, period="monat", at=dt.datetime(2026, 12, 15, tzinfo=dt.UTC)
        )
        january = await service.tracking(
            s, tenant_id=TENANT, period="monat", at=dt.datetime(2027, 1, 15, tzinfo=dt.UTC)
        )
        xaver_dec = await service.tracking(
            s, tenant_id=TENANT, period="monat", at=dt.datetime(2026, 12, 15, tzinfo=dt.UTC),
            everyone=False, actor_user_id=XAVER,
        )
    assert december["goals"][0]["ziel"] is None
    assert december["goals"][0]["valid_from"] == dt.date(2027, 1, 1)
    assert january["goals"][0]["ziel"] == 15_000
    assert january["goals"][0]["ist"] == 6_000
    assert _kpi(xaver_dec, "revenue")["ziel"] is None


async def test_two_shared_goals_on_the_same_kpi_are_two_rows_and_a_resave_updates() -> None:
    async with SessionLocal() as s:
        a = await service.set_target(
            s, tenant_id=TENANT, kpi="revenue", period="monat", value=30_000,
            members=[TOBIAS, JONAS], label="Jonas & Tobias",
        )
        again = await service.set_target(
            s, tenant_id=TENANT, kpi="revenue", period="monat", value=32_000,
            members=[JONAS, TOBIAS], label="J+T",
        )
        await service.set_target(
            s, tenant_id=TENANT, kpi="revenue", period="monat", value=15_000,
            actor_user_id=XAVER,
        )
        rows = await service.targets(s, tenant_id=TENANT)
    assert again.id == a.id and again.value == 32_000 and again.label == "J+T"
    assert len(rows) == 2


async def test_a_goal_can_be_deleted_by_an_admin() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        put = await c.put(
            "/api/v1/activity/targets",
            json={
                "kpi": "revenue", "period": "monat", "value": 30000,
                "members": [JONAS, TOBIAS], "label": "Jonas & Tobias",
                "valid_from": "2026-11-01",
            },
        )
        assert put.status_code == 200, put.text
        body = put.json()
        assert body["members"] == [JONAS, TOBIAS] and body["valid_from"] == "2026-11-01"
        gone = await c.delete(f"/api/v1/activity/targets/{body['id']}")
        assert gone.status_code == 204
        assert (await c.get("/api/v1/activity/targets")).json() == []


async def test_a_goal_on_a_kpi_that_cannot_be_counted_is_refused() -> None:
    async with SessionLocal() as s:
        with pytest.raises(ValueError):
            await service.set_target(s, tenant_id=TENANT, kpi="nope", period="monat", value=1)
        with pytest.raises(ValueError):
            # A group of one is an individual goal with extra steps.
            await service.set_target(
                s, tenant_id=TENANT, kpi="revenue", period="monat", value=1, members=[JONAS]
            )


# ── Prozess: ratio and days between steps ─────────────────────────────────


def _d(day: int, month: int = 11) -> dt.datetime:
    return dt.datetime(2026, month, day, tzinfo=dt.UTC)


async def test_the_funnel_shows_ratio_and_median_days_per_transition() -> None:
    # Three candidates presented in November.
    a = await _application()
    await _step(a, "vorgestellt", _d(1))
    await _step(a, "interview", _d(5))
    await _step(a, "interviewtermin_2", _d(12))
    await _step(a, "finaltermin", _d(20))
    await _step(a, "offer", _d(25))
    await _step(a, "vertrag", _d(28))

    b = await _application()
    await _step(b, "vorgestellt", _d(2))
    await _step(b, "interview", _d(12))
    # A custom step named as a second interview counts as one.
    await _step(b, "custom_2-interview", _d(19), label="2. Interview")

    c = await _application()
    await _step(c, "vorgestellt", _d(3))

    async with SessionLocal() as s:
        funnel = await service.process_funnel(s, tenant_id=TENANT, start=NOV_WINDOW[0], end=NOV_WINDOW[1])
    by = {(f["from_key"], f["to_key"]): f for f in funnel}
    first = by[("vorgestellt", "interview_1")]
    assert (first["reached"], first["of"]) == (2, 3)
    assert first["ratio"] == pytest.approx(2 / 3)
    assert first["median_days"] == pytest.approx(7.0)  # 4 and 10 days
    second = by[("interview_1", "interview_2")]
    assert (second["reached"], second["of"]) == (2, 2)
    assert second["median_days"] == pytest.approx(7.0)
    final = by[("interview_2", "final")]
    assert (final["reached"], final["of"]) == (1, 2)
    deal = by[("offer", "deal")]
    assert (deal["reached"], deal["of"]) == (1, 1)
    assert deal["median_days"] == pytest.approx(3.0)
    assert len(funnel) == 5


async def test_a_transition_with_nobody_in_it_is_blank_not_zero() -> None:
    a = await _application()
    await _step(a, "vorgestellt", _d(1))
    async with SessionLocal() as s:
        funnel = await service.process_funnel(s, tenant_id=TENANT, start=NOV_WINDOW[0], end=NOV_WINDOW[1])
    deal = next(f for f in funnel if f["to_key"] == "deal")
    assert deal["of"] == 0 and deal["ratio"] is None and deal["median_days"] is None
    first = funnel[0]
    assert (first["reached"], first["of"]) == (0, 1)
    assert first["ratio"] == 0 and first["median_days"] is None


async def test_the_funnel_counts_by_who_made_the_first_step_and_ignores_removed_steps() -> None:
    a = await _application()
    await _step(a, "vorgestellt", _d(1), actor=JONAS)
    await _step(a, "interview", _d(4), actor=TOBIAS)
    b = await _application()
    await _step(b, "vorgestellt", _d(1), actor=TOBIAS)
    async with SessionLocal() as s:
        row = ProcessStep(
            tenant_id=TENANT, application_id=b, step_key="interview", position=0,
            done_at=_d(3), active=False,
        )
        s.add(row)
        await s.commit()
        mine = await service.process_funnel(
            s, tenant_id=TENANT, start=NOV_WINDOW[0], end=NOV_WINDOW[1],
            everyone=False, actor_user_id=JONAS,
        )
        theirs = await service.process_funnel(
            s, tenant_id=TENANT, start=NOV_WINDOW[0], end=NOV_WINDOW[1],
            everyone=False, actor_user_id=TOBIAS,
        )
    assert (mine[0]["reached"], mine[0]["of"]) == (1, 1)
    assert (theirs[0]["reached"], theirs[0]["of"]) == (0, 1)


async def test_the_tracking_endpoint_carries_the_funnel() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        body = (await c.get("/api/v1/activity/tracking?period=quartal")).json()
    assert [f["to_key"] for f in body["funnel"]] == [
        "interview_1", "interview_2", "final", "offer", "deal",
    ]
    assert body["funnel"][0]["source"]


# ── Cockpit tiles, per person ─────────────────────────────────────────────


async def test_cockpit_tiles_default_and_are_saved_per_person() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        first = (await c.get("/api/v1/activity/preferences")).json()
        assert first["tiles"] == ["revenue", "business_calls", "leads_added"]
        assert first["saved"] is False
        put = await c.put(
            "/api/v1/activity/preferences", json={"tiles": ["process", "contact_points"]}
        )
        assert put.status_code == 200, put.text
        again = (await c.get("/api/v1/activity/preferences")).json()
        assert again == {"tiles": ["process", "contact_points"], "saved": True}
        bad = await c.put("/api/v1/activity/preferences", json={"tiles": ["nope"]})
        assert bad.status_code == 422
        # An empty Cockpit is a choice too.
        await c.put("/api/v1/activity/preferences", json={"tiles": []})
        assert (await c.get("/api/v1/activity/preferences")).json()["tiles"] == []
