"""Project business logic.

Reads join back to the shared corpus and to this workspace's own rows rather
than copying either: a project stores a name and a set of corpus ids, so the
company's sites, open roles and contacts are always the current answer.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.hub.models import HubCompany, HubCompanyLink, HubJobPosting
from app.domain.managers.models import Manager
from app.domain.projects.models import Project, ProjectCompany
from app.domain.projects.schemas import (
    AddContactRequest,
    ProjectCreate,
    ProjectUpdate,
)


class DuplicateName(Exception):
    """A project with this name already exists in this workspace."""


async def _name_taken(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    name: str,
    exclude: uuid.UUID | None = None,
) -> bool:
    stmt = select(Project.id).where(
        Project.tenant_id == tenant_id, func.lower(Project.name) == name.lower()
    )
    if exclude is not None:
        stmt = stmt.where(Project.id != exclude)
    return (await session.scalar(stmt)) is not None


async def create_project(
    session: AsyncSession, *, tenant_id: uuid.UUID, payload: ProjectCreate
) -> Project:
    name = payload.name.strip()
    if await _name_taken(session, tenant_id=tenant_id, name=name):
        raise DuplicateName(name)
    project = Project(tenant_id=tenant_id, name=name, note=payload.note)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


async def update_project(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: ProjectUpdate,
) -> Project | None:
    project = await get_project(session, tenant_id=tenant_id, project_id=project_id)
    if project is None:
        return None
    if payload.name is not None:
        name = payload.name.strip()
        if await _name_taken(
            session, tenant_id=tenant_id, name=name, exclude=project_id
        ):
            raise DuplicateName(name)
        project.name = name
    if payload.note is not None:
        project.note = payload.note or None
    await session.commit()
    await session.refresh(project)
    return project


async def get_project(
    session: AsyncSession, *, tenant_id: uuid.UUID, project_id: uuid.UUID
) -> Project | None:
    return await session.scalar(
        select(Project).where(
            Project.id == project_id, Project.tenant_id == tenant_id
        )
    )


async def delete_project(
    session: AsyncSession, *, tenant_id: uuid.UUID, project_id: uuid.UUID
) -> bool:
    """Remove the grouping. The companies themselves are corpus rows and the
    contacts are this workspace's own — neither is touched."""
    project = await get_project(session, tenant_id=tenant_id, project_id=project_id)
    if project is None:
        return False
    # Delete the memberships explicitly rather than leaning on ON DELETE
    # CASCADE: SQLite enforces foreign keys only when asked to, so relying on
    # the database here would leave orphan rows in CI while Postgres cleaned up.
    await session.execute(
        delete(ProjectCompany).where(
            ProjectCompany.project_id == project_id,
            ProjectCompany.tenant_id == tenant_id,
        )
    )
    await session.delete(project)
    await session.commit()
    return True


async def _employer_rollup(
    session: AsyncSession, *, hub_company_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict]:
    """Corpus facts per anchor company, summed across the employer's sites.

    Tracking and projects store ONE corpus row per employer (the site that was
    on screen), while the employer is all rows sharing `normalized_name`.
    """
    if not hub_company_ids:
        return {}
    anchors = {
        c.id: c
        for c in (
            await session.execute(
                select(HubCompany).where(HubCompany.id.in_(hub_company_ids))
            )
        ).scalars()
    }
    names = {c.normalized_name for c in anchors.values()}
    sites = (
        await session.execute(
            select(HubCompany.id, HubCompany.normalized_name, HubCompany.city).where(
                HubCompany.normalized_name.in_(names)
            )
        )
    ).all()
    name_of = {row.id: row.normalized_name for row in sites}
    postings = (
        await session.execute(
            select(
                HubJobPosting.hub_company_id,
                func.count(HubJobPosting.id),
                func.max(HubJobPosting.posted_at),
            )
            .where(
                HubJobPosting.hub_company_id.in_(list(name_of)),
                HubJobPosting.is_active.is_(True),
            )
            .group_by(HubJobPosting.hub_company_id)
        )
    ).all()

    per_name: dict[str, dict] = {
        n: {"sites": 0, "cities": [], "open_roles": 0, "last_posted_at": None}
        for n in names
    }
    for row in sites:
        entry = per_name[row.normalized_name]
        entry["sites"] += 1
        if row.city and row.city not in entry["cities"]:
            entry["cities"].append(row.city)
    for company_id, count, last in postings:
        entry = per_name[name_of[company_id]]
        entry["open_roles"] += count
        if last is not None:
            last = last if last.tzinfo else last.replace(tzinfo=dt.UTC)
            if entry["last_posted_at"] is None or last > entry["last_posted_at"]:
                entry["last_posted_at"] = last

    return {
        anchor_id: {
            "name": anchor.name,
            "website_domain": anchor.website_domain,
            **per_name[anchor.normalized_name],
        }
        for anchor_id, anchor in anchors.items()
    }


