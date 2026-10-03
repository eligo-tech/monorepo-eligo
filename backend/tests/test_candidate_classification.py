"""Branchen (plural) and the Anstellungsform — the two fields a filter needs.

The real data is why these exist: 618 candidates say "Permanent", 20 say
"Contract, Permanent", and the industries arrive as single labels that
sometimes contain a comma ("Pharma, MedTech und Gesundheitsbranche"). Neither
could be queried, and the obvious fixes — split on the comma, map every
string to something — both produce wrong answers quietly.
"""

from __future__ import annotations

import uuid

from app.core.database import SessionLocal
from app.domain.candidates import service
from app.domain.candidates.employment import normalize_employment_form
from app.domain.candidates.schemas import CandidateCreate, CandidateUpdate

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# The normalizer
# ---------------------------------------------------------------------------


def test_the_sources_own_vocabulary_maps() -> None:
    """Measured against production: these five cover 650 of 849 candidates."""
    assert normalize_employment_form("Permanent") == "festanstellung"
    assert normalize_employment_form("Contract") == "freelance"
    assert normalize_employment_form("Contract, Permanent") == "beides"
    # A befristete Anstellung is still an Anstellung, not freelance work.
    assert normalize_employment_form("Permanent, Temporary") == "festanstellung"
    assert normalize_employment_form("Freelance / Festanstellung") == "beides"


def test_a_phrase_it_cannot_place_stays_unanswered() -> None:
    """Guessing is worse than NULL in a field meant for filtering.

    "Full-time" says how many hours, not under what contract — a freelancer
    works full time too. "Founder" is neither. Both leave the field for the
    recruiter instead of inventing a classification.
    """
    assert normalize_employment_form("Full-time") is None
    assert normalize_employment_form("Founder") is None
    assert normalize_employment_form("") is None
    assert normalize_employment_form(None) is None


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


async def test_a_created_candidate_keeps_every_field_it_was_given() -> None:
    """Regression: `create_candidate` listed its columns by hand, so four
    fields added to the schema were silently dropped on the way to the row —
    the API accepted them, returned 201, and stored nothing."""
    created = await _create(
        CandidateCreate(
            tenant_id=TENANT,
            full_name="Vollständig",
            salary_minimum=92000,
            profile_summary="Senior Backend, 20 Jahre.",
            interview_availability="Mi/Do ab 11 Uhr",
            other_processes="Logistik GmbH, Nürnberg",
        )
    )
    assert created.salary_minimum == 92000
    assert created.profile_summary == "Senior Backend, 20 Jahre."
    assert created.interview_availability == "Mi/Do ab 11 Uhr"
    assert created.other_processes == "Logistik GmbH, Nürnberg"


async def test_a_career_can_span_several_industries() -> None:
    created = await _create(
        CandidateCreate(
            tenant_id=TENANT,
            full_name="Breit aufgestellt",
            industries=["Luft- und Raumfahrt", "Behörden", "Automotive"],
        )
    )
    assert created.industries == ["Luft- und Raumfahrt", "Behörden", "Automotive"]


async def test_one_imported_label_stays_one_label() -> None:
    """NOT split on the comma: "Pharma, MedTech und Gesundheitsbranche" is a
    single taxonomy label, and splitting it invents an industry that nobody
    recorded. This is the shape every import path writes."""
    created = await _create(
        CandidateCreate(
            tenant_id=TENANT,
            full_name="Aus dem Import",
            industries=["Pharma, MedTech und Gesundheitsbranche"],
        )
    )
    assert created.industries == ["Pharma, MedTech und Gesundheitsbranche"]


async def test_the_list_is_the_only_field_of_record() -> None:
    """The single `industry` column is gone from the code (its DROP waits for
    the next deploy). A patch that sets the list is the whole story."""
    created = await _create(
        CandidateCreate(
            tenant_id=TENANT, full_name="Wechselt", industries=["Automotive"]
        )
    )
    async with SessionLocal() as s:
        updated = await service.update_candidate(
            s,
            tenant_id=TENANT,
            candidate_id=created.id,
            patch=CandidateUpdate(industries=["Maschinenbau", "Intralogistik"]),
            editor="test",
        )
    assert updated.industries == ["Maschinenbau", "Intralogistik"]
    assert not hasattr(updated, "industry")


async def _create(data: CandidateCreate):
    async with SessionLocal() as s:
        return await service.create_candidate(s, data=data)


# ---------------------------------------------------------------------------
# Where else they are in process — the BD signal
# ---------------------------------------------------------------------------


async def test_the_same_employer_named_twice_is_one_signal() -> None:
    """The document's reason for asking "wo": whoever interviews the same
    profiles is a possible client. One name is an anecdote; two candidates
    naming it is a company with a hiring need in this niche."""
    await _create(
        CandidateCreate(
            tenant_id=TENANT,
            full_name="Erster",
            other_process_companies=["Trade Republic", "Sixt"],
        )
    )
    await _create(
        CandidateCreate(
            tenant_id=TENANT,
            full_name="Zweiter",
            # Same company, as a recruiter would actually type it.
            other_process_companies=["trade republic GmbH"],
        )
    )

    async with SessionLocal() as s:
        signals = await service.competing_employers(s, tenant_id=TENANT)

    assert [row["candidate_count"] for row in signals] == [2, 1]
    top = signals[0]
    assert top["company"].lower().startswith("trade republic")
    assert sorted(top["candidates"]) == ["Erster", "Zweiter"]


async def test_a_signal_never_leaves_its_tenant() -> None:
    await _create(
        CandidateCreate(
            tenant_id=TENANT, full_name="Unsere", other_process_companies=["Sixt"]
        )
    )
    async with SessionLocal() as s:
        assert await service.competing_employers(s, tenant_id=uuid.uuid4()) == []


async def test_blank_entries_are_not_counted_as_a_company() -> None:
    await _create(
        CandidateCreate(
            tenant_id=TENANT,
            full_name="Mit Leerzeile",
            other_process_companies=["  ", "", "Sixt"],
        )
    )
    async with SessionLocal() as s:
        signals = await service.competing_employers(s, tenant_id=TENANT)
    assert [row["company"] for row in signals] == ["Sixt"]


async def test_the_route_is_not_swallowed_by_the_uuid_path() -> None:
    """`/candidates/competing-employers` must not be read as a candidate id —
    FastAPI matches in declaration order, so the literal comes first."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app as fastapi_app

    await _create(
        CandidateCreate(
            tenant_id=TENANT, full_name="Jemand", other_process_companies=["Sixt"]
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://t"
    ) as client:
        response = await client.get("/api/v1/candidates/competing-employers")

    assert response.status_code == 200
    assert response.json()[0]["company"] == "Sixt"
