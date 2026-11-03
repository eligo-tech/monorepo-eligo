"""The agency finder — Eligo's own business development over the corpus.

Private recruiters (`kind=private_recruiter`, from the nightly pav pass) are
LEADS for Eligo's sales and competitors to every customer, so nothing here is
reachable outside the `agency_finder_tenants` allowlist (router).

Two halves, split by ARCHITECTURE.md RULE 1:

  * `refresh_profiles` — machine-only, run by the nightly job. Reads every
    agency row, posting and ad text, folds branches into one agency
    (`agency_rank.group_key`), lets `agency_rank` decide verdict and score, and
    rebuilds `hub_agency_profiles` in full.
  * `list_profiles` / `profile_detail` — plain reads of that table.

Adoption reuses `service.adopt_company`, so an agency enters Eligo's CRM
through the same verification gate and receipt as any company.
"""

from __future__ import annotations

import collections
import datetime as dt
import uuid

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.hub import agency_rank
from app.domain.hub import domains as site_domains
from app.domain.hub.models import (
    EMPLOYER,
    PRIVATE_RECRUITER,
    HubAgencyProfile,
    HubCompany,
    HubJobPosting,
    HubPostingPayload,
)

logger = get_logger(__name__)

_BATCH = 500
#: Ads shown in the detail view, newest first.
DETAIL_POSTINGS = 50


# ---------------------------------------------------------------------------
# The nightly rebuild
# ---------------------------------------------------------------------------


async def refresh_profiles(session: AsyncSession) -> dict[str, int]:
    """Rebuild every agency profile from the corpus. Idempotent."""
    if session.bind.dialect.name == "postgresql":
        # Two rebuilds at once would both insert every group_key. Serialise
        # them; the lock ends with the transaction.
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('hub_agency_profiles'))"))
    now = dt.datetime.now(dt.UTC)
    companies = (
        await session.execute(
            select(
                HubCompany.id,
                HubCompany.name,
                HubCompany.normalized_name,
                HubCompany.legal_form,
                HubCompany.suspected_natural_person,
                HubCompany.region,
                HubCompany.city,
            ).where(HubCompany.kind == PRIVATE_RECRUITER)
        )
    ).all()
    group_of: dict[uuid.UUID, str] = {}
    members: dict[str, list] = collections.defaultdict(list)
    for row in companies:
        key = agency_rank.group_key(row.name)
        if not key:
            continue
        group_of[row.id] = key
        members[key].append(row)

    facts: dict[str, agency_rank.AgencyFacts] = {}
    open_by_company: collections.Counter = collections.Counter()
    for key, rows in members.items():
        facts[key] = agency_rank.AgencyFacts(
            group_key=key,
            names=sorted({r.name for r in rows}),
            open_postings=0,
            sole_trader=any(
                r.suspected_natural_person
                or (r.legal_form and agency_rank.SMALL_LEGAL_FORMS.match(r.legal_form))
                for r in rows
            ),
        )

    # Postings: counts, fields, recruiter roles. Light columns only.
    week, month = now - dt.timedelta(days=7), now - dt.timedelta(days=28)
    postings = await session.execute(
        select(
            HubJobPosting.id,
            HubJobPosting.hub_company_id,
            HubJobPosting.title,
            HubJobPosting.berufsfeld,
            HubJobPosting.posted_at,
        ).where(
            HubJobPosting.segment == PRIVATE_RECRUITER,
            HubJobPosting.is_active.is_(True),
        )
    )
    for p in postings:
        key = group_of.get(p.hub_company_id)
        if key is None:
            continue
        f = facts[key]
        f.open_postings += 1
        open_by_company[p.hub_company_id] += 1
        if p.berufsfeld:
            f.fields[p.berufsfeld] = f.fields.get(p.berufsfeld, 0) + 1
        posted = p.posted_at
        if posted is not None and posted.tzinfo is None:  # SQLite
            posted = posted.replace(tzinfo=dt.UTC)
        if posted is not None and posted >= week:
            f.new_7d += 1
        if posted is not None and posted >= month:
            f.new_28d += 1
        if p.title and agency_rank.RECRUITER_ROLE.search(p.title):
            f.recruiter_roles += 1
            f.recruiter_posting_ids.append(str(p.id))

    # Ad texts: the heavy part, streamed. This is why it runs in the cron.
    name_of = {row.id: row.name for row in companies}
    seen_domains: dict[str, dict[str, dict]] = collections.defaultdict(dict)
    texts = await session.stream(
        select(HubJobPosting.hub_company_id, HubJobPosting.id, HubPostingPayload.description)
        .join(HubPostingPayload, HubPostingPayload.hub_job_posting_id == HubJobPosting.id)
        .where(
            HubJobPosting.segment == PRIVATE_RECRUITER,
            HubJobPosting.is_active.is_(True),  # the same ads the counts cover
            HubPostingPayload.description.is_not(None),
        )
        .execution_options(yield_per=_BATCH)
    )
    async for company_id, posting_id, body in texts:
        key = group_of.get(company_id)
        if key is None:
            continue
        site_domains.collect(seen_domains[key], posting_id, body)
        signals, domains = agency_rank.text_signals(body, name_of[company_id])
        if "client_phrase" in signals:
            facts[key].phrase_postings += 1
        facts[key].mail_domains |= domains

    # Client signal: the same firm also hires in its own name — under the
    # agency's root or under any branch's full name ("piening saarbruecken").
    group_by_name: dict[str, set[str]] = collections.defaultdict(set)
    for key, rows in members.items():
        group_by_name[key].add(key)
        for r in rows:
            group_by_name[r.normalized_name].add(key)
    names = list(group_by_name)
    for start in range(0, len(names), _BATCH):
        found = await session.execute(
            select(HubCompany.normalized_name).where(
                HubCompany.kind == EMPLOYER,
                HubCompany.normalized_name.in_(names[start : start + _BATCH]),
            )
        )
        for (name,) in found:
            for key in group_by_name[name]:
                facts[key].employer_overlap = True

    # Website candidates. A domain named like a known employer is likely the
    # client's ("autobahn.de" in an agency's ad for Die Autobahn GmbH).
    labels = {d.split(".")[0] for seen in seen_domains.values() for d in seen}
    variants = sorted(
        {
            prefix + v
            for label in labels
            for v in (label, label.replace("-", " "))
            for prefix in ("", "die ", "der ", "das ")
        }
    )
    employer_labels: set[str] = set()
    for start in range(0, len(variants), _BATCH):
        found = await session.execute(
            select(HubCompany.normalized_name).where(
                HubCompany.kind == EMPLOYER,
                HubCompany.normalized_name.in_(variants[start : start + _BATCH]),
            )
        )
        employer_labels |= {name for (name,) in found}

    await session.execute(delete(HubAgencyProfile))
    verdicts: collections.Counter = collections.Counter()
    for key, f in facts.items():
        verdict, why = agency_rank.classify(f)
        points, score_why = agency_rank.score(f)
        rows = members[key]
        primary = max(rows, key=lambda r: (open_by_company[r.id], r.name))
        session.add(
            HubAgencyProfile(
                group_key=key,
                name=primary.name,
                primary_company_id=primary.id,
                company_ids=[str(r.id) for r in rows],
                verdict=verdict,
                score=points,
                open_postings=f.open_postings,
                new_28d=f.new_28d,
                region=primary.region,
                city=primary.city,
                fields=dict(f.fields),
                reasons=why + score_why,
                website_candidates=site_domains.rank(
                    seen_domains.get(key, {}),
                    firm_names=f.names,
                    employer_names=employer_labels,
                    own_names={key, *(r.normalized_name for r in rows)},
                ),
                refreshed_at=now,
            )
        )
        verdicts[verdict] += 1
    await session.commit()
    with_site = sum(1 for k in facts if seen_domains.get(k))
    logger.info(
        "agency profiles rebuilt: %d (%s), website candidates for %d",
        len(facts), dict(verdicts), with_site,
    )
    return {
        "profiles": len(facts),
        **{v: verdicts.get(v, 0) for v in agency_rank.VERDICTS},
        # Measured every night, per the plan: how far domain discovery reaches.
        "with_website_candidate": with_site,
    }


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def _live():
    """Profiles whose primary company still exists — a suppression deletes the
    company at once, the rebuild follows only at night."""
    return select(HubAgencyProfile).join(
        HubCompany, HubCompany.id == HubAgencyProfile.primary_company_id
    )


