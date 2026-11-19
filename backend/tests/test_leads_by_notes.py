"""Leads sorted by notes (ELI-62): "Noch keine Notiz" — nothing has happened
with the lead yet — and "Mit Notizen", the latest note first.

A note is anything recorded on the person: a row of their contact history
(a call, a mail, a note — also an imported aiFind note, whatever its raw
spelling) or the free-text `managers.notes`.
"""

from __future__ import annotations

import datetime as dt
import uuid

from app.core.database import SessionLocal
from app.domain.companies.models import Company
from app.domain.hub import call_list
from app.domain.managers.models import Manager, ManagerInteraction

TENANT = uuid.uuid4()
OTHER = uuid.uuid4()
NOW = dt.datetime(2026, 11, 11, 9, 0, tzinfo=dt.UTC)


async def _seed() -> None:
    async with SessionLocal() as s:
        co = Company(tenant_id=TENANT, name="STW GmbH")
        foreign = Company(tenant_id=OTHER, name="Fremd GmbH")
        s.add_all([co, foreign])
        await s.flush()
        fresh = Manager(tenant_id=TENANT, company_id=co.id, stage="bus_dev", full_name="Ohne Notiz",
                        notes="   ", created_at=NOW - dt.timedelta(hours=1))
        called = Manager(tenant_id=TENANT, company_id=co.id, stage="bus_dev", full_name="Angerufen",
                         created_at=NOW - dt.timedelta(days=3))
        noted = Manager(tenant_id=TENANT, company_id=co.id, stage="bus_dev", full_name="Notiert",
                        created_at=NOW - dt.timedelta(days=2))
        free_text = Manager(tenant_id=TENANT, company_id=co.id, stage="bus_dev", full_name="Freitext",
                            notes="Kennt uns von der Messe", created_at=NOW - dt.timedelta(days=4))
        # A history row in ANOTHER workspace pointing at this tenant's person
        # must not count — the aggregate is tenant-scoped.
        leaked = Manager(tenant_id=TENANT, company_id=co.id, stage="bus_dev", full_name="Fremd notiert",
                         created_at=NOW - dt.timedelta(days=5))
        s.add_all([fresh, called, noted, free_text, leaked])
        await s.flush()
        s.add_all([
            ManagerInteraction(tenant_id=TENANT, manager_id=called.id, interaction_type="business_call",
                               occurred_at=NOW - dt.timedelta(days=2), outcome="not_reached"),
            ManagerInteraction(tenant_id=TENANT, manager_id=called.id, interaction_type="business_call",
                               occurred_at=NOW - dt.timedelta(hours=5), outcome="not_reached"),
            # An imported aiFind note in its raw spelling.
            ManagerInteraction(tenant_id=TENANT, manager_id=noted.id, interaction_type="Meeting Notes",
                               occurred_at=NOW - dt.timedelta(days=1), summary="Sucht 2 Entwickler"),
            ManagerInteraction(tenant_id=OTHER, manager_id=leaked.id, interaction_type="note",
                               occurred_at=NOW - dt.timedelta(hours=1), summary="fremd"),
        ])
        await s.commit()


async def test_every_row_says_how_many_notes_and_when_the_last_one_was() -> None:
    await _seed()
    async with SessionLocal() as s:
        page = await call_list.contacts(s, tenant_id=TENANT, now=NOW)
    by_name = {r["full_name"]: r for r in page["rows"]}
    assert by_name["Angerufen"]["note_count"] == 2
    assert by_name["Angerufen"]["last_note_at"] == NOW - dt.timedelta(hours=5)
    assert by_name["Notiert"]["note_count"] == 1
    assert by_name["Ohne Notiz"]["note_count"] == 0 and by_name["Ohne Notiz"]["last_note_at"] is None
    assert by_name["Fremd notiert"]["note_count"] == 0
    assert by_name["Freitext"]["has_notes"] is True and by_name["Ohne Notiz"]["has_notes"] is False


async def test_without_notes_lists_only_leads_nothing_happened_with() -> None:
    await _seed()
    async with SessionLocal() as s:
        page = await call_list.contacts(s, tenant_id=TENANT, notes="none", now=NOW)
    assert [r["full_name"] for r in page["rows"]] == ["Ohne Notiz", "Fremd notiert"]
    assert page["total"] == 2


async def test_with_notes_lists_the_latest_note_first_free_text_last() -> None:
    await _seed()
    async with SessionLocal() as s:
        page = await call_list.contacts(s, tenant_id=TENANT, notes="with", now=NOW)
    assert [r["full_name"] for r in page["rows"]] == ["Angerufen", "Notiert", "Freitext"]
    assert page["total"] == 3


async def test_the_counts_cover_the_other_filters_but_not_the_notes_choice() -> None:
    await _seed()
    async with SessionLocal() as s:
        everyone = await call_list.contacts(s, tenant_id=TENANT, notes="with", now=NOW)
        searched = await call_list.contacts(s, tenant_id=TENANT, q="not", now=NOW)
    assert everyone["note_counts"] == {"all": 5, "none": 2, "with": 3}
    # "Ohne Notiz", "Notiert", "Fremd notiert" match the search.
    assert searched["note_counts"] == {"all": 3, "none": 2, "with": 1}


async def test_the_route_takes_the_filter() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.core.auth import get_current_tenant
    from app.core.config import settings
    from app.main import app

    await _seed()
    app.dependency_overrides[get_current_tenant] = lambda: TENANT
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            ok = await c.get(f"{settings.api_v1_prefix}/hub/call-list/contacts?notes=none")
            bad = await c.get(f"{settings.api_v1_prefix}/hub/call-list/contacts?notes=maybe")
    finally:
        app.dependency_overrides.clear()
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert [r["full_name"] for r in body["rows"]] == ["Ohne Notiz", "Fremd notiert"]
    assert body["note_counts"] == {"all": 5, "none": 2, "with": 3}
    assert body["rows"][0]["note_count"] == 0
    assert bad.status_code == 422
