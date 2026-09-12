"""Importing a recruiter's own ATS.

Two things are being protected. The first is idempotency: this is meant to run
on a schedule, and an importer that cannot recognise its own output doubles the
book every night. The second is the boundary — a customer's clients, contacts
and mandates must land in tenant tables and never in the shared corpus.

The payloads below are the real shape, captured from the running client: padded
names ("Stefan " / "Graf"), a null priority, ids as opaque strings.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.domain.atsimport import service as importer
from app.domain.common.enums import ConfidenceSource
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager
from app.integrations import aifind

TENANT = uuid.uuid4()

COMPANIES_PAYLOAD = {
    "data": {
        "companies": {
            "total": 2,
            "hits": [
                {"id": "c1", "name": "Conrad Electronic SE"},
                {"id": "c2", "name": "SSI Schaefer IT Solutions GmbH"},
            ],
        }
    }
}

MANAGERS_PAYLOAD = {
    "data": {
        "managers": {
            "total": 3,
            "hits": [
                {
                    "id": "m1",
                    "first_name": "Stefan ",
                    "last_name": "Graf",
                    "job_title": "Head of IT",
                    "company": {"id": "c1", "name": "Conrad Electronic SE"},
                },
                {
                    "id": "m2",
                    "first_name": "Anna",
                    "last_name": "Bennech",
                    "job_title": None,
                    "company": {"id": "c2", "name": "SSI Schaefer IT Solutions GmbH"},
                },
                # No company: nowhere to hang, must be skipped not invented.
                {
                    "id": "m3",
                    "first_name": "Orphan",
                    "last_name": "Contact",
                    "company": None,
                },
            ],
        }
    }
}

JOBS_PAYLOAD = {
    "data": {
        "jobs": {
            "total": 2,
            "hits": [
                {
                    "id": "j1",
                    "title": "Head of SAP",
                    "priority": None,
                    "isOpen": True,
                    "employment": "Permanent",
                    "added_by": "connect@example.test",
                    "owner": "connect@example.test",
                    "manager": {
                        "id": "m1",
                        "first_name": "Stefan ",
                        "last_name": "Graf",
                    },
                    "company": {"id": "c1", "name": "Conrad Electronic SE"},
                },
                {
                    "id": "j2",
                    "title": "Contract- & Claim Manager (w/m/d)",
                    "priority": "A",
                    "isOpen": False,
                    "employment": "Permanent",
                    "added_by": "connect@example.test",
                    "owner": None,
                    "manager": {
                        "id": "m2",
                        "first_name": "Anna",
                        "last_name": "Bennech",
                    },
                    "company": {"id": "c2", "name": "SSI Schaefer IT Solutions GmbH"},
                },
            ],
        }
    }
}


def _parsed():
    return (
        aifind.parse_companies(COMPANIES_PAYLOAD),
        aifind.parse_managers(MANAGERS_PAYLOAD),
        aifind.parse_jobs(JOBS_PAYLOAD),
    )


# --- the pure parser: no network, no credentials ---------------------------


def test_padded_names_are_squeezed_not_concatenated() -> None:
    """'Stefan ' + 'Graf' must not become 'Stefan  Graf'.

    Naively joined, the same person arrives as a second manager on the next
    import whose only difference is a double space — a duplicate nobody can see.
    """
    managers = aifind.parse_managers(MANAGERS_PAYLOAD)
    assert managers[0].full_name == "Stefan Graf"


def test_a_person_without_a_name_is_not_imported() -> None:
    empty = {
        "data": {
            "managers": {"hits": [{"id": "x", "first_name": " ", "last_name": ""}]}
        }
    }
    assert aifind.parse_managers(empty) == []


def test_an_untitled_mandate_is_skipped() -> None:
    empty = {"data": {"jobs": {"hits": [{"id": "x", "title": "  "}]}}}
    assert aifind.parse_jobs(empty) == []


def test_jobs_carry_their_company_and_manager() -> None:
    jobs = aifind.parse_jobs(JOBS_PAYLOAD)
    assert [j.title for j in jobs] == [
        "Head of SAP",
        "Contract- & Claim Manager (w/m/d)",
    ]
    assert jobs[0].company.name == "Conrad Electronic SE"
    assert jobs[0].manager.full_name == "Stefan Graf"
    assert jobs[0].is_open is True
    assert jobs[1].is_open is False


# --- the import ------------------------------------------------------------


async def test_import_builds_the_company_manager_job_graph() -> None:
    companies, managers, jobs = _parsed()
    async with SessionLocal() as s:
        summary = await importer.import_aifind(
            s, tenant_id=TENANT, companies=companies, managers=managers, jobs=jobs
        )

    assert summary.companies_created == 2
    # m3 has no company and `managers.company_id` is NOT NULL — skipped, never
    # attached to an invented account.
    assert summary.managers_created == 2
    assert summary.jobs_created == 2

    async with SessionLocal() as s:
        job = await s.scalar(
            select(Job).where(Job.tenant_id == TENANT, Job.external_id == "j1")
        )
        manager = await s.get(Manager, job.manager_id)
        company = await s.get(Company, job.client_company_id)
    assert manager.full_name == "Stefan Graf"
    assert company.name == "Conrad Electronic SE"
    assert job.status == "open"


async def test_running_twice_updates_instead_of_duplicating() -> None:
    """THE property. Scheduled and non-idempotent means the book doubles nightly."""
    companies, managers, jobs = _parsed()
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        await importer.import_aifind(
            s, tenant_id=tenant, companies=companies, managers=managers, jobs=jobs
        )
    async with SessionLocal() as s:
        second = await importer.import_aifind(
            s, tenant_id=tenant, companies=companies, managers=managers, jobs=jobs
        )

    assert second.companies_created == 0
    assert second.managers_created == 0
    assert second.jobs_created == 0

    async with SessionLocal() as s:
        counts = {
            "companies": await s.scalar(
                select(func.count(Company.id)).where(Company.tenant_id == tenant)
            ),
            "managers": await s.scalar(
                select(func.count(Manager.id)).where(Manager.tenant_id == tenant)
            ),
            "jobs": await s.scalar(
                select(func.count(Job.id)).where(Job.tenant_id == tenant)
            ),
        }
    assert counts == {"companies": 2, "managers": 2, "jobs": 2}


async def test_a_manager_who_moved_company_follows_the_move() -> None:
    """The most valuable signal in recruiting BD, so it must not be ignored."""
    companies, managers, jobs = _parsed()
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        await importer.import_aifind(
            s, tenant_id=tenant, companies=companies, managers=managers, jobs=jobs
        )

    moved = aifind.parse_managers(
        {
            "data": {
                "managers": {
                    "hits": [
                        {
                            "id": "m1",
                            "first_name": "Stefan",
                            "last_name": "Graf",
                            "job_title": "CTO",
                            "company": {
                                "id": "c2",
                                "name": "SSI Schaefer IT Solutions GmbH",
                            },
                        }
                    ]
                }
            }
        }
    )
    async with SessionLocal() as s:
        summary = await importer.import_aifind(
            s, tenant_id=tenant, companies=companies, managers=moved, jobs=[]
        )
        row = await s.scalar(
            select(Manager).where(
                Manager.tenant_id == tenant, Manager.external_id == "m1"
            )
        )
        new_company = await s.get(Company, row.company_id)

    assert summary.managers_updated == 1
    assert new_company.name == "SSI Schaefer IT Solutions GmbH"
    assert row.role_title == "CTO"


async def test_imported_contacts_owe_no_art14_notice() -> None:
    """Moving the controller's own records between their own systems is not a
    new collection from a third party.

    Marking these as third-party-sourced would queue a notification for every
    person the recruiter already has a working relationship with. Recorded
    explicitly so the judgement is visible and can be reversed.
    """
    companies, managers, jobs = _parsed()
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        await importer.import_aifind(
            s, tenant_id=tenant, companies=companies, managers=managers, jobs=jobs
        )
        rows = list(
            await s.scalars(select(Manager).where(Manager.tenant_id == tenant))
        )

    assert rows
    for row in rows:
        assert row.source == ConfidenceSource.HUMAN_VERIFIED.value
        assert row.art14_outstanding is False
        assert row.source_detail.startswith("aifind:")


async def test_nothing_is_written_to_the_shared_corpus() -> None:
    """The boundary. A customer's book of business is not a public fact."""
    from app.domain.hub.models import HubCompany, HubJobPosting

    companies, managers, jobs = _parsed()
    async with SessionLocal() as s:
        before_companies = await s.scalar(select(func.count(HubCompany.id)))
        before_postings = await s.scalar(select(func.count(HubJobPosting.id)))
        await importer.import_aifind(
            s,
            tenant_id=uuid.uuid4(),
            companies=companies,
            managers=managers,
            jobs=jobs,
        )
        assert await s.scalar(select(func.count(HubCompany.id))) == before_companies
        assert await s.scalar(select(func.count(HubJobPosting.id))) == before_postings


