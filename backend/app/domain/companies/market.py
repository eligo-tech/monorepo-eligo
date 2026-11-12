"""A workspace's companies in Markt: links and open jobs (ELI-33).

"Bei Managern oder Leads soll immer direkt die Karriereseite hinterlegt sein,
damit wir wissen welche Stellen gerade offen sind, wenn wir anrufen." The open
jobs are already in the shared corpus (BA, EURES, Personio, Ashby …, refreshed
weekly and daily); a company only has to be linked to its corpus rows. Measured
2026-11-12: of ~330 companies per workspace only 1–6 were linked.

Linking is the corpus→record crossing (CLAUDE.md §2.6), so each one goes
through `verify_and_commit` and leaves a receipt, like adoption does.

AUTO-LINK ONLY WHAT IS CERTAIN (agreed for ELI-33): the same normalized name
AND the same town — the company's own location, else the town or postcode its
managers' records give (imports carry no company location). Measured: ~84 of
331 companies per workspace. A name match in another or unknown town is left
for a person to confirm (ELI-33 step 2b); a wrong link would show another
company's jobs on a call.
"""

from __future__ import annotations

import collections
import datetime as dt
import re
import uuid
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.common.enums import ConfidenceSource
from app.domain.companies.models import Company
from app.domain.hub.domains import _usable, registrable_domain
from app.domain.hub.models import EMPLOYER, HubCompany, HubCompanyLink, HubJobPosting, HubPostingPayload
from app.domain.hub.resolution import fold_umlauts, normalize_company_name
from app.domain.hub.schemas import source_detail_url
from app.domain.verification import service as verification
from app.domain.verification.schemas import ProposedChange

logger = get_logger(__name__)

#: Open jobs shown per company.
OPEN_JOBS_LIMIT = 50


def town_key(value: str | None) -> str | None:
    """A town as both sides write it: "Nürnberg, Mittelfranken" and
    "Nuernberg" are one; "Frankfurt (Oder)" keeps only "frankfurt" — the
    postcode, when there is one, is what tells Frankfurts apart."""
    if not value:
        return None
    head = re.split(r"[,(/]", value, maxsplit=1)[0]
    key = re.sub(r"[^a-z]", "", fold_umlauts(head.lower()))
    return key or None


async def _places(session: AsyncSession, tenant_id: uuid.UUID, company_ids: list[uuid.UUID]) -> dict:
    """Per company: the towns and postcodes it is known at — its own
    location, else where its managers' records say they sit."""
    from app.domain.managers.models import Manager

    places: dict[uuid.UUID, dict[str, set[str]]] = collections.defaultdict(lambda: {"towns": set(), "plz": set()})
    rows = await session.execute(
        select(Manager.company_id, Manager.city, Manager.postal_code).where(
            Manager.tenant_id == tenant_id, Manager.company_id.in_(company_ids)
        )
    )
    for company_id, city, plz in rows:
        if (key := town_key(city)) is not None:
            places[company_id]["towns"].add(key)
        if plz and plz.strip():
            places[company_id]["plz"].add(plz.strip())
    return places


async def exact_matches(session: AsyncSession, tenant_id: uuid.UUID) -> list[tuple[Company, list[HubCompany]]]:
    """Companies not yet linked, each with the corpus sites of the same name
    in the same town. Sites another company here already holds are left out."""
    linked = select(HubCompanyLink.company_id).where(
        HubCompanyLink.tenant_id == tenant_id, HubCompanyLink.company_id.is_not(None)
    )
    companies = (
        await session.scalars(
            select(Company).where(Company.tenant_id == tenant_id, Company.id.not_in(linked)).order_by(Company.name)
        )
    ).all()
    if not companies:
        return []
    keys = {c.id: normalize_company_name(c.name) for c in companies}
    hubs: dict[str, list[HubCompany]] = collections.defaultdict(list)
    for hub in (
        await session.scalars(
            select(HubCompany).where(
                HubCompany.normalized_name.in_(set(keys.values())), HubCompany.kind == EMPLOYER
            )
        )
    ).all():
        hubs[hub.normalized_name].append(hub)
    taken = await _unavailable(session, tenant_id)
    places = await _places(session, tenant_id, [c.id for c in companies])
    out = []
    for company in companies:
        towns = set(places[company.id]["towns"])
        if (own := town_key(company.location)) is not None:
            towns.add(own)
        plz = places[company.id]["plz"]
        same = [
            h
            for h in hubs.get(keys[company.id], [])
            if h.id not in taken
            and ((h.postal_code and h.postal_code in plz) or (town_key(h.city) is not None and town_key(h.city) in towns))
        ]
        if same:
            out.append((company, same))
    return out


