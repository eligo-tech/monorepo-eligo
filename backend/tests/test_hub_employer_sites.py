"""Employers' Impressum: switchboard phone, VAT id, register (ELI-30).

`hub/employer_sites.py`: the agency check's discipline (`test_hub_sites.py`)
applied to employers whose ads name no contact person. Asserted on what is
stored and on the requests that actually left (the recording fetcher), not on
which helper ran.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import pathlib
import uuid

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.domain.hub import employer_sites, sites, suppression
from app.domain.hub.models import (
    EMPLOYER,
    PRIVATE_RECRUITER,
    HubAdContact,
    HubCompany,
    HubJobPosting,
    HubObservation,
    HubPostingPayload,
    HubSiteCheck,
)
from app.domain.hub.resolution import normalize_company_name

FX = pathlib.Path(__file__).parent / "fixtures" / "impressum"
NOW = dt.datetime.now(dt.UTC)


def _html(text: str) -> str:
    return "<html><body>" + "".join(f"<p>{line}</p>" for line in text.split("\n")) + "</body></html>"


class _Fetcher:
    """Answers from URL → (status, html); records every request. A URL in
    `slow` never answers within the batch."""

    def __init__(self, pages: dict[str, tuple[int, str | None]], slow: frozenset[str] | set[str] = frozenset()) -> None:
        self.pages, self.slow = pages, slow
        self.requested: list[str] = []

    async def get(self, url: str) -> sites.SitePage:
        self.requested.append(url)
        if url in self.slow:
            await asyncio.sleep(30)
        status, html = self.pages.get(url, (404, None))
        return sites.SitePage(url=url, final_url=url, status=status, html=html)


def _mayr() -> dict:
    return {
        "https://alois-mayr.at/": (200, '<a href="/impressum/">Impressum</a>'),
        "https://alois-mayr.at/impressum/": (200, _html((FX / "alois_mayr_at.txt").read_text())),
    }


def _tempton() -> dict:
    return {
        "https://tempton.de/": (200, '<a href="/impressum">Impressum</a>'),
        "https://tempton.de/impressum": (200, _html((FX / "tempton_de.txt").read_text())),
    }


async def _company(
    name: str,
    ad: str = "",
    *,
    kind: str = EMPLOYER,
    raw: dict | None = None,
    open_ads: int = 1,
    sole_trader: bool = False,
    named_contact: bool = False,
    **facts,
) -> uuid.UUID:
    async with SessionLocal() as s:
        c = HubCompany(
            name=name, normalized_name=normalize_company_name(name), dedupe_key=f"x:{uuid.uuid4()}",
            resolution_basis="name_place", city="Wörgl", source="bundesagentur", kind=kind,
            open_postings_count=open_ads, suspected_natural_person=sole_trader, first_seen_at=NOW,
            last_seen_at=NOW, **facts,
        )
        s.add(c)
        await s.flush()
        p = HubJobPosting(
            hub_company_id=c.id, title="Maurer (m/w/d)", berufsfeld="Bau", source="bundesagentur",
            external_id=f"e-{uuid.uuid4().hex[:6]}", content_hash=uuid.uuid4().hex, segment=kind,
            posted_at=NOW, first_seen_at=NOW, last_seen_at=NOW, is_active=True,
            payload=HubPostingPayload(raw=raw or {}, description=ad),
        )
        s.add(p)
        await s.flush()
        if named_contact:
            s.add(HubAdContact(
                hub_job_posting_id=p.id, hub_company_id=c.id, person_key="max mustermann",
                full_name="Max Mustermann", last_name="Mustermann", quote="Max Mustermann", text_source="ad",
            ))
        await s.commit()
        return c.id


async def _run(fetcher, limit: int = 20) -> dict:
    async with SessionLocal() as s:
        return await employer_sites.check_employer_sites(s, fetcher=fetcher, limit=limit)


async def _checks(company_id: uuid.UUID) -> list[HubSiteCheck]:
    async with SessionLocal() as s:
        return list((await s.scalars(select(HubSiteCheck).where(HubSiteCheck.hub_company_id == company_id))).all())


async def test_a_verified_impressum_stores_phone_vat_and_register() -> None:
    cid = await _company("Alois Mayr Bauwaren GmbH", "Bewerbung an bewerbung@alois-mayr.at")
    outcome = await _run(_Fetcher(_mayr()))
    [check] = await _checks(cid)
    async with SessionLocal() as s:
        company = await s.get(HubCompany, cid)
        observations = await s.scalar(select(func.count()).select_from(HubObservation))
    assert outcome["checked"] == 1 and outcome["verified"] == 1
    assert check.status == "verified" and check.domain == "alois-mayr.at"
    assert check.group_key == f"employer:{cid}"
    assert check.facts["phone"] == "+43 5332 795-0"
    assert check.facts["vat_id"] == "ATU31821909" and check.facts["register"] == "FN 56945v"
    assert check.impressum_url == "https://alois-mayr.at/impressum/"
    assert check.observation_id is not None and observations == 1
    assert (company.website_domain, company.vat_id, company.register_number, company.register_court) == (
        "alois-mayr.at", "ATU31821909", "FN 56945v", "Innsbruck",
    )
    assert "Mustermann" not in str(check.facts)  # people parsed, never stored


async def test_facts_already_on_record_are_not_overwritten() -> None:
    cid = await _company(
        "Alois Mayr Bauwaren GmbH", "bewerbung@alois-mayr.at",
        website_domain="mayr-bau.at", vat_id="ATU00000001", register_number="FN 1a",
    )
    await _run(_Fetcher(_mayr()))
    async with SessionLocal() as s:
        company = await s.get(HubCompany, cid)
    assert (company.website_domain, company.vat_id, company.register_number) == ("mayr-bau.at", "ATU00000001", "FN 1a")


async def test_someone_elses_impressum_stores_nothing_and_the_next_candidate_is_tried() -> None:
    # The best candidate (name-like, first A→Z) carries another firm's
    # Impressum; the second is the employer's own site.
    ads = "Mehr unter www.aaa-mayr.de · Bewerbung an bewerbung@alois-mayr.at"
    cid = await _company("Alois Mayr Bauwaren GmbH", ads)
    other = {
        "https://aaa-mayr.de/": (200, '<a href="/impressum">Impressum</a>'),
        "https://aaa-mayr.de/impressum": _tempton()["https://tempton.de/impressum"],
    }
    outcome = await _run(_Fetcher({**other, **_mayr()}))
    checks = {c.domain: c for c in await _checks(cid)}
    assert outcome["verified"] == 1
    assert checks["aaa-mayr.de"].status == "not_named" and checks["aaa-mayr.de"].facts == {}
    assert checks["alois-mayr.at"].status == "verified"


async def test_only_someone_elses_impressum_leaves_the_company_untouched() -> None:
    cid = await _company("Alois Mayr Bauwaren GmbH", "Mehr unter www.tempton.de")
    outcome = await _run(_Fetcher(_tempton()))
    async with SessionLocal() as s:
        company = await s.get(HubCompany, cid)
    assert outcome["not_named"] == 1
    assert company.website_domain is None and company.vat_id is None and company.register_number is None


async def test_the_ba_external_link_is_a_website_source() -> None:
    cid = await _company("Alois Mayr Bauwaren GmbH", "Kein Link im Text.", raw={"externeURL": "https://alois-mayr.at/karriere"})
    outcome = await _run(_Fetcher(_mayr()))
    assert outcome["verified"] == 1 and (await _checks(cid))[0].domain == "alois-mayr.at"


async def test_no_website_in_any_ad_is_recorded_and_asked_again_after_a_month() -> None:
    cid = await _company("Alois Mayr Bauwaren GmbH", "Bewerbung bitte per Post.")
    fetcher = _Fetcher({})
    outcome = await _run(fetcher)
    [check] = await _checks(cid)
    assert outcome["no_domain"] == 1 and check.status == "no_domain" and check.domain == ""
    assert fetcher.requested == []
    assert (await _run(_Fetcher({})))["checked"] == 0  # not tomorrow
    async with SessionLocal() as s:
        (await s.get(HubSiteCheck, check.id)).checked_at = NOW - dt.timedelta(days=31)
        await s.commit()
    assert (await _run(_Fetcher({})))["checked"] == 1  # after a month


async def test_a_checked_employer_is_not_fetched_again() -> None:
    await _company("Alois Mayr Bauwaren GmbH", "bewerbung@alois-mayr.at")
    await _run(_Fetcher(_mayr()))
    again = _Fetcher(_mayr())
    assert (await _run(again))["checked"] == 0 and again.requested == []


async def test_an_error_is_retried_after_a_week() -> None:
    cid = await _company("Alois Mayr Bauwaren GmbH", "bewerbung@alois-mayr.at")
    await _run(_Fetcher({"https://alois-mayr.at/": (503, None)}))
    [check] = await _checks(cid)
    assert check.status == "error"
    assert (await _run(_Fetcher(_mayr())))["checked"] == 0
    async with SessionLocal() as s:
        (await s.get(HubSiteCheck, check.id)).checked_at = NOW - dt.timedelta(days=8)
        await s.commit()
    assert (await _run(_Fetcher(_mayr())))["verified"] == 1


async def test_a_sole_trader_and_an_agency_are_never_checked() -> None:
    await _company("Erika Beispiel Fliesenleger", "info@beispiel-fliesen.de", sole_trader=True)
    await _company("Alois Mayr Personal GmbH", "jobs@alois-mayr.at", kind=PRIVATE_RECRUITER)
    fetcher = _Fetcher(_mayr())
    assert (await _run(fetcher))["checked"] == 0 and fetcher.requested == []


async def test_employers_no_ad_names_a_person_for_come_first() -> None:
    named = await _company("Tempton Group GmbH", "jobs@tempton.de", named_contact=True, open_ads=50)
    unnamed = await _company("Alois Mayr Bauwaren GmbH", "bewerbung@alois-mayr.at", open_ads=1)
    await _run(_Fetcher({**_mayr(), **_tempton()}), limit=1)
    assert await _checks(named) == []
    assert len(await _checks(unnamed)) == 1


async def test_a_domain_shared_by_branches_is_fetched_once() -> None:
    a = await _company("Alois Mayr Bauwaren GmbH", "bewerbung@alois-mayr.at")
    b = await _company("Alois Mayr Bauwaren GmbH", "jobs@alois-mayr.at")
    fetcher = _Fetcher(_mayr())
    outcome = await _run(fetcher)
    assert outcome["verified"] == 2
    assert fetcher.requested.count("https://alois-mayr.at/impressum/") == 1
    assert (await _checks(a))[0].observation_id == (await _checks(b))[0].observation_id


async def test_a_slow_site_does_not_hold_up_the_batch(monkeypatch) -> None:
    monkeypatch.setattr(employer_sites, "BATCH_SECONDS", 0.5)
    slow = await _company("Langsam Bau GmbH", "info@langsam-bau.de")
    fast = await _company("Alois Mayr Bauwaren GmbH", "bewerbung@alois-mayr.at")
    outcome = await _run(_Fetcher(_mayr(), slow={"https://langsam-bau.de/"}))
    assert outcome["checked"] == 1 and outcome["verified"] == 1
    assert await _checks(slow) == []  # unrecorded: picked again next batch
    assert len(await _checks(fast)) == 1


async def test_a_suppressed_employer_takes_its_checks_with_it() -> None:
    cid = await _company("Alois Mayr Bauwaren GmbH", "bewerbung@alois-mayr.at")
    await _run(_Fetcher(_mayr()))
    assert len(await _checks(cid)) == 1
    async with SessionLocal() as s:
        await suppression.suppress(s, scope="company", name="Alois Mayr Bauwaren GmbH", reason="objection")
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).select_from(HubSiteCheck)) == 0