async def test_another_workspace_sees_none_of_it() -> None:
    companies, managers, jobs = _parsed()
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    async with SessionLocal() as s:
        await importer.import_aifind(
            s, tenant_id=mine, companies=companies, managers=managers, jobs=jobs
        )
        count = await s.scalar(
            select(func.count(Manager.id)).where(Manager.tenant_id == theirs)
        )
    assert count == 0


def test_a_field_the_source_types_inconsistently_is_coerced() -> None:
    """`employment` is a scalar on jobs and a LIST on candidates.

    A candidate can be open to several arrangements; a mandate is one thing.
    Assuming the scalar shape drove a DataError on the first real import, 391
    candidates in — the kind of defect only live data produces.

    Joined rather than truncated to the first entry: "open to contract or
    permanent" is the fact, and keeping half of it silently narrows someone's
    availability.
    """
    payload = {
        "data": {
            "candidates": {
                "hits": [
                    {
                        "id": "k1",
                        "first_name": "Tania",
                        "last_name": "Zuniga",
                        "job_title": "Site Reliability Engineer",
                        "employment": ["Contract", "Permanent"],
                        "address": {"zip": "80331"},
                    },
                    {
                        "id": "k2",
                        "first_name": "Samir",
                        "last_name": "Abou Kamal",
                        "job_title": "Senior Project Manager SAP EMEA",
                        "employment": [],
                        "address": None,
                    },
                ]
            }
        }
    }
    first, second = aifind.parse_candidates(payload)
    assert first.employment == "Contract, Permanent"
    assert first.postal_code == "80331"
    # an empty list is absence, not an empty string
    assert second.employment is None
    assert second.postal_code is None


