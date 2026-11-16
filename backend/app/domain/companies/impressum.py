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

Website finder (`website_search.py`): when the workspace's own candidates are
none, or their Impressum named another firm / was missing, the company's name
(+ its town, + "Impressum") is sent to a web search (Brave Search API, a
subprocessor — ARCHITECTURE.md). Its result domains — directories, registers,
social networks, job boards and freemail never (`hub.domains._usable`) — are
tried AFTER the workspace's own, through exactly the same checks: the search
proposes, the Impressum decides. What was searched (name, time, domains) is
kept on `impressum.search`, so a company is searched at most once per
`SETTLED_RETRY_AFTER` or when renamed; a reading it led to says
`found_by: "search"` and its provenance names the web search. Only the
company's name and town leave — no person, no mailbox; suspected sole traders
are never searched (they are not checked at all). Without
`ELIGO_SEARCH_API_KEY` there is no finder and nothing changes.

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
import dataclasses
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
from app.domain.hub.domains import _usable, registrable_domain, search_usable
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
#: Outcomes a web search may improve on: no website of its own, or its own
#: websites' Impressum named another firm or none was found. Not an error or
#: a block (the site may well be the right one) and not a rejected reading.
SEARCHABLE = frozenset({SITE_NO_DOMAIN, SITE_NOT_NAMED, SITE_NO_IMPRESSUM})
FOUND_BY_WORKSPACE = "workspace"
FOUND_BY_SEARCH = "search"
SEARCH_COUNTS = ("searched", "search_failed")
_SEARCH_NOTE = " · website found by web search"
#: A search that got no answer (provider error, timeout) is asked again the
#: next day — not within the same daily run, which would re-pick the same
#: companies batch after batch while the provider is down.
SEARCH_FAILED_RETRY_AFTER = dt.timedelta(days=1)


@dataclasses.dataclass(frozen=True)
class _Work:
    company_id: uuid.UUID
    name: str
    town: str | None
    #: The workspace's own website candidates (what `_standing` compares).
    candidates: list[str]
    #: A search still fresh for this name, or None.
    search: dict | None
    #: Due only for the finder: its own candidates' outcome is settled and
    #: stored, so they are not fetched again; a budget slot is reserved.
    search_only: bool = False
    stored: dict | None = None


@dataclasses.dataclass
class _Budget:
    #: Queries left for companies due anyway (the rest is reserved).
    free: int


def search_domains(urls: list[str]) -> list[str]:
    """Search result URLs → registrable domains worth an Impressum fetch,
    best first: no directory, register, social network, job board, freemail."""
    out: list[str] = []
    for url in urls:
        try:
            host = urlparse(url).hostname
        except ValueError:
            continue
        domain = registrable_domain(host)
        if domain and search_usable(domain) and domain not in out:
            out.append(domain)
    return out[:MAX_TRIES]


def search_query(name: str, town: str | None) -> str:
    """Company name, its town when known, and "Impressum" — nothing else. Of
    a "street, PLZ town" location only the last part (PLZ and town) is sent."""
    place = (town or "").split(",")[-1].strip()[:80]
    return " ".join(p for p in (name.strip(), place, "Impressum") if p)


def _search_fresh(facts: dict | None, name: str, now: dt.datetime) -> dict | None:
    search = (facts or {}).get("search")
    if not isinstance(search, dict) or search.get("name") != name:
        return None
    try:
        at = dt.datetime.fromisoformat(search.get("at") or "")
    except (TypeError, ValueError):
        return None
    period = SEARCH_FAILED_RETRY_AFTER if search.get("failed") else SETTLED_RETRY_AFTER
    return search if at > now - period else None


def _search_wanted(facts: dict | None, candidates: list[str], name: str, now: dt.datetime) -> bool:
    """A settled check the finder could still improve: its own candidates were
    all tried, the outcome is searchable, and no fresh search exists — or one
    whose domains a cut-short read never got to try (`pending`)."""
    if not facts or facts.get("status") not in SEARCHABLE or facts.get("candidates") != candidates:
        return False
    fresh = _search_fresh(facts, name, now)
    return fresh is None or bool(fresh.get("pending"))


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


async def _due(
    session: AsyncSession, tenant_id: uuid.UUID, now: dt.datetime, limit: int, search_budget: int = 0
) -> list[_Work]:
    """Companies no Markt reading with a VAT id or register and no standing
    check answers for — plus, up to `search_budget`, settled ones the website
    finder has not searched yet; clients first."""
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
    # Suspected sole traders are never checked, and so never searched.
    companies = [c for c in companies if not looks_like_natural_person(c.name)]
    standing = {c.id: _standing(c.impressum, candidates[c.id], now) for c in companies}
    open_ = [
        c for c in companies
        if not standing[c.id] or (search_budget > 0 and _search_wanted(c.impressum, candidates[c.id], c.name, now))
    ]
    if not open_:
        return []
    # A Markt reading with only a phone does not answer for VAT id and register.
    boards = await corpus_switchboards(session, tenant_id, [c.id for c in open_])
    answered = {cid for cid, b in boards.items() if b.get("vat_id") or b.get("register")}
    work: list[_Work] = []
    for c in open_:
        if len(work) >= limit:
            break
        if c.id in answered:
            continue
        if standing[c.id]:  # due only for the finder
            if search_budget <= 0:
                continue
            search_budget -= 1
        work.append(_Work(
            c.id, c.name, c.location, candidates[c.id], _search_fresh(c.impressum, c.name, now),
            search_only=standing[c.id], stored=c.impressum if standing[c.id] else None,
        ))
    return work


