"""Activity tracking and per-consultant goals (ELI-15).

The ticket: "Jeder Consultant muss seine Tätigkeiten tracken und managen
können. Dabei soll es möglich sein, dass für jeden Consultant
unterschiedliche Ziele vorgegeben werden bzw. wir als Admins unsere Ziele
selbst festlegen können."

What these pin, in order of how badly they would hurt:

1. **A number nothing measures is never shown as a number.** There is no
   Contract entity and no LinkedIn integration, so two of the four KPIs in
   the design cannot be counted. A plausible-looking zero would be a lie a
   consultant gets measured against.
2. **A figure counts once, and stops counting when it is undone.** Saving a
   note twice is one call; un-ticking "Vorgestellt" removes the
   presentation. A KPI that only goes up is a KPI people game.
3. **Periods are calendar periods.** "This month" has to mean the same
   thing to the consultant and to whoever set the target.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from app.core.database import SessionLocal
from app.domain.activity import kpis, service
from app.domain.companies.models import Company
from app.domain.managers.models import Manager, ManagerInteraction

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.uuid4()
ANNA = "user_anna"
BEN = "user_ben"


async def _call(
    *,
    when: dt.datetime,
    actor: str | None = ANNA,
    kind: str = "business_call",
    tenant: uuid.UUID = TENANT,
) -> uuid.UUID:
    """A manager note — the row that IS the Business Call."""
    async with SessionLocal() as s:
        company = Company(tenant_id=tenant, name="Linde + Wiemann")
        s.add(company)
        await s.flush()
        manager = Manager(
            tenant_id=tenant, company_id=company.id, full_name="Jürgen Nothof"
        )
        s.add(manager)
        await s.flush()
        note = ManagerInteraction(
            tenant_id=tenant,
            manager_id=manager.id,
            interaction_type=kind,
            occurred_at=when,
            actor_user_id=actor,
            actor_name="Anna" if actor == ANNA else actor,
        )
        s.add(note)
        await s.commit()
        return note.id


async def _count(start: dt.datetime, end: dt.datetime, **kw) -> int:
    async with SessionLocal() as s:
        return await service.count(
            s, tenant_id=TENANT, counts=kpis.MANAGER_CALL, start=start, end=end, **kw
        )


WEEK = (dt.datetime(2026, 10, 19, tzinfo=dt.UTC), dt.datetime(2026, 10, 26, tzinfo=dt.UTC))


# ── periods ───────────────────────────────────────────────────────────────


def test_a_week_starts_on_monday() -> None:
    # A German work week does. A week starting Sunday would put Monday's
    # calls in the previous week's number.
    wednesday = dt.datetime(2026, 10, 21, 15, 0, tzinfo=dt.UTC)
    start, end = kpis.window("woche", wednesday)
    assert start == dt.datetime(2026, 10, 19, tzinfo=dt.UTC)  # Monday
    assert end == dt.datetime(2026, 10, 26, tzinfo=dt.UTC)


def test_a_month_is_the_calendar_month() -> None:
    start, end = kpis.window("monat", dt.datetime(2026, 10, 25, tzinfo=dt.UTC))
    assert start == dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
    assert end == dt.datetime(2026, 11, 1, tzinfo=dt.UTC)


def test_a_december_quarter_rolls_into_the_next_year() -> None:
    start, end = kpis.window("quartal", dt.datetime(2026, 12, 31, tzinfo=dt.UTC))
    assert start == dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
    assert end == dt.datetime(2027, 1, 1, tzinfo=dt.UTC)


def test_an_unknown_period_is_refused() -> None:
    with pytest.raises(ValueError):
        kpis.window("jahrzehnt", dt.datetime.now(dt.UTC))


# ── counting ──────────────────────────────────────────────────────────────
#
# There is no events table. Every count below is a query over the row that
# already records the fact, which is what makes these properties free rather
# than maintained: a deleted note cannot linger in a KPI it was never copied
# into.


async def test_a_saved_call_is_counted() -> None:
    await _call(when=dt.datetime(2026, 10, 20, tzinfo=dt.UTC))
    assert await _count(*WEEK) == 1


async def test_deleting_the_note_removes_the_call() -> None:
    """By construction, not by cleanup. This is the whole argument for
    counting the source row instead of copying it into an events table."""
    note_id = await _call(when=dt.datetime(2026, 10, 20, tzinfo=dt.UTC))
    async with SessionLocal() as s:
        await s.delete(await s.get(ManagerInteraction, note_id))
        await s.commit()
    assert await _count(*WEEK) == 0


async def test_moving_when_it_happened_moves_which_week_it_counts_in() -> None:
    # A call logged on Monday for last Friday belongs in last week.
    note_id = await _call(when=dt.datetime(2026, 10, 20, tzinfo=dt.UTC))
    assert await _count(*WEEK) == 1
    async with SessionLocal() as s:
        note = await s.get(ManagerInteraction, note_id)
        note.occurred_at = dt.datetime(2026, 10, 13, tzinfo=dt.UTC)
        await s.commit()
    assert await _count(*WEEK) == 0
    assert (
        await _count(
            dt.datetime(2026, 10, 12, tzinfo=dt.UTC),
            dt.datetime(2026, 10, 19, tzinfo=dt.UTC),
        )
        == 1
    )


@pytest.mark.parametrize("kind", ["na", "note", "message", "candidate_call", "meeting"])
async def test_only_a_call_with_a_manager_counts(kind) -> None:
    # "NA" is a call that did not connect; a candidate call is a different
    # conversation. Neither is a Business Call.
    await _call(when=dt.datetime(2026, 10, 20, tzinfo=dt.UTC), kind=kind)
    assert await _count(*WEEK) == 0


async def test_a_mandate_note_with_no_contact_is_not_a_call() -> None:
    # A briefing can be filed before the contact exists in the record. That
    # is not a call with anybody.
    async with SessionLocal() as s:
        s.add(
            ManagerInteraction(
                tenant_id=TENANT,
                manager_id=None,
                interaction_type="business_call",
                occurred_at=dt.datetime(2026, 10, 20, tzinfo=dt.UTC),
            )
        )
        await s.commit()
    assert await _count(*WEEK) == 0


async def test_each_consultant_is_counted_separately() -> None:
    at = dt.datetime(2026, 10, 20, tzinfo=dt.UTC)
    await _call(when=at, actor=ANNA)
    await _call(when=at, actor=ANNA)
    await _call(when=at, actor=BEN)
    assert await _count(*WEEK) == 3
    assert await _count(*WEEK, everyone=False, actor_user_id=ANNA) == 2
    assert await _count(*WEEK, everyone=False, actor_user_id=BEN) == 1


async def test_rows_with_no_author_are_their_own_bucket() -> None:
    # Imported history has no author, and hiding it would make the workspace
    # total look wrong against the sum of the consultants.
    at = dt.datetime(2026, 10, 20, tzinfo=dt.UTC)
    await _call(when=at, actor=None)
    await _call(when=at, actor=ANNA)
    assert await _count(*WEEK) == 2
    assert await _count(*WEEK, everyone=False, actor_user_id=None) == 1


async def test_one_workspace_cannot_count_anothers_activity() -> None:
    await _call(when=dt.datetime(2026, 10, 20, tzinfo=dt.UTC), tenant=OTHER)
    assert await _count(*WEEK) == 0


# ── targets ───────────────────────────────────────────────────────────────


async def test_a_consultant_inherits_the_workspace_target() -> None:
    async with SessionLocal() as s:
        await service.set_target(
            s, tenant_id=TENANT, kpi="business_calls", period="monat", value=100
        )
    async with SessionLocal() as s:
        panel = await service.tracking(
            s, tenant_id=TENANT, period="monat", everyone=False, actor_user_id=ANNA
        )
    calls = next(k for k in panel["kpis"] if k["key"] == "business_calls")
    assert calls["ziel"] == 100


async def test_a_consultants_own_target_wins() -> None:
    async with SessionLocal() as s:
        await service.set_target(
            s, tenant_id=TENANT, kpi="business_calls", period="monat", value=100
        )
        await service.set_target(
            s, tenant_id=TENANT, kpi="business_calls", period="monat",
            value=40, actor_user_id=ANNA,
        )
    async with SessionLocal() as s:
        mine = await service.tracking(
            s, tenant_id=TENANT, period="monat", everyone=False, actor_user_id=ANNA
        )
        theirs = await service.tracking(
            s, tenant_id=TENANT, period="monat", everyone=False, actor_user_id=BEN
        )
    assert next(k for k in mine["kpis"] if k["key"] == "business_calls")["ziel"] == 40
    assert next(k for k in theirs["kpis"] if k["key"] == "business_calls")["ziel"] == 100


async def test_setting_a_target_twice_updates_it() -> None:
    async with SessionLocal() as s:
        await service.set_target(
            s, tenant_id=TENANT, kpi="business_calls", period="woche", value=10
        )
        row = await service.set_target(
            s, tenant_id=TENANT, kpi="business_calls", period="woche", value=25
        )
    assert row.value == 25
    async with SessionLocal() as s:
        rows = [
            r
            for r in await service.targets(s, tenant_id=TENANT)
            if r.kpi == "business_calls" and r.period == "woche"
        ]
    assert len(rows) == 1


async def test_no_target_is_not_a_target_of_zero() -> None:
    # 0 / 0 would render as "achieved" for a KPI nobody has set.
    async with SessionLocal() as s:
        panel = await service.tracking(s, tenant_id=TENANT, period="quartal")
    assert all(k["ziel"] is None for k in panel["kpis"])


async def test_an_unknown_kpi_or_period_is_refused() -> None:
    async with SessionLocal() as s:
        with pytest.raises(ValueError):
            await service.set_target(
                s, tenant_id=TENANT, kpi="vibes", period="monat", value=1
            )
        with pytest.raises(ValueError):
            await service.set_target(
                s, tenant_id=TENANT, kpi="business_calls", period="jahr", value=1
            )


# ── what cannot be measured ───────────────────────────────────────────────


async def test_the_two_unmeasurable_kpis_show_no_number_and_say_why() -> None:
    """THE one that matters. There is no Contract entity and no LinkedIn
    integration, so these two cannot be counted — and a confident 0 next to
    a target is worse than a blank, because somebody gets measured on it."""
    async with SessionLocal() as s:
        panel = await service.tracking(s, tenant_id=TENANT, period="monat")
    for key in ("framework_contracts", "network_growth"):
        kpi = next(k for k in panel["kpis"] if k["key"] == key)
        assert kpi["available"] is False
        assert kpi["ist"] is None, "an unmeasurable KPI must not render as a count"
        assert kpi["unavailable_because"]


async def test_the_measurable_ones_are_measurable() -> None:
    async with SessionLocal() as s:
        panel = await service.tracking(s, tenant_id=TENANT, period="monat")
    for key in ("business_calls", "candidates_presented"):
        kpi = next(k for k in panel["kpis"] if k["key"] == key)
        assert kpi["available"] is True and isinstance(kpi["ist"], int)


# ── through the API, and from the write paths that feed it ────────────────


async def _client():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_saving_a_manager_note_counts_as_a_business_call() -> None:
    """End to end: nobody counts calls by hand — the note IS the event."""
    async with await _client() as client:
        company = (await client.post("/api/v1/companies", json={"name": "ACME AG"})).json()
        manager = (
            await client.post(
                "/api/v1/managers",
                json={"full_name": "Jürgen Nothof", "company_id": company["id"]},
            )
        ).json()
        before = (await client.get("/api/v1/activity/tracking?period=monat")).json()
        calls_before = next(
            k for k in before["kpis"] if k["key"] == "business_calls"
        )["ist"]

        posted = await client.post(
            f"/api/v1/managers/{manager['id']}/interactions",
            json={
                "interaction_type": "business_call",
                "occurred_at": dt.datetime.now(dt.UTC).isoformat(),
                "summary": "Erstkontakt",
            },
        )
        assert posted.status_code in (200, 201)

        after = (await client.get("/api/v1/activity/tracking?period=monat")).json()
    calls_after = next(k for k in after["kpis"] if k["key"] == "business_calls")["ist"]
    assert calls_after == calls_before + 1


async def test_a_note_that_is_not_a_call_is_not_counted() -> None:
    # "NA — nicht erreicht" is a call ATTEMPTED, not a call made, and a
    # plain note is not a conversation at all.
    async with await _client() as client:
        company = (await client.post("/api/v1/companies", json={"name": "Beta GmbH"})).json()
        manager = (
            await client.post(
                "/api/v1/managers",
                json={"full_name": "Maren Kaltenbach", "company_id": company["id"]},
            )
        ).json()
        before = next(
            k
            for k in (await client.get("/api/v1/activity/tracking?period=monat")).json()["kpis"]
            if k["key"] == "business_calls"
        )["ist"]
        for kind in ("na", "note", "message"):
            await client.post(
                f"/api/v1/managers/{manager['id']}/interactions",
                json={
                    "interaction_type": kind,
                    "occurred_at": dt.datetime.now(dt.UTC).isoformat(),
                },
            )
        after = next(
            k
            for k in (await client.get("/api/v1/activity/tracking?period=monat")).json()["kpis"]
            if k["key"] == "business_calls"
        )["ist"]
    assert after == before


async def test_the_endpoint_refuses_an_unknown_period() -> None:
    async with await _client() as client:
        assert (await client.get("/api/v1/activity/tracking?period=jahr")).status_code == 422


async def test_a_target_set_through_the_api_comes_back() -> None:
    async with await _client() as client:
        put = await client.put(
            "/api/v1/activity/targets",
            json={"kpi": "candidates_presented", "period": "monat", "value": 12},
        )
        assert put.status_code == 200
        panel = (await client.get("/api/v1/activity/tracking?period=monat")).json()
    assert next(
        k for k in panel["kpis"] if k["key"] == "candidates_presented"
    )["ziel"] == 12


async def test_consultants_lists_who_actually_did_something() -> None:
    # Read off the source tables, so somebody who has only ticked a process
    # step appears too — there is no roster to list instead.
    await _call(when=dt.datetime.now(dt.UTC), actor=ANNA)
    async with await _client() as client:
        rows = (await client.get("/api/v1/activity/consultants")).json()
    assert any(r["actor_user_id"] == ANNA for r in rows)



# ── presentations, counted off the step itself ────────────────────────────


async def _step(
    *,
    done_at: dt.datetime | None = None,
    scheduled_at: dt.datetime | None = None,
    outcome: str = "open",
    actor: str | None = ANNA,
    step_key: str = kpis.PRESENTED_STEP,
    active: bool = True,
) -> uuid.UUID:
    from app.domain.pipeline.models import ProcessStep

    async with SessionLocal() as s:
        row = ProcessStep(
            tenant_id=TENANT,
            application_id=uuid.uuid4(),
            step_key=step_key,
            position=0,
            active=active,
            done_at=done_at,
            scheduled_at=scheduled_at,
            outcome=outcome,
            actor_user_id=actor,
            actor_name="Anna" if actor == ANNA else actor,
        )
        s.add(row)
        await s.commit()
        return row.id


async def _presented(**kw) -> int:
    async with SessionLocal() as s:
        return await service.count(
            s,
            tenant_id=TENANT,
            counts=kpis.CANDIDATE_PRESENTED,
            start=WEEK[0],
            end=WEEK[1],
            **kw,
        )


async def test_a_ticked_presentation_counts() -> None:
    await _step(done_at=dt.datetime(2026, 10, 20, tzinfo=dt.UTC))
    assert await _presented() == 1


async def test_a_booked_presentation_counts_like_the_board_counts_it() -> None:
    # `derive_stage` treats a scheduled step as reached: the date is the
    # commitment. The KPI and the board must not tell different stories.
    await _step(scheduled_at=dt.datetime(2026, 10, 20, 9, 0, tzinfo=dt.UTC))
    assert await _presented() == 1


async def test_an_empty_step_does_not_count() -> None:
    await _step()
    assert await _presented() == 0


async def test_un_ticking_removes_it_from_the_count() -> None:
    """A KPI that only ever goes up is a KPI people game."""
    from app.domain.pipeline.models import ProcessStep

    step_id = await _step(done_at=dt.datetime(2026, 10, 20, tzinfo=dt.UTC))
    assert await _presented() == 1
    async with SessionLocal() as s:
        row = await s.get(ProcessStep, step_id)
        row.done_at = None
        await s.commit()
    assert await _presented() == 0


async def test_a_step_removed_from_the_process_does_not_count() -> None:
    await _step(done_at=dt.datetime(2026, 10, 20, tzinfo=dt.UTC), active=False)
    assert await _presented() == 0


async def test_another_step_is_not_a_presentation() -> None:
    await _step(done_at=dt.datetime(2026, 10, 20, tzinfo=dt.UTC), step_key="vertrag")
    assert await _presented() == 0


async def test_presentations_split_by_consultant_too() -> None:
    at = dt.datetime(2026, 10, 20, tzinfo=dt.UTC)
    await _step(done_at=at, actor=ANNA)
    await _step(done_at=at, actor=BEN)
    assert await _presented() == 2
    assert await _presented(everyone=False, actor_user_id=ANNA) == 1
