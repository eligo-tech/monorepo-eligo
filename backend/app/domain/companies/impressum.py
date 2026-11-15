"""A workspace company's website, VAT id and register — from its Impressum (ELI-39).

"Agent should be able to: find website of the company; extract USt-Nr,
Handelsregister (Impressum) — muss da stehen." German law (§ 5 DDG) makes
every commercial site publish both, so the Impressum is the source.

Markt answers first: an employer with open ads already gets its Impressum
read by the corpus job (`hub/employer_sites.py`, ELI-30), and a linked
company shows it (`hub.call_list.company_switchboards`). This module is for
the rest — a company of the workspace no verified Markt row answers for —
and runs the SAME discipline on data the workspace already holds:

  website  the company's own `domain`, else the company mail domains of its
           contacts (freemail and job boards never; `hub.domains._usable`)
    → `employer_sites.fetch_impressum` (robots.txt, identified, paced,
      public hosts only — the corpus job's `SiteFetcher`)
    → `parse_impressum` (deterministic; VAT check digit; an ambiguous value
      reads as nothing) → `names_firm`: the Impressum must name THIS company
      as its operator, or nothing is kept.

Agents propose, verification commits: a verified reading is a
`ProposedChange` through `verify_and_commit` with deterministic
postconditions — named as operator, every value present on the fetched page,
a German VAT id passing its check digit — so it leaves a provenance record
(the URL and fetch time) and VERIFY + WRITE receipts (references only).

Where it lives: on the workspace's own `companies` row (`impressum`), never
in `hub_*`. The website came from the workspace's data (its contacts'
mail), and a corpus row keyed on it would tell every workspace who this one's
clients are (ARCHITECTURE.md RULE 3). For the same reason no
`hub_observations` row is written; the fetch's URL, time and content hash sit
on the record itself.

Company facts only: no phone (a sole trader's would be a person's), no
mailbox, never the people an Impressum names. Suspected sole traders are not
checked at all, as in the corpus job.

Machine-triggered only (RULE 1): `POST /hub/companies/impressum/check`,
scheduled by `.github/workflows/hub-company-links.yml`. No button, no page
load fetches anything.
"""

from __future__ import annotations

import asyncio
import collections
import datetime as dt
import hashlib
import json
import re
import time
import uuid
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.common.enums import ConfidenceSource
from app.domain.companies.models import Company
from app.domain.hub.adapters.impressum import names_firm, parse_impressum, register_entries, valid_de_vat
from app.domain.hub.domains import _usable, registrable_domain
from app.domain.hub.employer_sites import BATCH_SECONDS, CONCURRENCY, MAX_TRIES, fetch_impressum, verdict
from app.domain.hub.models import (
    SITE_BLOCKED,
    SITE_ERROR,
    SITE_NO_DOMAIN,
    SITE_NO_IMPRESSUM,
    SITE_NOT_NAMED,
    SITE_VERIFIED,
)
from app.domain.hub.resolution import looks_like_natural_person
from app.domain.verification import service as verification
from app.domain.verification.schemas import ProposedChange

logger = get_logger(__name__)

AGENT = "company_impressum"
#: A verified reading whose values did not all re-check: nothing kept.
REJECTED = "rejected"
COUNTS = (SITE_VERIFIED, SITE_NOT_NAMED, SITE_NO_IMPRESSUM, SITE_BLOCKED, SITE_ERROR, SITE_NO_DOMAIN, REJECTED)
#: "Not now" from a site: asked again after a week (as the corpus job).
ERROR_RETRY_AFTER = dt.timedelta(days=7)
#: No usable domain yet: a contact added later may bring one.
NO_DOMAIN_RETRY_AFTER = dt.timedelta(days=30)
#: Every other outcome but "verified" (not named, no Impressum, blocked,
#: rejected) is asked again after a quarter — or at once when the website
#: candidates changed (a recruiter entered the domain, a contact arrived).
SETTLED_RETRY_AFTER = dt.timedelta(days=90)


def site_domain(value: str | None) -> str | None:
    """"https://www.tempton.de/karriere" → "tempton.de"."""
    if not value or not value.strip():
        return None
    value = value.strip()
    host = urlparse(value if "://" in value else f"https://{value}").hostname
    return registrable_domain(host)