async def _try(fetcher, name: str, candidates: list[str], pages: dict[str, asyncio.Task]) -> dict:
    """Try candidates in order until one Impressum names the company."""
    if not candidates:
        return {"status": SITE_NO_DOMAIN, "domain": None}
    result: dict = {}
    error: dict | None = None
    for domain in candidates:
        if domain not in pages:
            pages[domain] = asyncio.ensure_future(fetch_impressum(fetcher, domain))
        page = await pages[domain]
        facts = parse_impressum(page.text)
        named = names_firm(page.text, [name])
        status = verdict(page.status, facts.is_impressum, named)
        result = {"status": status, "domain": domain, "page": page, "facts": facts, "named": named}
        if status == SITE_VERIFIED:
            return result
        if status == SITE_ERROR and error is None:
            error = result
    # A candidate that failed may still be the one: "error" is asked again
    # after a week, the last candidate's settled answer only after a quarter.
    return error or result


async def _search(searcher, work: _Work, now: dt.datetime) -> dict:
    """One query for this company. A search error never fails the read: it is
    "no candidates", marked `failed` so it is asked again the next day."""
    try:
        urls = await searcher.search(search_query(work.name, work.town))
    except Exception as exc:  # noqa: BLE001 — a search failure is "no candidates"
        logger.warning("website search failed: %s", type(exc).__name__)
        urls = None
    if urls is None:
        return {"name": work.name, "at": now.isoformat(), "domains": [], "failed": True}
    return {"name": work.name, "at": now.isoformat(), "domains": search_domains(urls)}


def _may_search(searcher, work: _Work, budget: _Budget) -> bool:
    """Spend one query — synchronously, before any await, so concurrent reads
    cannot overdraw the budget. A finder-only company has its slot reserved."""
    if searcher is None or searcher.remaining <= 0:
        return False
    if not work.search_only:
        if budget.free <= 0:
            return False
        budget.free -= 1
    searcher.remaining -= 1
    return True


async def _read(
    fetcher, work: _Work, pages: dict[str, asyncio.Task], searcher, now: dt.datetime,
    budget: _Budget, found: dict[uuid.UUID, dict],
) -> dict:
    """One company: its own candidates first (or, when due only for the
    finder, their stored outcome); when they found nothing that names it, the
    finder's domains (stored, else searched now). A search answer goes into
    `found` at once, so a read cut short still keeps what was paid for."""
    if work.search_only and work.stored:
        result = {
            "status": work.stored.get("status"), "domain": work.stored.get("domain"),
            "found_by": work.stored.get("found_by", FOUND_BY_WORKSPACE),
        }
    else:
        result = await _try(fetcher, work.name, work.candidates, pages)
        result["found_by"] = FOUND_BY_WORKSPACE
    search, outcome = work.search, None
    if search is not None:
        search = {k: v for k, v in search.items() if k != "pending"}
    if result["status"] in SEARCHABLE and search is None and _may_search(searcher, work, budget):
        search = await _search(searcher, work, now)
        found[work.company_id] = search
        outcome = "search_failed" if search.get("failed") else "searched"
    if search is None:
        return result
    extra = [d for d in search.get("domains") or [] if d not in work.candidates]
    if result["status"] in SEARCHABLE and extra:
        result = await _try(fetcher, work.name, extra, pages)
        result["found_by"] = FOUND_BY_SEARCH
    result["search"], result["search_outcome"] = search, outcome
    return result