IGNORED = "ignored"


async def _unavailable(session: AsyncSession, tenant_id: uuid.UUID) -> set[uuid.UUID]:
    """Sites this workspace already holds for a company, or said are not
    theirs ("Keiner davon", or a link undone) — never linked or suggested
    again, not even by the daily job."""
    return set(
        (
            await session.scalars(
                select(HubCompanyLink.hub_company_id).where(
                    HubCompanyLink.tenant_id == tenant_id,
                    (HubCompanyLink.company_id.is_not(None)) | (HubCompanyLink.relationship == IGNORED),
                )
            )
        ).all()
    )


async def link(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    company: Company,
    sites: list[HubCompany],
    basis: str,
    agent: str,
    actor: str | None = None,
) -> None:
    """Point this workspace's link rows for `sites` at `company`, through the
    verification gate (one receipt per company)."""
    from app.domain.managers.models import Manager

    has_managers = await session.scalar(
        select(Manager.id).where(Manager.company_id == company.id, Manager.stage == "manager").limit(1)
    )
    relationship = "client" if has_managers else "prospect"
    for hub in sites:
        row = await session.scalar(
            select(HubCompanyLink).where(
                HubCompanyLink.tenant_id == tenant_id, HubCompanyLink.hub_company_id == hub.id
            )
        )
        if row is None:
            row = HubCompanyLink(tenant_id=tenant_id, hub_company_id=hub.id)
            session.add(row)
        row.company_id = company.id
        row.relationship = relationship
    await session.flush()
    ids = [h.id for h in sites]

    async def _prove_it_landed(_session: AsyncSession, _change) -> None:
        landed = (
            await _session.scalars(
                select(HubCompanyLink.hub_company_id).where(
                    HubCompanyLink.tenant_id == tenant_id,
                    HubCompanyLink.company_id == company.id,
                    HubCompanyLink.hub_company_id.in_(ids),
                )
            )
        ).all()
        if set(landed) != set(ids):
            raise RuntimeError("market link did not land")

    result = await verification.verify_and_commit(
        session,
        change=ProposedChange(
            tenant_id=tenant_id,
            entity_type="company",
            entity_id=company.id,
            field="hub_company_id",
            proposed_value=",".join(str(i) for i in ids),
            source=ConfidenceSource.PUBLIC_WEB,
            source_detail=f"hub_companies/{ids[0]} · {basis}",
            confidence=1.0,
        ),
        agent=agent,
        apply_hook=_prove_it_landed,
        actor=actor,
    )
    if not result.committed:  # never at confidence 1.0 — but never silently either
        await session.rollback()
        raise RuntimeError(f"market link not committed: {result.reason}")
    # The gate records and proves; committing is the caller's (as in adoption).
    await session.commit()


async def auto_link(session: AsyncSession, *, tenant_id: uuid.UUID) -> dict[str, int]:
    """Link every exact match of one workspace; see the module docstring."""
    matches = await exact_matches(session, tenant_id)
    linked = 0
    for company, sites in matches:
        towns = sorted({h.city or h.postal_code or "" for h in sites})
        await link(
            session,
            tenant_id=tenant_id,
            company=company,
            sites=sites,
            basis=f"same name and town ({', '.join(towns)[:120]})",
            agent="company_market_link",
        )
        linked += 1
    return {"linked": linked}


async def link_all_workspaces() -> dict[str, int]:
    """`auto_link` for every workspace, each in its own session pinned to it.

    The workspaces come from `tenants`, which every role may read (the
    pre-auth org lookup). NOT from `companies`: the operator request is pinned
    to the ingest token's workspace, so under RLS that list held one
    workspace — the first production run linked 1 company instead of ~84 per
    workspace. The caller's pin is restored afterwards."""
    from app.core.database import SessionLocal, current_tenant_var
    from app.domain.tenants.models import Tenant

    async with SessionLocal() as session:
        tenants = (await session.scalars(select(Tenant.id))).all()
    total = {"tenants": 0, "linked": 0}
    for tenant_id in tenants:
        token = current_tenant_var.set(str(tenant_id))
        try:
            async with SessionLocal() as session:
                total["linked"] += (await auto_link(session, tenant_id=tenant_id))["linked"]
        finally:
            current_tenant_var.reset(token)
        total["tenants"] += 1
    logger.info("company links: %s", total)
    return total