async def _contacts_by_company(
    session: AsyncSession, *, tenant_id: uuid.UUID, company_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[dict]]:
    """The people attached to each of this workspace's companies.

    Read from `managers` every time rather than denormalised onto the project:
    a contact's phone number, provenance and Art. 14 state belong to the
    record, and a project must not be able to show a stale copy of them.
    """
    if not company_ids:
        return {}
    rows = (
        await session.execute(
            select(Manager)
            .where(
                Manager.tenant_id == tenant_id,
                Manager.company_id.in_(company_ids),
                Manager.status == "active",
            )
            .order_by(Manager.created_at)
        )
    ).scalars()
    out: dict[uuid.UUID, list[dict]] = {}
    for manager in rows:
        out.setdefault(manager.company_id, []).append(
            {
                "id": manager.id,
                "full_name": manager.full_name,
                "role_title": manager.role_title,
                "email": manager.email,
                "phone": manager.phone,
                "linkedin_url": manager.linkedin_url,
                "source": manager.source,
                "art14_outstanding": manager.art14_outstanding,
            }
        )
    return out


async def _adopted_and_contacts(
    session: AsyncSession, *, tenant_id: uuid.UUID, hub_company_ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, uuid.UUID], dict[uuid.UUID, int]]:
    """(hub_company_id → adopted company id, company id → contact count).

    The link table is where a corpus company becomes one of this workspace's
    own; contacts hang off that row, never off the corpus.
    """
    if not hub_company_ids:
        return {}, {}
    links = (
        await session.execute(
            select(HubCompanyLink.hub_company_id, HubCompanyLink.company_id).where(
                HubCompanyLink.tenant_id == tenant_id,
                HubCompanyLink.hub_company_id.in_(hub_company_ids),
                HubCompanyLink.company_id.is_not(None),
            )
        )
    ).all()
    adopted = {hub_id: company_id for hub_id, company_id in links}
    counts: dict[uuid.UUID, int] = {}
    if adopted:
        rows = (
            await session.execute(
                select(Manager.company_id, func.count(Manager.id))
                .where(
                    Manager.tenant_id == tenant_id,
                    Manager.company_id.in_(list(adopted.values())),
                )
                .group_by(Manager.company_id)
            )
        ).all()
        counts = dict(rows)
    return adopted, counts