def website_candidates(domain: str | None, emails: list[str]) -> list[str]:
    """The company's own domain first, then its contacts' company mail
    domains, most frequent first. Freemail and job boards never."""
    out: list[str] = []
    own = site_domain(domain)
    if own and _usable(own):
        out.append(own)
    counted = collections.Counter(
        d for e in emails if "@" in (e or "") and (d := registrable_domain(e.rsplit("@", 1)[1].strip())) and _usable(d)
    )
    for d, _ in sorted(counted.items(), key=lambda kv: (-kv[1], kv[0])):
        if d not in out:
            out.append(d)
    return out[:MAX_TRIES]


def on_page(facts: dict, text: str | None) -> tuple[bool, str]:
    """Postcondition: every value appears on the fetched page as published."""
    text = text or ""
    # Compared as printed, minus separators: "CHE-123.456.789", "DE 252 406 571".
    alnum = re.sub(r"[^0-9A-Za-z]", "", text)
    spaced = " ".join(text.split())
    missing = []
    if (vat := facts.get("vat_id")) and re.sub(r"[^0-9A-Za-z]", "", vat) not in alnum:
        missing.append("vat_id")
    if register := facts.get("register"):
        kind, _, number = register.partition(" ")
        found = (kind, number) in register_entries(text) if kind in ("HRA", "HRB") else number in alnum
        if not found:
            missing.append("register")
    if (court := facts.get("register_court")) and " ".join(court.split()) not in spaced:
        missing.append("register_court")
    if missing:
        return False, f"not on the fetched page: {', '.join(missing)}"
    return True, "every value is on the fetched page"


def _vat_checks(facts: dict) -> tuple[bool, str]:
    vat = facts.get("vat_id")
    if vat and vat.startswith("DE") and not valid_de_vat(vat):
        return False, "VAT id fails its check digit"
    if vat and vat.startswith("DE"):
        return True, "German VAT id check digit valid"
    return True, "no German VAT id (no check digit tested)"


def _standing(facts: dict | None, candidates: list[str], now: dt.datetime) -> bool:
    if not facts:
        return False
    try:
        checked = dt.datetime.fromisoformat(facts.get("checked_at") or "")
    except ValueError:
        return False
    status = facts.get("status")
    if status == SITE_VERIFIED:
        return True
    if facts.get("candidates") is not None and facts["candidates"] != candidates:
        return False  # a new website to try
    if status == SITE_ERROR:
        return checked > now - ERROR_RETRY_AFTER
    if status == SITE_NO_DOMAIN:
        return checked > now - NO_DOMAIN_RETRY_AFTER
    return checked > now - SETTLED_RETRY_AFTER


async def _due(session: AsyncSession, tenant_id: uuid.UUID, now: dt.datetime, limit: int) -> list[tuple]:
    """(company id, name, website candidates) for companies no Markt reading
    with a VAT id or register and no standing check answers for; clients
    first."""
    from app.domain.hub.call_list import corpus_switchboards
    from app.domain.managers.models import Manager

    companies = (
        await session.scalars(
            select(Company).where(Company.tenant_id == tenant_id).order_by(Company.is_client.desc(), Company.name)
        )
    ).all()
    emails: dict[uuid.UUID, list[str]] = collections.defaultdict(list)
    for company_id, email in await session.execute(
        select(Manager.company_id, Manager.email).where(
            Manager.tenant_id == tenant_id, Manager.company_id.is_not(None), Manager.email.is_not(None)
        )
    ):
        emails[company_id].append(email)
    candidates = {c.id: website_candidates(c.domain, emails[c.id]) for c in companies}
    open_ = [
        c for c in companies
        if not _standing(c.impressum, candidates[c.id], now) and not looks_like_natural_person(c.name)
    ]
    if not open_:
        return []
    # A Markt reading with only a phone does not answer for VAT id and register.
    boards = await corpus_switchboards(session, tenant_id, [c.id for c in open_])
    answered = {cid for cid, b in boards.items() if b.get("vat_id") or b.get("register")}
    open_ = [c for c in open_ if c.id not in answered][:limit]
    return [(c.id, c.name, candidates[c.id]) for c in open_]