# ---------------------------------------------------------------------------
# Step 2b: the unclear matches — a person confirms, dismisses, or undoes
# ---------------------------------------------------------------------------

#: Candidate sites shown per company (a chain can have hundreds).
SUGGESTION_SITES = 8


class NotACandidate(ValueError):
    """The site is not this company's name, or not an employer row."""


class SiteTaken(ValueError):
    """Another company of this workspace already holds the site."""


async def _candidates(
    session: AsyncSession, tenant_id: uuid.UUID, companies: list[Company]
) -> dict[uuid.UUID, list[HubCompany]]:
    """Per unlinked company: the employer sites of the same normalized name
    this workspace has neither linked nor dismissed."""
    if not companies:
        return {}
    keys = {c.id: normalize_company_name(c.name) for c in companies}
    names = {k for k in keys.values() if k}
    if not names:
        return {}
    blocked = await _unavailable(session, tenant_id)
    by_name: dict[str, list[HubCompany]] = collections.defaultdict(list)
    for hub in (
        await session.scalars(
            select(HubCompany).where(HubCompany.normalized_name.in_(names), HubCompany.kind == EMPLOYER)
        )
    ).all():
        if hub.id not in blocked:
            by_name[hub.normalized_name].append(hub)
    return {c.id: by_name.get(keys[c.id], []) for c in companies}


async def _linked_company_ids(session: AsyncSession, tenant_id: uuid.UUID) -> set[uuid.UUID]:
    return set(
        (
            await session.scalars(
                select(HubCompanyLink.company_id).where(
                    HubCompanyLink.tenant_id == tenant_id, HubCompanyLink.company_id.is_not(None)
                )
            )
        ).all()
    )