CANDIDATE_DETAIL_PAYLOAD = {
    "data": {
        "candidate": {
            "id": "k1",
            "first_name": "Samir",
            "last_name": "Abou Kamal",
            "sex": None,
            "name_prefix": "",
            "date_of_birth": "1979-05-31T00:00:00.000Z",
            "email": "samir.kamal@example.test",
            "xing_url": "",
            "job_title": "Senior Project Manager SAP EMEA",
            "current_company": "",
            "industry": "",
            "employment": [],
            "skills": ["Agile", "SAP", " ", "data migration"],
            "tags": [],
            "address": {
                "street": "",
                "zip": "",
                "city": "München",
                "country": "Germany",
                "addition": None,
            },
        }
    }
}


def test_detail_gives_the_skills_the_list_query_never_returns() -> None:
    """The reason the detail pass exists.

    A hard filter cannot filter on a job title. The list query returns no skills
    at all, so 391 people were unmatchable until this.
    """
    c = aifind.parse_candidate_detail(CANDIDATE_DETAIL_PAYLOAD)
    assert c is not None
    # a list, not a sentence — the matcher reads individual skills
    assert c.skills == ["Agile", "SAP", "data migration"]
    assert c.email == "samir.kamal@example.test"
    assert c.city == "München"
    assert c.country == "Germany"


def test_a_birth_date_keeps_no_invented_precision() -> None:
    """`date_of_birth` is a String column, so a midnight-UTC timestamp would be
    stored verbatim — precision the record does not have."""
    c = aifind.parse_candidate_detail(CANDIDATE_DETAIL_PAYLOAD)
    assert c.date_of_birth == "1979-05-31"


def test_empty_strings_from_the_source_read_as_absent() -> None:
    """The source returns "" for fields nobody filled in. Stored as-is they
    become empty values that look like answers."""
    c = aifind.parse_candidate_detail(CANDIDATE_DETAIL_PAYLOAD)
    assert c.name_prefix is None
    assert c.xing_url is None
    assert c.current_company is None
    assert c.street is None
    assert c.employment is None


