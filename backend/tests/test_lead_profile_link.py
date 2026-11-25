"""ELI-77: a contact added from a pasted LinkedIn or XING profile link.

The browser reads the name from the link's slug — nothing is fetched, ever
(RULE 1). The server stores the profile in `linkedin_url` / `xing_url` in one
spelling, and recognises the same profile already held in this workspace —
at ANY company, since a person changes employers but keeps the profile — and
answers 409 `lead_exists` with it instead of a second record.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.companies.models import Company
from app.domain.managers import service as managers
from app.domain.managers.models import Manager

DEFAULT = settings.default_tenant_id
API = settings.api_v1_prefix

LEAD = {
    "job_title": "Senior Java Entwickler (m/w/d)",
    "full_name": "Anna Berg",
    "company_name": "Nordlicht Software GmbH",
}


def _api() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _count() -> int:
    async with SessionLocal() as s:
        return int(await s.scalar(select(func.count()).select_from(Manager)))


def test_one_key_per_profile() -> None:
    key = managers.profile_key
    same = [
        "https://www.linkedin.com/in/anna-berg-1a2b3c",
        "https://de.linkedin.com/in/Anna-Berg-1a2b3c/?originalSubdomain=de",
        "linkedin.com/in/anna-berg-1a2b3c/",
        "http://m.linkedin.com/in/anna-berg-1a2b3c#about",
    ]
    assert {key(u) for u in same} == {"linkedin:in/anna-berg-1a2b3c"}
    assert key("https://www.xing.com/profile/Anna_Berg/cv") == key("xing.com/profile/anna_berg?sc_o=x") == (
        "xing:profile/anna_berg"
    )
    assert key("https://www.linkedin.com/pub/anna-berg/12/345/678") == "linkedin:pub/anna-berg/12/345/678"
    # Umlauts typed or percent-encoded are one profile.
    assert key("https://www.linkedin.com/in/j%C3%B6rg-m%C3%BCller") == key("https://www.linkedin.com/in/jörg-müller")
    for other in ("https://www.linkedin.com/company/nordlicht", "https://www.stepstone.de/x", None, ""):
        assert key(other) is None


async def test_the_profile_is_stored_in_its_column() -> None:
    async with _api() as c:
        li = await c.post(f"{API}/managers/leads", json={
            **LEAD, "profile_url": "https://de.linkedin.com/in/anna-berg-1a2b3c/?trk=x",
        })
        xi = await c.post(f"{API}/managers/leads", json={
            **LEAD, "full_name": "Ben Ott", "profile_url": "https://www.xing.com/profile/Ben_Ott/cv",
        })
    assert li.status_code == 201, li.text
    assert li.json()["linkedin_url"] == "https://www.linkedin.com/in/anna-berg-1a2b3c"
    assert xi.json()["xing_url"] == "https://www.xing.com/profile/Ben_Ott"
    # The profile is not the job's ad: provenance says how it was found.
    assert li.json()["source_detail"] == "https://www.linkedin.com/in/anna-berg-1a2b3c"


async def test_a_link_that_is_no_profile_is_refused() -> None:
    async with _api() as c:
        r = await c.post(f"{API}/managers/leads", json={**LEAD, "profile_url": "https://www.linkedin.com/jobs/view/1"})
    assert r.status_code == 422
    assert await _count() == 0


async def test_the_same_profile_is_offered_not_doubled_even_at_another_company() -> None:
    async with SessionLocal() as s:
        old = Company(tenant_id=DEFAULT, name="Altfirma AG")
        s.add(old)
        await s.flush()
        held = Manager(tenant_id=DEFAULT, company_id=old.id, full_name="Anna Berg-Schulz",
                       linkedin_url="https://de.linkedin.com/in/anna-berg-1a2b3c/")
        s.add(held)
        await s.commit()
        held_id = held.id
    async with _api() as c:
        # Another company, another spelling of the name — the same profile.
        r = await c.post(f"{API}/managers/leads", json={
            **LEAD, "full_name": "Anna Berg", "profile_url": "https://www.linkedin.com/in/Anna-Berg-1a2b3c?trk=x",
        })
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "lead_exists"
    assert detail["manager_id"] == str(held_id)
    assert detail["match"] == "profile"
    assert await _count() == 1


async def test_another_workspaces_profile_is_not_this_ones() -> None:
    async with SessionLocal() as s:
        theirs = Company(tenant_id=uuid.uuid4(), name="Fremd GmbH")
        s.add(theirs)
        await s.flush()
        s.add(Manager(tenant_id=theirs.tenant_id, company_id=theirs.id, full_name="Anna Berg",
                      linkedin_url="https://www.linkedin.com/in/anna-berg-1a2b3c"))
        await s.commit()
    async with _api() as c:
        r = await c.post(f"{API}/managers/leads", json={
            **LEAD, "profile_url": "https://www.linkedin.com/in/anna-berg-1a2b3c",
        })
    assert r.status_code == 201, r.text


async def test_a_linkedin_source_link_and_a_linkedin_profile_together() -> None:
    """Both boxes LinkedIn: one profile column, the pasted profile wins — no 500."""
    async with _api() as c:
        r = await c.post(f"{API}/managers/leads", json={
            **LEAD,
            "source_url": "https://www.linkedin.com/in/someone-else/",
            "profile_url": "https://de.linkedin.com/in/anna-berg-1a2b3c",
        })
    assert r.status_code == 201, r.text
    assert r.json()["linkedin_url"] == "https://www.linkedin.com/in/anna-berg-1a2b3c"


def test_odd_links_are_not_profiles_and_spellings_fold() -> None:
    from app.domain.managers.profiles import canonical_url

    key = managers.profile_key
    # Credentials in a link: not a profile, whatever host the text names.
    assert canonical_url("https://u:p@www.linkedin.com/in/anna") is None
    assert canonical_url("https://www.linkedin.com:pw@evil.com/in/x") is None
    # Path tricks are not a person.
    assert canonical_url("linkedin.com/in/../company/acme") is None
    # The kind is case-insensitive, like the host.
    assert key("https://www.linkedin.com/IN/anna-berg") == "linkedin:in/anna-berg"
    # A composed and a decomposed ü are one profile.
    assert key("https://www.linkedin.com/in/jürgen-berg") == key("https://www.linkedin.com/in/jürgen-berg")


async def test_a_profile_pasted_as_the_source_link_is_matched_too() -> None:
    async with _api() as c:
        first = await c.post(f"{API}/managers/leads", json={
            **LEAD, "source_url": "https://www.linkedin.com/in/anna-berg-1a2b3c/",
        })
        again = await c.post(f"{API}/managers/leads", json={
            **LEAD, "company_name": "Andere GmbH", "profile_url": "https://de.linkedin.com/in/anna-berg-1a2b3c",
        })
    assert first.status_code == 201
    assert again.status_code == 409
    assert again.json()["detail"]["manager_id"] == first.json()["id"]