async def to_review(session: AsyncSession, tenant_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """For Unternehmen: how many candidate sites each unlinked company has."""
    linked = await _linked_company_ids(session, tenant_id)
    companies = (
        await session.scalars(select(Company).where(Company.tenant_id == tenant_id))
    ).all()
    open_ = [c for c in companies if c.id not in linked]
    return {cid: len(sites) for cid, sites in (await _candidates(session, tenant_id, open_)).items()}


async def suggestions(session: AsyncSession, *, tenant_id: uuid.UUID, company: Company) -> list[dict]:
    """The candidate sites of one unlinked company, most open ads first, each
    with its town and two sample job titles — enough to recognise the firm."""
    if company.id in await _linked_company_ids(session, tenant_id):
        return []
    sites = (await _candidates(session, tenant_id, [company])).get(company.id, [])
    if not sites:
        return []
    ids = [h.id for h in sites]
    counts = dict(
        (
            await session.execute(
                select(HubJobPosting.hub_company_id, func.count(HubJobPosting.id))
                .where(HubJobPosting.hub_company_id.in_(ids), HubJobPosting.is_active.is_(True))
                .group_by(HubJobPosting.hub_company_id)
            )
        ).all()
    )
    ranked = sorted(sites, key=lambda h: (-counts.get(h.id, 0), h.city or "", str(h.id)))[:SUGGESTION_SITES]
    out = []
    for hub in ranked:
        titles = (
            await session.scalars(
                select(HubJobPosting.title)
                .where(HubJobPosting.hub_company_id == hub.id, HubJobPosting.is_active.is_(True))
                .order_by(HubJobPosting.posted_at.desc().nulls_last())
                .limit(2)
            )
        ).all()
        out.append(
            {
                "hub_company_id": hub.id,
                "name": hub.name,
                "city": hub.city,
                "postal_code": hub.postal_code,
                "open_ads": int(counts.get(hub.id, 0)),
                "sample_titles": list(titles),
            }
        )
    return out


async def _company(session: AsyncSession, tenant_id: uuid.UUID, company_id: uuid.UUID) -> Company:
    company = await session.scalar(select(Company).where(Company.id == company_id, Company.tenant_id == tenant_id))
    if company is None:
        raise LookupError("company not found")
    return company


async def confirm(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    hub_company_ids: list[uuid.UUID],
    actor: str | None,
    dismiss_ids: list[uuid.UUID] | None = None,
) -> None:
    """A person says: these sites are our company. Only sites of the same
    name, not held by another company here; one receipt naming the person.

    `dismiss_ids`: the other sites the person was shown and did not pick —
    a same-name firm elsewhere, ruled out so its jobs do not show here."""
    company = await _company(session, tenant_id, company_id)
    wanted = set(hub_company_ids)
    sites = (
        await session.scalars(select(HubCompany).where(HubCompany.id.in_(wanted), HubCompany.kind == EMPLOYER))
    ).all()
    if not wanted or len(sites) != len(wanted) or any(
        h.normalized_name != normalize_company_name(company.name) for h in sites
    ):
        raise NotACandidate("not a site of this company's name")
    held = (
        await session.scalars(
            select(HubCompanyLink.company_id).where(
                HubCompanyLink.tenant_id == tenant_id,
                HubCompanyLink.hub_company_id.in_(wanted),
                HubCompanyLink.company_id.is_not(None),
                HubCompanyLink.company_id != company.id,
            )
        )
    ).all()
    if held:
        raise SiteTaken("another company here holds this site")
    await link(
        session,
        tenant_id=tenant_id,
        company=company,
        sites=list(sites),
        basis=f"confirmed by {actor or 'a recruiter'}",
        agent="recruiter_market_link",
        actor=actor,
    )
    others = [i for i in (dismiss_ids or []) if i not in wanted]
    if others:
        await dismiss(session, tenant_id=tenant_id, company_id=company_id, hub_company_ids=others)


async def dismiss(
    session: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID, hub_company_ids: list[uuid.UUID]
) -> None:
    """"Keiner davon": these sites are not ours — never suggested or
    auto-linked here again. Interest, not a record change: no receipt (as
    tracking, `hub.service.track_company`)."""
    await _company(session, tenant_id, company_id)
    for hub_id in set(hub_company_ids):
        row = await session.scalar(
            select(HubCompanyLink).where(HubCompanyLink.tenant_id == tenant_id, HubCompanyLink.hub_company_id == hub_id)
        )
        if row is None:
            if await session.get(HubCompany, hub_id) is None:
                continue
            row = HubCompanyLink(tenant_id=tenant_id, hub_company_id=hub_id)
            session.add(row)
        if row.company_id is None:
            row.relationship = IGNORED
    await session.commit()


async def unlink(session: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID, actor: str | None) -> None:
    """Undo a wrong link: the sites are released and marked not ours, so the
    daily job does not put the link back. A record change: one receipt."""
    company = await _company(session, tenant_id, company_id)
    rows = (
        await session.scalars(
            select(HubCompanyLink).where(HubCompanyLink.tenant_id == tenant_id, HubCompanyLink.company_id == company.id)
        )
    ).all()
    if not rows:
        return
    ids = [r.hub_company_id for r in rows]
    for row in rows:
        row.company_id = None
        row.relationship = IGNORED
    await session.flush()

    async def _prove_it_landed(_session: AsyncSession, _change) -> None:
        still = await _session.scalar(
            select(HubCompanyLink.id).where(HubCompanyLink.tenant_id == tenant_id, HubCompanyLink.company_id == company.id)
        )
        if still is not None:
            raise RuntimeError("market unlink did not land")

    result = await verification.verify_and_commit(
        session,
        change=ProposedChange(
            tenant_id=tenant_id,
            entity_type="company",
            entity_id=company.id,
            field="hub_company_id",
            proposed_value="",
            source=ConfidenceSource.SELF_REPORTED,
            source_detail=f"unlinked by {actor or 'a recruiter'}: " + ",".join(str(i) for i in ids)[:400],
            confidence=1.0,
        ),
        agent="recruiter_market_unlink",
        apply_hook=_prove_it_landed,
        actor=actor,
    )
    if not result.committed:
        await session.rollback()
        raise RuntimeError(f"market unlink not committed: {result.reason}")
    await session.commit()


# ---------------------------------------------------------------------------
# Open jobs and the careers page, for the company page and the manager page
# ---------------------------------------------------------------------------

#: An employer's own board on an ATS this corpus reads: the board's home page.
_BOARD = {
    "personio": "https://{slug}.jobs.personio.de/",
    "ashby": "https://jobs.ashbyhq.com/{slug}",
    "greenhouse": "https://boards.greenhouse.io/{slug}",
    "lever": "https://jobs.lever.co/{slug}",
    "lever-eu": "https://jobs.eu.lever.co/{slug}",
}
_CAREERS_WORD = re.compile(r"karriere|career|jobs?\b|stellen|bewerb", re.IGNORECASE)


def careers_page(postings: list[tuple[str, str | None, str | None]]) -> dict | None:
    """(source, external_id, BA externeURL) per open ad → the employer's
    careers page: its own ATS board if the corpus reads one, else the host its
    ads link to most (never a job board), as a page or a website."""
    for source, external_id, _link in postings:
        if source in _BOARD and external_id and ":" in external_id:
            # Lever's EU instance: "eu:<slug>:<id>" (adapters/lever.py).
            eu = external_id.startswith("eu:")
            slug = external_id.removeprefix("eu:").split(":", 1)[0]
            board = "lever-eu" if source == "lever" and eu else source
            return {"url": _BOARD[board].format(slug=slug), "kind": "careers"}
    hosts: collections.Counter[str] = collections.Counter()
    for _source, _id, url in postings:
        if not url or not isinstance(url, str):
            continue
        host = (urlparse(url.strip()).hostname or "").lower()
        domain = registrable_domain(host)
        if domain and _usable(domain):
            hosts[host] += 1
    if not hosts:
        return None
    host = hosts.most_common(1)[0][0]
    return {"url": f"https://{host}/", "kind": "careers" if _CAREERS_WORD.search(host) else "website"}


async def open_jobs(session: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID) -> dict:
    """The open jobs the corpus holds for this company — every site of the
    employer it is linked to — newest first, and its careers page."""
    names = (
        await session.scalars(
            select(HubCompany.normalized_name)
            .join(HubCompanyLink, HubCompanyLink.hub_company_id == HubCompany.id)
            .where(HubCompanyLink.tenant_id == tenant_id, HubCompanyLink.company_id == company_id)
            .distinct()
        )
    ).all()
    if not names:
        return {"linked": False, "total": 0, "jobs": [], "careers": None}
    # Every site of the name — a chain's branches — except those this
    # workspace ruled out or another of its companies holds.
    mine = set(
        (
            await session.scalars(
                select(HubCompanyLink.hub_company_id).where(
                    HubCompanyLink.tenant_id == tenant_id, HubCompanyLink.company_id == company_id
                )
            )
        ).all()
    )
    excluded = (await _unavailable(session, tenant_id)) - mine
    base = (
        select(HubJobPosting, HubCompany.city, HubPostingPayload.raw)
        .join(HubCompany, HubCompany.id == HubJobPosting.hub_company_id)
        .outerjoin(HubPostingPayload, HubPostingPayload.hub_job_posting_id == HubJobPosting.id)
        .where(
            HubCompany.normalized_name.in_(names),
            HubCompany.kind == EMPLOYER,
            HubCompany.id.not_in(excluded) if excluded else True,
            HubJobPosting.is_active.is_(True),
        )
    )
    rows = (await session.execute(base.order_by(HubJobPosting.posted_at.desc().nulls_last()).limit(500))).all()
    # One role relayed by several boards counts once (hub/vacancy.py).
    seen: set[str] = set()
    jobs = []
    for posting, city, _raw in rows:
        key = posting.vacancy_key or str(posting.id)
        if key in seen:
            continue
        seen.add(key)
        jobs.append(
            {
                "title": posting.title,
                "city": posting.city or city,
                "posted_at": _aware(posting.posted_at),
                "source": posting.source,
                "url": source_detail_url(posting.source, posting.external_id) or posting.source_url,
            }
        )
    links = [
        (p.source, p.external_id, (raw or {}).get("externeURL") if isinstance(raw, dict) else None)
        for p, _city, raw in rows
    ]
    return {"linked": True, "total": len(jobs), "jobs": jobs[:OPEN_JOBS_LIMIT], "careers": careers_page(links)}


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    return value.replace(tzinfo=dt.UTC) if value is not None and value.tzinfo is None else value