async def check_companies(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    fetcher,
    searcher=None,
    limit: int = 20,
    now: dt.datetime | None = None,
    seconds: float = BATCH_SECONDS,
) -> dict[str, int]:
    """Read up to `limit` of this workspace's companies' Impressum; see the
    module docstring. `searcher` (`website_search.WebSearch`, or None: no
    finder) proposes websites for companies whose own found nothing.
    Unfinished reads are not recorded — picked again."""
    now = now or dt.datetime.now(dt.UTC)
    work = await _due(session, tenant_id, now, limit, searcher.remaining if searcher is not None else 0)
    await session.commit()  # no transaction held open across network fetches

    pages: dict[str, asyncio.Task] = {}
    gate = asyncio.Semaphore(CONCURRENCY)
    reserved = sum(item.search_only for item in work)
    budget = _Budget(free=max(0, (searcher.remaining if searcher is not None else 0) - reserved))
    found: dict[uuid.UUID, dict] = {}

    async def one(item: _Work) -> dict:
        async with gate:
            return await _read(fetcher, item, pages, searcher, now, budget, found)

    tasks = [asyncio.ensure_future(one(item)) for item in work]
    if tasks:
        await asyncio.wait(tasks, timeout=seconds)
    # Decide which reads finished BEFORE cancelling anything: cancelling one
    # company's read cancels a page fetch another company awaits too, and that
    # one would then be "done" as cancelled (review of #267).
    finished = [task.done() and not task.cancelled() for task in tasks]
    for task, ok in zip(tasks, finished, strict=True):
        if not ok:
            task.cancel()

    counts = {"checked": 0, **{status: 0 for status in COUNTS}, **dict.fromkeys(SEARCH_COUNTS, 0)}
    for item, task, ok in zip(work, tasks, finished, strict=True):
        if not ok:
            # Picked again next batch; only a search already paid for is kept.
            if (search := found.get(item.company_id)) is not None:
                await _keep_search(session, tenant_id, item.company_id, search)
            continue
        if task.exception() is not None:
            logger.warning("company impressum check failed: %s", type(task.exception()).__name__)
            result = {"status": SITE_ERROR, "domain": None, "search": found.get(item.company_id)}
        else:
            result = task.result()
        status = await _record(session, tenant_id, item.company_id, result, item.candidates, now)
        counts["checked"] += 1
        if result.get("search_outcome"):
            counts[result["search_outcome"]] += 1
        counts[status] += 1
    leftover = [t for t in [*tasks, *pages.values()] if not t.done()]
    for task in leftover:
        task.cancel()
    await asyncio.gather(*leftover, return_exceptions=True)
    await session.commit()
    return counts


async def _keep_search(session: AsyncSession, tenant_id: uuid.UUID, company_id: uuid.UUID, search: dict) -> None:
    """A read cut short after its search answered: keep the answer, marked
    `pending` (its domains are still to try), the rest of the record as is."""
    company = await session.scalar(select(Company).where(Company.tenant_id == tenant_id, Company.id == company_id))
    if company is not None:
        company.impressum = {**(company.impressum or {}), "search": {**search, "pending": True}}
        await session.flush()


def _finder(result: dict) -> dict:
    """Where the tried website came from, and the search kept for reuse."""
    out = {}
    if result.get("domain"):
        out["found_by"] = result.get("found_by", FOUND_BY_WORKSPACE)
    if result.get("search") is not None:
        out["search"] = result["search"]
    return out


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
        **_finder(result),
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
        **_finder(result),
    }
    note = _SEARCH_NOTE if result.get("found_by") == FOUND_BY_SEARCH else ""
    change = ProposedChange(
        tenant_id=tenant_id,
        entity_type="company",
        entity_id=company.id,
        field="impressum",
        proposed_value=json.dumps({"domain": domain, **values}, sort_keys=True),
        source=ConfidenceSource.PUBLIC_WEB,
        source_detail=f"{url[:900]} @ {now.isoformat()}{note}",
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
        await _commit_domain(session, tenant_id, company, domain, url, now, _named, note)
    return outcome.committed


async def _commit_domain(
    session, tenant_id: uuid.UUID, company: Company, domain: str, url: str, now, named, note: str = ""
) -> None:
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
            source_detail=f"{url[:900]} @ {now.isoformat()}{note}",
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


async def check_all_workspaces(*, fetcher, limit: int, searcher=None) -> dict[str, int]:
    """`check_companies` for every workspace, each in its own session pinned
    to it (as `market.link_all_workspaces`), until `limit` companies were
    read or the request's time is up."""
    from app.core.database import SessionLocal, current_tenant_var
    from app.domain.tenants.models import Tenant

    async with SessionLocal() as session:
        tenants = (await session.scalars(select(Tenant.id).order_by(Tenant.id))).all()
    deadline = time.monotonic() + BATCH_SECONDS
    total = {"tenants": 0, "checked": 0, **{status: 0 for status in COUNTS}, **dict.fromkeys(SEARCH_COUNTS, 0)}
    for tenant_id in tenants:
        left = deadline - time.monotonic()
        if total["checked"] >= limit or left < 10:
            break
        token = current_tenant_var.set(str(tenant_id))
        try:
            async with SessionLocal() as session:
                counts = await check_companies(
                    session, tenant_id=tenant_id, fetcher=fetcher, searcher=searcher,
                    limit=limit - total["checked"], seconds=left,
                )
        finally:
            current_tenant_var.reset(token)
        for key, value in counts.items():
            total[key] += value
        total["tenants"] += 1
    logger.info("company impressum: %s", total)
    return total