async def list_profiles(
    session: AsyncSession,
    *,
    verdicts: list[str],
    region: str | None = None,
    berufsfeld: str | None = None,
    include_chains: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[HubAgencyProfile]:
    stmt = _live().where(HubAgencyProfile.verdict.in_(verdicts))
    if not include_chains:
        stmt = stmt.where(HubAgencyProfile.open_postings <= agency_rank.CHAIN_OPEN_POSTINGS)
    if region:
        # The primary branch's state: an agency is listed where it is based.
        stmt = stmt.where(HubAgencyProfile.region == region)
    stmt = stmt.order_by(
        HubAgencyProfile.score.desc(),
        HubAgencyProfile.new_28d.desc(),
        HubAgencyProfile.name,
        HubAgencyProfile.id,
    )
    if not berufsfeld:
        return list((await session.execute(stmt.limit(limit).offset(offset))).scalars().all())
    # `fields` is a JSON object; its keys are matched here to stay portable
    # across Postgres and SQLite. Bounded: one row per agency (thousands).
    rows = (await session.execute(stmt)).scalars().all()
    rows = [r for r in rows if berufsfeld in (r.fields or {})]
    return rows[offset : offset + limit]


async def get_profile(session: AsyncSession, profile_id: uuid.UUID) -> HubAgencyProfile | None:
    return await session.scalar(_live().where(HubAgencyProfile.id == profile_id))


async def profile_detail(
    session: AsyncSession, *, tenant_id: uuid.UUID, profile: HubAgencyProfile
) -> dict:
    from app.domain.hub import service

    ids = [uuid.UUID(i) for i in profile.company_ids]
    branches = (
        await session.execute(
            select(HubCompany).where(HubCompany.id.in_(ids)).order_by(HubCompany.city)
        )
    ).scalars().all()
    live_ids = [b.id for b in branches]
    postings = (
        await session.execute(
            select(HubJobPosting)
            .where(HubJobPosting.hub_company_id.in_(live_ids))
            .order_by(HubJobPosting.is_active.desc(), HubJobPosting.posted_at.desc().nulls_last())
            .limit(DETAIL_POSTINGS)
        )
    ).scalars().all()
    contacts = await service.company_contacts(
        session,
        tenant_id=tenant_id,
        hub_company_id=profile.primary_company_id,
        kind=PRIVATE_RECRUITER,
        company_ids=live_ids,
    )
    return {"profile": profile, "branches": branches, "postings": postings, "contacts": contacts}