async def _read(fetcher, name: str, candidates: list[str], pages: dict[str, asyncio.Task]) -> dict:
    """One company: try its candidates until one Impressum names it."""
    if not candidates:
        return {"status": SITE_NO_DOMAIN, "domain": None}
    result: dict = {}
    for domain in candidates:
        if domain not in pages:
            pages[domain] = asyncio.ensure_future(fetch_impressum(fetcher, domain))
        page = await pages[domain]
        facts = parse_impressum(page.text)
        named = names_firm(page.text, [name])
        status = verdict(page.status, facts.is_impressum, named)
        result = {"status": status, "domain": domain, "page": page, "facts": facts, "named": named}
        if status == SITE_VERIFIED:
            break
    return result


async def check_companies(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    fetcher,
    limit: int = 20,
    now: dt.datetime | None = None,
    seconds: float = BATCH_SECONDS,
) -> dict[str, int]:
    """Read up to `limit` of this workspace's companies' Impressum; see the
    module docstring. Unfinished reads are not recorded — picked again."""
    now = now or dt.datetime.now(dt.UTC)
    work = await _due(session, tenant_id, now, limit)
    await session.commit()  # no transaction held open across network fetches

    pages: dict[str, asyncio.Task] = {}
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(name: str, candidates: list[str]) -> dict:
        async with gate:
            return await _read(fetcher, name, candidates, pages)

    tasks = [asyncio.ensure_future(one(name, candidates)) for _, name, candidates in work]
    if tasks:
        await asyncio.wait(tasks, timeout=seconds)
    # Decide which reads finished BEFORE cancelling anything: cancelling one
    # company's read cancels a page fetch another company awaits too, and that
    # one would then be "done" as cancelled (review of #267).
    finished = [task.done() and not task.cancelled() for task in tasks]
    for task, ok in zip(tasks, finished, strict=True):
        if not ok:
            task.cancel()

    counts = {"checked": 0, **{status: 0 for status in COUNTS}}
    for (company_id, _, candidates), task, ok in zip(work, tasks, finished, strict=True):
        if not ok:
            continue  # picked again next batch; nothing recorded
        if task.exception() is not None:
            logger.warning("company impressum check failed: %s", type(task.exception()).__name__)
            result = {"status": SITE_ERROR, "domain": None}
        else:
            result = task.result()
        status = await _record(session, tenant_id, company_id, result, candidates, now)
        counts["checked"] += 1
        counts[status] += 1
    leftover = [t for t in [*tasks, *pages.values()] if not t.done()]
    for task in leftover:
        task.cancel()
    await asyncio.gather(*leftover, return_exceptions=True)
    await session.commit()
    return counts


async def _record(
    session: AsyncSession, tenant_id: uuid.UUID, company_id: uuid.UUID, result: dict, candidates: list[str], now: dt.datetime
) -> str:
    company = await session.scalar(select(Company).where(Company.tenant_id == tenant_id, Company.id == company_id))
    if company is None:
        return result["status"]  # deleted meanwhile; nothing to record
    status = result["status"]
    if status == SITE_VERIFIED and await _commit_verified(session, tenant_id, company, result, candidates, now):
        return SITE_VERIFIED
    if status == SITE_VERIFIED:
        status = REJECTED
    # Scheduling only — what was tried and when, never a value: the record
    # asserts nothing about the company, so it owes no receipt.
    company.impressum = {
        "status": status, "domain": result.get("domain"), "candidates": candidates, "checked_at": now.isoformat(),
    }
    await session.flush()
    return status