def test_a_detail_reimport_fills_in_rows_the_list_pass_created() -> None:
    """The first import predated the detail pass, so its rows carry a name and a
    title and nothing else. Re-running must enrich them, not skip them because
    they already exist."""
    import asyncio

    async def run():
        tenant = uuid.uuid4()
        thin = aifind.parse_candidates(
            {
                "data": {
                    "candidates": {
                        "hits": [
                            {
                                "id": "k1",
                                "first_name": "Samir",
                                "last_name": "Abou Kamal",
                                "job_title": "Senior Project Manager SAP EMEA",
                                "employment": [],
                                "address": None,
                            }
                        ]
                    }
                }
            }
        )
        async with SessionLocal() as s:
            first = await importer.import_aifind(
                s, tenant_id=tenant, companies=[], managers=[], jobs=[],
                candidates=thin,
            )
        assert first.candidates_created == 1

        rich = [aifind.parse_candidate_detail(CANDIDATE_DETAIL_PAYLOAD)]
        async with SessionLocal() as s:
            second = await importer.import_aifind(
                s, tenant_id=tenant, companies=[], managers=[], jobs=[],
                candidates=rich,
            )
            from app.domain.candidates.models import Candidate

            row = await s.scalar(
                select(Candidate).where(
                    Candidate.tenant_id == tenant, Candidate.external_id == "k1"
                )
            )
        assert second.candidates_created == 0
        assert second.candidates_updated == 1
        assert row.skills == ["Agile", "SAP", "data migration"]
        assert row.email == "samir.kamal@example.test"
        assert row.city == "München"
        assert row.location == "München, Germany"

    asyncio.run(run())


def test_a_failed_detail_call_never_blanks_a_good_record() -> None:
    """Absent in the source is not "delete what we have"."""
    import asyncio

    async def run():
        tenant = uuid.uuid4()
        rich = [aifind.parse_candidate_detail(CANDIDATE_DETAIL_PAYLOAD)]
        async with SessionLocal() as s:
            await importer.import_aifind(
                s, tenant_id=tenant, companies=[], managers=[], jobs=[],
                candidates=rich,
            )
        # the thin list record: everything the detail gave is missing here
        thin = aifind.parse_candidates(
            {
                "data": {
                    "candidates": {
                        "hits": [
                            {
                                "id": "k1",
                                "first_name": "Samir",
                                "last_name": "Abou Kamal",
                                "job_title": "Senior Project Manager SAP EMEA",
                                "employment": [],
                                "address": None,
                            }
                        ]
                    }
                }
            }
        )
        async with SessionLocal() as s:
            await importer.import_aifind(
                s, tenant_id=tenant, companies=[], managers=[], jobs=[],
                candidates=thin,
            )
            from app.domain.candidates.models import Candidate

            row = await s.scalar(
                select(Candidate).where(
                    Candidate.tenant_id == tenant, Candidate.external_id == "k1"
                )
            )
        assert row.email == "samir.kamal@example.test"
        assert row.skills == ["Agile", "SAP", "data migration"]
        assert row.city == "München"

    asyncio.run(run())


MANAGER_DETAIL_PAYLOAD = {
    "data": {
        "manager": {
            "id": "m1",
            "first_name": "Mathias",
            "last_name": "Ams",
            "job_title": "Head of R&D",
            "department": "",
            "industry": "",
            "sex": "M",
            "email": "mathias.ams@example.test",
            "code": "MNGR197",
            "skills": ["Bereichsleitung", "R&D"],
            "tags": ["R&D", "PerSie"],
            "employment": ["Contract"],
            "lastContactAt": "2026-07-03T12:47:44.002Z",
            "company": {"id": "c1", "name": "Conrad Electronic SE"},
            # LISTS, not the singular the profile screen implies
            "telephones": [{"number": "+49 7681 2023947"}, {"number": "+49 999"}],
            "addresses": [
                {
                    "street": "Erwin-Sick-Straße 1",
                    "zip": "79183",
                    "city": "Waldkirch",
                    "country": "Germany",
                }
            ],
        }
    }
}

