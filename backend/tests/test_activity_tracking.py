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
from sqlalchemy import select

from app.core.database import SessionLocal
from app.domain.activity import kpis, service
from app.domain.activity.models import ActivityEvent

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.uuid4()
ANNA = "user_anna"
BEN = "user_ben"


async def _event(
    *,
    when: dt.datetime,
    actor: str | None = ANNA,
    event_type: str = kpis.MANAGER_CALL,
    tenant: uuid.UUID = TENANT,
    ref: uuid.UUID | None = None,
) -> uuid.UUID:
    ref = ref or uuid.uuid4()
    async with SessionLocal() as s:
        await service.record(
            s,
            tenant_id=tenant,
            event_type=event_type,
            occurred_at=when,
            ref_type="manager_interaction",
            ref_id=ref,
            actor_user_id=actor,
            actor_name="Anna" if actor == ANNA else actor,
        )
        await s.commit()
    return ref


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


async def test_an_event_is_counted_once_however_often_it_is_saved() -> None:
    # Editing a note must not invent a second call.
    ref = uuid.uuid4()
    at = dt.datetime(2026, 10, 20, 10, 0, tzinfo=dt.UTC)
    await _event(when=at, ref=ref)
    await _event(when=at, ref=ref)
    async with SessionLocal() as s:
        assert (
            await service.count(
                s,
                tenant_id=TENANT,
                event_type=kpis.MANAGER_CALL,
                start=dt.datetime(2026, 10, 19, tzinfo=dt.UTC),
                end=dt.datetime(2026, 10, 26, tzinfo=dt.UTC),
            )
            == 1
        )


async def test_moving_when_it_happened_moves_which_week_it_counts_in() -> None:
    # A call logged on Monday for last Friday belongs in last week.
    ref = uuid.uuid4()
    await _event(when=dt.datetime(2026, 10, 20, tzinfo=dt.UTC), ref=ref)
    await _event(when=dt.datetime(2026, 10, 13, tzinfo=dt.UTC), ref=ref)
    async with SessionLocal() as s:
        this_week = await service.count(
            s, tenant_id=TENANT, event_type=kpis.MANAGER_CALL,
            start=dt.datetime(2026, 10, 19, tzinfo=dt.UTC),
            end=dt.datetime(2026, 10, 26, tzinfo=dt.UTC),
        )
        last_week = await service.count(
            s, tenant_id=TENANT, event_type=kpis.MANAGER_CALL,
            start=dt.datetime(2026, 10, 12, tzinfo=dt.UTC),
            end=dt.datetime(2026, 10, 19, tzinfo=dt.UTC),
        )
    assert (this_week, last_week) == (0, 1)


async def test_undoing_a_step_removes_the_event() -> None:
    ref = await _event(
        when=dt.datetime(2026, 10, 20, tzinfo=dt.UTC),
        event_type=kpis.CANDIDATE_PRESENTED,
    )
    async with SessionLocal() as s:
        await service.forget(
            s, tenant_id=TENANT, event_type=kpis.CANDIDATE_PRESENTED, ref_id=ref
        )
        await s.commit()
        assert (
            await service.count(
                s, tenant_id=TENANT, event_type=kpis.CANDIDATE_PRESENTED,
                start=dt.datetime(2026, 10, 19, tzinfo=dt.UTC),
                end=dt.datetime(2026, 10, 26, tzinfo=dt.UTC),
            )
            == 0
        )


async def test_the_first_author_keeps_the_event() -> None:
    # Ben editing Anna's note does not make it Ben's call.
    ref = uuid.uuid4()
    at = dt.datetime(2026, 10, 20, tzinfo=dt.UTC)
    await _event(when=at, ref=ref, actor=ANNA)
    await _event(when=at, ref=ref, actor=BEN)
    async with SessionLocal() as s:
        row = await s.scalar(select(ActivityEvent).where(ActivityEvent.ref_id == ref))
    assert row is not None and row.actor_user_id == ANNA


async def test_an_unattributed_event_adopts_the_first_author_it_gets() -> None:
    # The backfill writes history with no author; the first person to touch
    # that row afterwards is a better answer than nobody.
    ref = uuid.uuid4()
    at = dt.datetime(2026, 10, 20, tzinfo=dt.UTC)
    await _event(when=at, ref=ref, actor=None)
    await _event(when=at, ref=ref, actor=BEN)
    async with SessionLocal() as s:
        row = await s.scalar(select(ActivityEvent).where(ActivityEvent.ref_id == ref))
    assert row is not None and row.actor_user_id == BEN


async def test_one_workspace_cannot_count_anothers_activity() -> None:
    at = dt.datetime(2026, 10, 20, tzinfo=dt.UTC)
    await _event(when=at, tenant=OTHER)
    async with SessionLocal() as s:
        assert (
            await service.count(
                s, tenant_id=TENANT, event_type=kpis.MANAGER_CALL,
                start=dt.datetime(2026, 10, 19, tzinfo=dt.UTC),
                end=dt.datetime(2026, 10, 26, tzinfo=dt.UTC),
            )
            == 0
        )


async def test_an_unknown_event_type_is_refused() -> None:
    async with SessionLocal() as s:
        with pytest.raises(ValueError):
            await service.record(
                s,
                tenant_id=TENANT,
                event_type="coffee_made",
                occurred_at=dt.datetime.now(dt.UTC),
                ref_type="x",
                ref_id=uuid.uuid4(),
            )


async def test_recording_never_breaks_the_caller() -> None:
    # The note is already saved by the time this runs. Losing a KPI row is a
    # wrong dashboard; raising would lose the recruiter's work.
    async with SessionLocal() as s:
        await service.record_safely(
            s,
            tenant_id=TENANT,
            event_type="coffee_made",
            occurred_at=dt.datetime.now(dt.UTC),
            ref_type="x",
            ref_id=uuid.uuid4(),
        )


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
    await _event(when=dt.datetime.now(dt.UTC), actor=ANNA)
    async with await _client() as client:
        rows = (await client.get("/api/v1/activity/consultants")).json()
    assert any(r["actor_user_id"] == ANNA for r in rows)

