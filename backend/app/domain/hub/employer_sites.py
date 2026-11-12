"""Employers' Impressum: switchboard phone, VAT id, register (ELI-30).

The last fallback when no ad names a contact person: the phone number the
employer's own Impressum publishes. Measured on 1,000 random employers whose
ads name nobody (2026-11-11, `scripts/measure_employer_impressum.py`): 164
verified, 140 with a phone, 134 with a VAT id, 125 with a register number;
30 of 30 spot-checked hits were right.

A machine-only nightly step (ARCHITECTURE.md RULE 1), the agency check's
discipline applied to employers (`sites.py`):

  ads (text + the BA's `externeURL`) → `domains.domain_candidates`
    → `SiteFetcher` (robots.txt, identified, paced, public hosts only)
    → `find_impressum_link` → `parse_impressum`
    → `names_firm`: the Impressum must name THIS employer as its operator.

Only then are facts kept. A parent company's or a job board's Impressum is
someone else's: its VAT id and register would be wrong on this employer, so
"not named" stores nothing (measured: dennree GmbH for "denn's Biomarkt",
Duisburger Hafen AG for a duisport subsidiary).

What is stored, as published:
  * `hub_site_checks` (one row per employer and domain, `hub_company_id` set):
    status, Impressum URL, the fetch's `hub_observations` row, and the company
    facts — phone, VAT id, register, function mailboxes. Never people.
  * on `hub_companies`, only where still empty: website, VAT id, register.
Suspected sole traders are never checked: their phone is a person's phone.

Order: employers without a named contact first, then by open ads.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import hashlib
import uuid
from urllib.parse import urljoin, urlparse

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.hub.adapters.impressum import find_impressum_link, names_firm, parse_impressum
from app.domain.hub.adapters.partner_pages import page_text
from app.domain.hub.domains import domain_candidates, registrable_domain
from app.domain.hub.models import (
    EMPLOYER,
    SITE_BLOCKED,
    SITE_ERROR,
    SITE_NO_DOMAIN,
    SITE_NO_IMPRESSUM,
    SITE_NOT_NAMED,
    SITE_VERIFIED,
    HubAdContact,
    HubCompany,
    HubJobPosting,
    HubObservation,
    HubPostingPayload,
    HubSiteCheck,
)
from app.domain.hub.sites import ERROR_RETRY_AFTER, STATUS_BLOCKED, STATUS_ERROR, company_facts

logger = get_logger(__name__)

#: New ads may name a website: an employer without one is asked again.
NO_DOMAIN_RETRY_AFTER = dt.timedelta(days=30)
#: Candidates tried per employer: the best, and one more if it fails.
MAX_TRIES = 2
#: Ads read per employer for website candidates.
MAX_ADS = 20
#: Sites fetched at once. Different hosts; each host is paced by the fetcher.
CONCURRENCY = 20
#: A batch stops waiting here; unfinished employers are simply picked again.
#: Kept well under the nightly client's 120 s read timeout.
BATCH_SECONDS = 90

COUNTS = (SITE_VERIFIED, SITE_NOT_NAMED, SITE_NO_IMPRESSUM, SITE_BLOCKED, SITE_ERROR, SITE_NO_DOMAIN)


def group_key(company_id: uuid.UUID) -> str:
    return f"employer:{company_id}"


@dataclasses.dataclass
class _Page:
    """One domain's homepage → Impressum fetch, shared by every employer
    that names the domain in this batch (a chain's branches)."""

    url: str
    impressum_url: str | None
    status: int
    text: str
    note: str | None


@dataclasses.dataclass
class _Try:
    domain: str
    status: str
    page: _Page | None = None
    facts: dict = dataclasses.field(default_factory=dict)


def verdict(page_status: int, is_impressum: bool, named: bool) -> str:
    """Same verdicts as the agency check (`sites._check_one`)."""
    if page_status in (STATUS_BLOCKED, 401, 403):
        return SITE_BLOCKED  # the site said no — not asked again
    if page_status in (STATUS_ERROR, 408, 429) or page_status >= 500:
        return SITE_ERROR  # "not now" — retried after a week
    if not is_impressum:
        return SITE_NO_IMPRESSUM
    return SITE_VERIFIED if named else SITE_NOT_NAMED


async def _due(session: AsyncSession, now: dt.datetime, limit: int) -> list[tuple[uuid.UUID, str]]:
    """Employers to check: open employer ads, not a suspected sole trader,
    no check that still stands. Those no ad names a person for come first."""
    standing = exists().where(
        HubSiteCheck.hub_company_id == HubCompany.id,
        or_(
            HubSiteCheck.status.not_in((SITE_ERROR, SITE_NO_DOMAIN)),
            and_(HubSiteCheck.status == SITE_ERROR, HubSiteCheck.checked_at > now - ERROR_RETRY_AFTER),
            and_(HubSiteCheck.status == SITE_NO_DOMAIN, HubSiteCheck.checked_at > now - NO_DOMAIN_RETRY_AFTER),
        ),
    )
    open_ad = exists().where(
        HubJobPosting.hub_company_id == HubCompany.id,
        HubJobPosting.is_active.is_(True),
        HubJobPosting.segment == EMPLOYER,
    )
    named = exists().where(HubAdContact.hub_company_id == HubCompany.id)
    rows = await session.execute(
        select(HubCompany.id, HubCompany.name)
        .where(
            HubCompany.kind == EMPLOYER,
            HubCompany.suspected_natural_person.is_not(True),
            open_ad,
            ~standing,
        )
        .order_by(named.asc(), HubCompany.open_postings_count.desc(), HubCompany.id)
        .limit(limit)
    )
    return [(r.id, r.name) for r in rows]


async def _ads(session: AsyncSession, company_id: uuid.UUID) -> list[tuple[str, str]]:
    """(posting id, text) — the ad text, the partner page and the BA's
    `externeURL`, which often is the employer's own careers page."""
    rows = await session.execute(
        select(
            HubJobPosting.id,
            HubPostingPayload.description,
            HubPostingPayload.source_page_text,
            HubPostingPayload.raw,
        )
        .join(HubPostingPayload, HubPostingPayload.hub_job_posting_id == HubJobPosting.id)
        .where(HubJobPosting.hub_company_id == company_id, HubJobPosting.is_active.is_(True))
        .limit(MAX_ADS)
    )
    out = []
    for posting_id, description, partner_text, raw in rows:
        link = raw.get("externeURL") if isinstance(raw, dict) else None
        text = " ".join(t for t in (description, partner_text, link if isinstance(link, str) else None) if t)
        out.append((str(posting_id), text))
    return out


async def _fetch(fetcher, domain: str) -> _Page:
    home = await fetcher.get(f"https://{domain}/")
    page, impressum_url = home, None
    if home.status == 200:
        site = registrable_domain(urlparse(home.final_url).hostname) or domain
        impressum_url = find_impressum_link(home.html, home.final_url, site) or urljoin(home.final_url, "/impressum")
        page = await fetcher.get(impressum_url)
    text = page_text(page.html) if page.status == 200 else ""
    return _Page(url=home.url, impressum_url=impressum_url, status=page.status, text=text, note=page.note)


async def _check(fetcher, name: str, ads, pages: dict[str, asyncio.Task]) -> list[_Try]:
    candidates = domain_candidates(ads, firm_names=[name])
    if not candidates:
        return [_Try(domain="", status=SITE_NO_DOMAIN)]
    tries: list[_Try] = []
    for candidate in candidates[:MAX_TRIES]:
        domain = candidate["domain"]
        if domain not in pages:
            pages[domain] = asyncio.ensure_future(_fetch(fetcher, domain))
        page = await pages[domain]
        facts = parse_impressum(page.text)
        status = verdict(page.status, facts.is_impressum, names_firm(page.text, [name]))
        tries.append(_Try(domain, status, page, company_facts(facts) if status == SITE_VERIFIED else {}))
        if status == SITE_VERIFIED:
            break
    return tries


async def check_employer_sites(session: AsyncSession, *, fetcher, limit: int = 20) -> dict[str, int]:
    """Check up to `limit` employers' Impressum; see the module docstring."""
    now = dt.datetime.now(dt.UTC)
    due = await _due(session, now, limit)
    work = [(company_id, name, await _ads(session, company_id)) for company_id, name in due]
    await session.commit()  # no transaction held open across network fetches

    pages: dict[str, asyncio.Task] = {}
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(name: str, ads) -> list[_Try]:
        async with gate:
            return await _check(fetcher, name, ads, pages)

    tasks = [asyncio.ensure_future(one(name, ads)) for _, name, ads in work]
    if tasks:
        await asyncio.wait(tasks, timeout=BATCH_SECONDS)

    counts = {"checked": 0, **{status: 0 for status in COUNTS}}
    observations: dict[str, uuid.UUID] = {}
    for (company_id, *_), task in zip(work, tasks, strict=True):
        if not task.done():
            task.cancel()  # picked again next batch; nothing recorded
            continue
        if task.exception() is not None:
            logger.warning("employer site check failed: %s", type(task.exception()).__name__)
            tries = [_Try(domain="", status=SITE_ERROR)]
        else:
            tries = task.result()
        for t in tries:
            observation_id = None
            if t.page is not None:
                observation_id = observations.get(t.domain)
                if observation_id is None:
                    observation_id = await _observe(session, t.page, t.status, now)
                    observations[t.domain] = observation_id
            await _record(session, company_id, t, observation_id, now)
        final = tries[-1]
        if final.status == SITE_VERIFIED:
            await _backfill(session, company_id, final)
        counts["checked"] += 1
        counts[final.status] += 1
    leftover = [t for t in [*tasks, *pages.values()] if not t.done()]
    for task in leftover:
        task.cancel()
    await asyncio.gather(*leftover, return_exceptions=True)
    await session.commit()
    logger.info("employer site checks: %s", counts)
    return counts


async def switchboards(session: AsyncSession, hub_company_ids) -> dict[uuid.UUID, dict]:
    """Verified Impressum facts per employer, for the company card and the
    Leads/Unternehmen views. Only "verified": a rejected Impressum is someone
    else's and is never shown."""
    ids = list(hub_company_ids)
    if not ids:
        return {}
    rows = await session.scalars(
        select(HubSiteCheck)
        .where(HubSiteCheck.hub_company_id.in_(ids), HubSiteCheck.status == SITE_VERIFIED)
        .order_by(HubSiteCheck.checked_at.desc())
    )
    out: dict[uuid.UUID, dict] = {}
    for check in rows:
        facts = check.facts or {}
        if check.hub_company_id in out or not any(facts.get(k) for k in ("phone", "vat_id", "register")):
            continue
        out[check.hub_company_id] = {
            "phone": facts.get("phone"),
            "vat_id": facts.get("vat_id"),
            "register": facts.get("register"),
            "register_court": facts.get("register_court"),
            "impressum_url": check.impressum_url,
            "domain": check.domain,
            "checked_at": check.checked_at,
        }
    return out


async def _observe(session: AsyncSession, page: _Page, status: str, now: dt.datetime) -> uuid.UUID:
    observation = HubObservation(
        source="impressum",
        request_url=(page.impressum_url or page.url)[:1000],
        http_status=page.status if page.status >= 100 else None,
        robots_allowed=page.status != STATUS_BLOCKED,
        record_count=1 if status in (SITE_VERIFIED, SITE_NOT_NAMED) else 0,
        content_hash=hashlib.sha256(page.text.encode()).hexdigest() if page.text else None,
        fetched_at=now,
        note=(f"employer {status}" + (f"; {page.note}" if page.note else ""))[:500],
    )
    session.add(observation)
    await session.flush()
    return observation.id


async def _record(session, company_id: uuid.UUID, t: _Try, observation_id, now: dt.datetime) -> None:
    key = group_key(company_id)
    check = await session.scalar(
        select(HubSiteCheck).where(HubSiteCheck.domain == t.domain, HubSiteCheck.group_key == key)
    )
    if check is None:
        check = HubSiteCheck(domain=t.domain, group_key=key, hub_company_id=company_id, status=t.status, checked_at=now)
        session.add(check)
    check.hub_company_id = company_id
    check.status = t.status
    check.impressum_url = t.page.impressum_url[:1000] if t.page and t.page.impressum_url else None
    check.observation_id = observation_id
    check.facts = t.facts
    check.checked_at = now


async def _backfill(session: AsyncSession, company_id: uuid.UUID, t: _Try) -> None:
    """Website, VAT id, register — only where still empty: a fact already on
    record outranks this one."""
    company = await session.get(HubCompany, company_id)
    if company is None:
        return
    if company.website_domain is None:
        company.website_domain = t.domain
    if company.vat_id is None and t.facts.get("vat_id"):
        company.vat_id = t.facts["vat_id"]
    if company.register_number is None and t.facts.get("register"):
        company.register_number = t.facts["register"]
        company.register_court = company.register_court or t.facts.get("register_court")