async def list_projects(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[dict]:
    """Every project with the counts a list needs, newest first."""
    projects = list(
        (
            await session.execute(
                select(Project)
                .where(Project.tenant_id == tenant_id)
                .order_by(Project.created_at.desc())
            )
        ).scalars()
    )
    if not projects:
        return []
    memberships = (
        await session.execute(
            select(ProjectCompany.project_id, ProjectCompany.hub_company_id).where(
                ProjectCompany.tenant_id == tenant_id,
                ProjectCompany.project_id.in_([p.id for p in projects]),
            )
        )
    ).all()
    hub_ids = list({m.hub_company_id for m in memberships})
    rollup = await _employer_rollup(session, hub_company_ids=hub_ids)
    adopted, contacts = await _adopted_and_contacts(
        session, tenant_id=tenant_id, hub_company_ids=hub_ids
    )

    out = []
    for project in projects:
        mine = [m.hub_company_id for m in memberships if m.project_id == project.id]
        with_contact = sum(
            1
            for hub_id in mine
            if contacts.get(adopted.get(hub_id), 0) > 0  # type: ignore[arg-type]
        )
        out.append(
            {
                "id": project.id,
                "name": project.name,
                "note": project.note,
                "company_count": len(mine),
                "companies_with_contact": with_contact,
                "open_roles": sum(
                    rollup.get(hub_id, {}).get("open_roles", 0) for hub_id in mine
                ),
                "created_at": project.created_at,
                "updated_at": project.updated_at,
            }
        )
    return out


async def project_detail(
    session: AsyncSession, *, tenant_id: uuid.UUID, project_id: uuid.UUID
) -> dict | None:
    project = await get_project(session, tenant_id=tenant_id, project_id=project_id)
    if project is None:
        return None
    rows = list(
        (
            await session.execute(
                select(ProjectCompany)
                .where(
                    ProjectCompany.tenant_id == tenant_id,
                    ProjectCompany.project_id == project_id,
                )
                .order_by(ProjectCompany.created_at)
            )
        ).scalars()
    )
    hub_ids = [r.hub_company_id for r in rows]
    rollup = await _employer_rollup(session, hub_company_ids=hub_ids)
    adopted, _ = await _adopted_and_contacts(
        session, tenant_id=tenant_id, hub_company_ids=hub_ids
    )
    contacts_by_company = await _contacts_by_company(
        session, tenant_id=tenant_id, company_ids=list(adopted.values())
    )

    companies = []
    for row in rows:
        facts = rollup.get(row.hub_company_id)
        if facts is None:
            continue  # corpus row gone; the membership is meaningless without it
        company_id = adopted.get(row.hub_company_id)
        people = contacts_by_company.get(company_id, []) if company_id else []
        companies.append(
            {
                "hub_company_id": row.hub_company_id,
                "name": facts["name"],
                "website_domain": facts["website_domain"],
                "cities": facts["cities"][:6],
                "city_count": len(facts["cities"]),
                "sites": facts["sites"],
                "open_roles": facts["open_roles"],
                "last_posted_at": facts["last_posted_at"],
                "note": row.note,
                "added_at": row.created_at,
                "company_id": company_id,
                "contacts": people,
                "contact_count": len(people),
            }
        )
    companies.sort(key=lambda c: (-c["open_roles"], c["name"].lower()))
    return {
        "id": project.id,
        "name": project.name,
        "note": project.note,
        "company_count": len(companies),
        "companies_with_contact": sum(1 for c in companies if c["contact_count"]),
        "open_roles": sum(c["open_roles"] for c in companies),
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "companies": companies,
    }


async def add_companies(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    hub_company_ids: list[uuid.UUID],
) -> int:
    """Put corpus companies in the project. Idempotent; returns how many were
    new. Unknown corpus ids are ignored rather than failing the whole call."""
    project = await get_project(session, tenant_id=tenant_id, project_id=project_id)
    if project is None:
        raise ValueError("project not found")
    known = set(
        (
            await session.execute(
                select(HubCompany.id).where(HubCompany.id.in_(hub_company_ids))
            )
        ).scalars()
    )
    already = set(
        (
            await session.execute(
                select(ProjectCompany.hub_company_id).where(
                    ProjectCompany.project_id == project_id,
                    ProjectCompany.tenant_id == tenant_id,
                )
            )
        ).scalars()
    )
    added = 0
    for hub_company_id in hub_company_ids:
        if hub_company_id not in known or hub_company_id in already:
            continue
        session.add(
            ProjectCompany(
                tenant_id=tenant_id,
                project_id=project_id,
                hub_company_id=hub_company_id,
            )
        )
        already.add(hub_company_id)
        added += 1
    await session.commit()
    return added


async def add_contact(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    hub_company_id: uuid.UUID,
    payload: "AddContactRequest",
) -> "Manager":
    """Attach a person to a company in this project — the enrichment step.

    The company must be one of this workspace's own before a person can hang
    off it, so a company still only watched is adopted first. That crossing
    goes through the verification gate and leaves a receipt exactly as it does
    from Markt; this is the same door, not a second one.
    """
    from app.domain.hub import service as hub_service

    membership = await session.scalar(
        select(ProjectCompany).where(
            ProjectCompany.tenant_id == tenant_id,
            ProjectCompany.project_id == project_id,
            ProjectCompany.hub_company_id == hub_company_id,
        )
    )
    if membership is None:
        raise ValueError("company is not in this project")

    adopted, _ = await _adopted_and_contacts(
        session, tenant_id=tenant_id, hub_company_ids=[hub_company_id]
    )
    company_id = adopted.get(hub_company_id)
    if company_id is None:
        company, _link, _manager = await hub_service.adopt_company(
            session, tenant_id=tenant_id, hub_company_id=hub_company_id
        )
        company_id = company.id

    manager = Manager(
        tenant_id=tenant_id,
        company_id=company_id,
        full_name=payload.full_name.strip(),
        role_title=payload.role_title,
        email=payload.email or None,
        phone=payload.phone or None,
        linkedin_url=payload.linkedin_url or None,
        source=payload.source.value,
        source_detail=payload.source_detail,
    )
    session.add(manager)
    await session.commit()
    await session.refresh(manager)
    return manager


async def remove_company(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    hub_company_id: uuid.UUID,
) -> bool:
    row = await session.scalar(
        select(ProjectCompany).where(
            ProjectCompany.tenant_id == tenant_id,
            ProjectCompany.project_id == project_id,
            ProjectCompany.hub_company_id == hub_company_id,
        )
    )
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def candidate_companies(
    session: AsyncSession, *, tenant_id: uuid.UUID, project_id: uuid.UUID
) -> list[dict]:
    """Watched employers not yet in this project — what "add" offers."""
    in_project = set(
        (
            await session.execute(
                select(ProjectCompany.hub_company_id).where(
                    ProjectCompany.tenant_id == tenant_id,
                    ProjectCompany.project_id == project_id,
                )
            )
        ).scalars()
    )
    watched = [
        hub_id
        for hub_id in (
            await session.execute(
                select(HubCompanyLink.hub_company_id).where(
                    HubCompanyLink.tenant_id == tenant_id,
                    HubCompanyLink.relationship != "ignored",
                )
            )
        ).scalars()
        if hub_id not in in_project
    ]
    rollup = await _employer_rollup(session, hub_company_ids=watched)
    out = [
        {
            "hub_company_id": hub_id,
            "name": facts["name"],
            "cities": facts["cities"][:4],
            "open_roles": facts["open_roles"],
        }
        for hub_id, facts in rollup.items()
    ]
    out.sort(key=lambda c: (-c["open_roles"], c["name"].lower()))
    return out