async def _commit_verified(
    session: AsyncSession, tenant_id: uuid.UUID, company: Company, result: dict, candidates: list[str], now: dt.datetime
) -> bool:
    page, parsed, domain = result["page"], result["facts"], result["domain"]
    register = f"{parsed.register_type} {parsed.register_number}" if parsed.register_number else None
    values = {
        k: v
        for k, v in {"vat_id": parsed.vat_id, "register": register, "register_court": parsed.register_court}.items()
        if v
    }
    url = page.impressum_url or page.url
    record = {
        "status": SITE_VERIFIED,
        "domain": domain,
        **values,
        "impressum_url": url[:1000],
        "fetched_at": now.isoformat(),
        "checked_at": now.isoformat(),
        "content_sha256": hashlib.sha256(page.text.encode()).hexdigest(),
        "candidates": candidates,
    }
    change = ProposedChange(
        tenant_id=tenant_id,
        entity_type="company",
        entity_id=company.id,
        field="impressum",
        proposed_value=json.dumps({"domain": domain, **values}, sort_keys=True),
        source=ConfidenceSource.PUBLIC_WEB,
        source_detail=f"{url[:900]} @ {now.isoformat()}",
        confidence=1.0,  # deterministic parse, re-checked below
    )
    text = page.text

    async def _apply(_session: AsyncSession, _change) -> None:
        company.impressum = record
        await _session.flush()
        landed = await _session.scalar(
            select(Company.impressum).where(Company.tenant_id == tenant_id, Company.id == company.id)
        )
        if (landed or {}).get("fetched_at") != record["fetched_at"]:
            raise RuntimeError("company impressum did not land")

    def _named(_c) -> tuple[bool, str]:
        if result["named"] and names_firm(text, [company.name]):
            return True, "Impressum names the company as operator"
        return False, "Impressum does not name the company"

    outcome = await verification.verify_and_commit(
        session,
        change=change,
        agent=AGENT,
        postconditions=[_named, lambda _c: on_page(values, text), lambda _c: _vat_checks(values)],
        apply_hook=_apply,
    )
    if outcome.committed and not company.domain:
        await _commit_domain(session, tenant_id, company, domain, url, now, _named)
    return outcome.committed


async def _commit_domain(session, tenant_id: uuid.UUID, company: Company, domain: str, url: str, now, named) -> None:
    """The website found and verified becomes the company's `domain` — only
    where the record has none, and as its own receipted change, so the ledger
    names the field it wrote (review of #267)."""

    async def _apply(_session: AsyncSession, _change) -> None:
        company.domain = domain
        await _session.flush()
        landed = await _session.scalar(
            select(Company.domain).where(Company.tenant_id == tenant_id, Company.id == company.id)
        )
        if landed != domain:
            raise RuntimeError("company domain did not land")

    await verification.verify_and_commit(
        session,
        change=ProposedChange(
            tenant_id=tenant_id,
            entity_type="company",
            entity_id=company.id,
            field="domain",
            proposed_value=domain,
            source=ConfidenceSource.PUBLIC_WEB,
            source_detail=f"{url[:900]} @ {now.isoformat()}",
            confidence=1.0,
        ),
        agent=AGENT,
        postconditions=[named],
        apply_hook=_apply,
    )


def board(company: Company) -> dict | None:
    """The verified facts in the switchboard's shape (no phone), for the
    company page and the Mandate's Stammdaten. Only a verified reading with a
    VAT id or a register is shown."""
    facts = company.impressum or {}
    if facts.get("status") != SITE_VERIFIED or not any(facts.get(k) for k in ("vat_id", "register")):
        return None
    return {
        "phone": None,
        "vat_id": facts.get("vat_id"),
        "register": facts.get("register"),
        "register_court": facts.get("register_court"),
        "impressum_url": facts.get("impressum_url"),
        "domain": facts.get("domain"),
        "checked_at": dt.datetime.fromisoformat(facts["fetched_at"]),
    }


async def check_all_workspaces(*, fetcher, limit: int) -> dict[str, int]:
    """`check_companies` for every workspace, each in its own session pinned
    to it (as `market.link_all_workspaces`), until `limit` companies were
    read or the request's time is up."""
    from app.core.database import SessionLocal, current_tenant_var
    from app.domain.tenants.models import Tenant

    async with SessionLocal() as session:
        tenants = (await session.scalars(select(Tenant.id).order_by(Tenant.id))).all()
    deadline = time.monotonic() + BATCH_SECONDS
    total = {"tenants": 0, "checked": 0, **{status: 0 for status in COUNTS}}
    for tenant_id in tenants:
        left = deadline - time.monotonic()
        if total["checked"] >= limit or left < 10:
            break
        token = current_tenant_var.set(str(tenant_id))
        try:
            async with SessionLocal() as session:
                counts = await check_companies(
                    session, tenant_id=tenant_id, fetcher=fetcher, limit=limit - total["checked"], seconds=left
                )
        finally:
            current_tenant_var.reset(token)
        for key, value in counts.items():
            total[key] += value
        total["tenants"] += 1
    logger.info("company impressum: %s", total)
    return total