NOTES_PAYLOAD = {
    "data": {
        "contactNotes": {
            "total": 2,
            "notes": [
                {
                    "id": "n1",
                    "note": "T: Neuer AP ist Andreas Hagel für die Projekte.",
                    "category": "BD Call",
                    "createdAt": "2026-07-03T12:47:43.992Z",
                },
                {
                    "id": "n2",
                    "note": "Unternehmenskontext & Fachbereich.",
                    "category": "Meeting Notes",
                    "createdAt": "2026-02-10T11:01:31.857Z",
                },
                # a dated blank is not a record
                {"id": "n3", "note": "  ", "category": "BD Call", "createdAt": None},
            ],
        }
    }
}


def test_manager_detail_reads_the_list_shaped_contact_fields() -> None:
    """`telephones` and `addresses` are LISTS even though the profile shows one.

    Reading them as objects returns nothing and looks exactly like a contact
    with no phone number — a silent empty import rather than an error.
    """
    notes = aifind.parse_notes(NOTES_PAYLOAD)
    m = aifind.parse_manager_detail(MANAGER_DETAIL_PAYLOAD, notes)
    assert m is not None
    assert m.phone == "+49 7681 2023947"
    assert m.city == "Waldkirch"
    assert m.postal_code == "79183"
    assert m.code == "MNGR197"
    # "Looks for: Contract" — a list in the source, one line in the UI
    assert m.looks_for == "Contract"
    assert m.skills == ["Bereichsleitung", "R&D"]
    assert m.tags == ["R&D", "PerSie"]
    assert m.department is None  # "" is absence, not an answer


def test_notes_drop_the_blank_ones() -> None:
    notes = aifind.parse_notes(NOTES_PAYLOAD)
    assert [n.category for n in notes] == ["BD Call", "Meeting Notes"]
    assert notes[0].text.startswith("T: Neuer AP")


def test_importing_notes_twice_does_not_replay_the_conversation() -> None:
    """Notes are append-only in effect: a second run must add nothing.

    Without an external id on the interaction, every import would write the same
    three calls again, and a contact history that grows on its own is worse than
    none — it cannot be read.
    """
    import asyncio

    async def run():
        tenant = uuid.uuid4()
        companies = aifind.parse_companies(COMPANIES_PAYLOAD)
        detailed = [
            aifind.parse_manager_detail(
                MANAGER_DETAIL_PAYLOAD, aifind.parse_notes(NOTES_PAYLOAD)
            )
        ]
        async with SessionLocal() as s:
            first = await importer.import_aifind(
                s, tenant_id=tenant, companies=companies, managers=detailed, jobs=[]
            )
        async with SessionLocal() as s:
            second = await importer.import_aifind(
                s, tenant_id=tenant, companies=companies, managers=detailed, jobs=[]
            )
            from app.domain.managers.models import ManagerInteraction

            total = await s.scalar(
                select(func.count(ManagerInteraction.id)).where(
                    ManagerInteraction.tenant_id == tenant
                )
            )
            row = await s.scalar(
                select(Manager).where(
                    Manager.tenant_id == tenant, Manager.external_id == "m1"
                )
            )
        assert first.notes_created == 2
        assert second.notes_created == 0
        assert total == 2
        # the detail landed on the row, not just in the summary
        assert row.phone == "+49 7681 2023947"
        assert row.external_code == "MNGR197"
        assert row.looks_for == "Contract"
        assert row.last_contact_at is not None

    asyncio.run(run())


def test_the_sources_own_category_is_kept_verbatim() -> None:
    """"BD Call" is the recruiter's word for it. Mapping it onto our
    InteractionType enum would turn a chosen category into a near-miss."""
    import asyncio

    async def run():
        tenant = uuid.uuid4()
        companies = aifind.parse_companies(COMPANIES_PAYLOAD)
        detailed = [
            aifind.parse_manager_detail(
                MANAGER_DETAIL_PAYLOAD, aifind.parse_notes(NOTES_PAYLOAD)
            )
        ]
        async with SessionLocal() as s:
            await importer.import_aifind(
                s, tenant_id=tenant, companies=companies, managers=detailed, jobs=[]
            )
            from app.domain.managers.models import ManagerInteraction

            kinds = list(
                await s.scalars(
                    select(ManagerInteraction.interaction_type).where(
                        ManagerInteraction.tenant_id == tenant
                    )
                )
            )
        assert sorted(kinds) == ["BD Call", "Meeting Notes"]

    asyncio.run(run())
