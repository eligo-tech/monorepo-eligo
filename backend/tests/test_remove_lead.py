"""ELI-66: "Leads entfernen" — and every field of a lead editable.

"Entfernen" hides a lead, it never deletes one: the same `no_interest_at`
as ELI-60's "Kein Interesse" (off the Leads list, under the hidden filter,
restorable, not taken again from Markt), plus WHY — a reason code
(`agency` · `not_relevant` · `other`) and, optionally, the recruiter's words.

The edit side: name, company, XING and the address join the fields the
Manager page already edited, and every hand edit goes through
`verify_and_commit` as a `human_verified` change, so its provenance is the
recruiter — the same rule as a candidate's manual edit.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.companies.models import Company
from app.domain.hub import call_list
from app.domain.managers.models import Manager
from app.domain.verification.models import EnrichmentRecord, Receipt
from tests.test_call_list import market  # noqa: F401 — fixture

DEFAULT = settings.default_tenant_id
API = settings.api_v1_prefix


def _api() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _lead(hub_company_id) -> dict:
    async with SessionLocal() as s:
        return await call_list.log_call(
            s, tenant_id=DEFAULT, hub_company_id=hub_company_id, person_key="denkinger", outcome="not_reached"
        )


async def _contacts(**kw) -> dict:
    async with SessionLocal() as s:
        return await call_list.contacts(s, tenant_id=DEFAULT, **kw)


async def test_entfernen_hides_the_lead_with_its_reason_and_keeps_the_record(market) -> None:  # noqa: F811
    lead = await _lead(market["forschner"])
    mid = lead["manager_id"]
    async with _api() as c:
        r = await c.post(f"{API}/managers/{mid}/remove", json={"reason": "agency"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["no_interest_at"] is not None and body["removed_reason"] == "agency"

        # Off the Leads list, under the hidden filter with its reason.
        page = await _contacts()
        assert page["rows"] == [] and page["no_interest_total"] == 1
        (row,) = (await _contacts(no_interest=True))["rows"]
        assert row["manager_id"] == mid and row["removed_reason"] == "agency"

        # Not taken again from Markt (ELI-60's guard holds for a removed lead).
        again = await c.post(f"{API}/managers", json={
            "company_id": str(lead["company_id"]), "full_name": "Leonie Denkinger", "first_name": "Leonie",
            "last_name": "Denkinger", "source": "public_web",
        })
        assert again.status_code == 409 and again.json()["detail"]["code"] == "no_interest"

        # Restorable through the existing path; the reason goes with it.
        back = await c.delete(f"{API}/managers/{mid}/no-interest")
        assert back.status_code == 200
        assert back.json()["no_interest_at"] is None and back.json()["removed_reason"] is None
        assert [r["manager_id"] for r in (await _contacts())["rows"]] == [mid]

    async with SessionLocal() as s:
        manager = await s.get(Manager, uuid.UUID(str(mid)))
        receipts = (await s.scalars(select(Receipt).where(Receipt.subject_id == str(mid)))).all()
    assert manager is not None and manager.stage == "bus_dev"
    (mark,) = [r for r in receipts if r.summary == "Lead entfernt"]
    assert mark.payload["reason"] == "agency"


async def test_sonstiges_keeps_the_words_on_the_record_never_in_the_receipt(market) -> None:  # noqa: F811
    mid = (await _lead(market["forschner"]))["manager_id"]
    async with _api() as c:
        r = await c.post(f"{API}/managers/{mid}/remove", json={"reason": "other", "note": "Firma wird verkauft"})
        assert r.status_code == 200
        assert r.json()["removed_reason"] == "other" and r.json()["removed_note"] == "Firma wird verkauft"
        assert (await c.post(f"{API}/managers/{mid}/remove", json={"reason": "weil"})).status_code == 422
        assert (await c.post(f"{API}/managers/{uuid.uuid4()}/remove", json={"reason": "other"})).status_code == 404
        cleared = (await c.delete(f"{API}/managers/{mid}/no-interest")).json()
        assert cleared["removed_note"] is None
    async with SessionLocal() as s:
        receipts = (await s.scalars(select(Receipt).where(Receipt.subject_id == str(mid)))).all()
    assert all("verkauft" not in str(r.payload) for r in receipts)


async def test_a_kein_interesse_lead_removed_keeps_its_date_and_gets_the_reason(market) -> None:  # noqa: F811
    lead = await _lead(market["forschner"])
    mid = lead["manager_id"]
    async with _api() as c:
        await c.post(f"{API}/managers/{mid}/interactions",
                     json={"interaction_type": "business_call", "summary": "", "outcome": "not_interested"})
        since = (await c.get(f"{API}/managers/{mid}")).json()["no_interest_at"]
        r = await c.post(f"{API}/managers/{mid}/remove", json={"reason": "not_relevant"})
        assert r.json()["no_interest_at"] == since and r.json()["removed_reason"] == "not_relevant"


async def test_a_vetted_manager_is_not_removed_as_a_lead() -> None:
    async with SessionLocal() as s:
        company = Company(tenant_id=DEFAULT, name="Kunde GmbH")
        s.add(company)
        await s.flush()
        m = Manager(tenant_id=DEFAULT, company_id=company.id, full_name="Petra Kunde", stage="manager")
        s.add(m)
        await s.commit()
    async with _api() as c:
        r = await c.post(f"{API}/managers/{m.id}/remove", json={"reason": "agency"})
        assert r.status_code == 409
        assert (await c.get(f"{API}/managers/{m.id}")).json()["no_interest_at"] is None


async def test_every_field_of_a_lead_is_editable_with_the_recruiter_as_provenance(market) -> None:  # noqa: F811
    lead = await _lead(market["forschner"])
    mid = lead["manager_id"]
    async with SessionLocal() as s:
        other = Company(tenant_id=DEFAULT, name="Forschner Holding")
        foreign = Company(tenant_id=uuid.uuid4(), name="Fremd GmbH")
        s.add_all([other, foreign])
        await s.commit()
    patch = {
        "full_name": "Leonie Denkinger-Maier", "first_name": "Leonie", "last_name": "Denkinger-Maier",
        "role_title": "Leitung Personal", "xing_url": "https://www.xing.com/profile/Leonie_Denkinger",
        "street": "Hauptstr. 1", "postal_code": "72336", "city": "Balingen",
        "phones": [{"number": "+49 7424 943 126", "kind": "direct"}, {"number": "+49 7424 943 0", "kind": "switchboard"}],
        "company_id": str(other.id),
    }
    async with _api() as c:
        r = await c.patch(f"{API}/managers/{mid}", json=patch)
        assert r.status_code == 200, r.text
        got = r.json()
        for k in ("full_name", "last_name", "role_title", "xing_url", "street", "postal_code", "city"):
            assert got[k] == patch[k], k
        assert got["company_id"] == str(other.id)
        assert [p["number"] for p in got["phones"]] == ["+49 7424 943 126", "+49 7424 943 0"]
        # Another workspace's company is not this lead's to move to.
        bad = await c.patch(f"{API}/managers/{mid}", json={"company_id": str(foreign.id)})
        assert bad.status_code == 422
        assert (await c.get(f"{API}/managers/{mid}")).json()["company_id"] == str(other.id)
        assert (await c.patch(f"{API}/managers/{mid}", json={"full_name": " "})).status_code == 422

    async with SessionLocal() as s:
        records = (await s.scalars(select(EnrichmentRecord).where(
            EnrichmentRecord.entity_id == uuid.UUID(str(mid)), EnrichmentRecord.entity_type == "manager"))).all()
    by_field = {r.field: r for r in records}
    # Only what changed — first_name was already "Leonie".
    assert set(by_field) == {"full_name", "last_name", "role_title", "xing_url", "street", "postal_code",
                             "city", "phones", "company_id"}
    assert all(r.source == "human_verified" and r.committed for r in records)
