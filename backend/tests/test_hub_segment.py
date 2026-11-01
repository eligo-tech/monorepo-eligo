"""Private recruiters in the corpus — kept apart from employers.

The agency finder (docs/plans/info_hub.md, Phase 0a) ingests private
recruiters (`pav=true`) as LEADS for Eligo's own sales. Every existing
recruiter-facing view is about employers and must not change: an agency there
is a competitor, not a lead, which is why the crawler excluded them before.

Two facts measured on the live source shape this:
  * a listing record carries no agency flag — the segment is known only from
    which filtered query returned it, so it is stamped at ingest;
  * `firma` in a pav ad is sometimes the CLIENT ("Die Autobahn GmbH des
    Bundes"), so a pav posting must never attach to an employer row. Agencies
    get their own identity namespace.

The leak test is behavioural, like `test_operator_endpoints.py`: it walks every
customer-facing GET route under /hub and asserts the agency appears in none,
so a new route cannot forget the filter.
"""

from __future__ import annotations

import datetime as dt

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.domain.hub import service
from app.domain.hub.adapters.base import (
    FetchResult,
    SourcedCompany,
    SourcedPosting,
    SourceQuery,
)
from app.domain.hub.adapters.bundesagentur import BundesagenturAdapter
from app.domain.hub.models import (
    EMPLOYER,
    PRIVATE_RECRUITER,
    HubCompany,
    HubJobPosting,
)
from app.domain.hub.resolution import normalize_company_name
from app.domain.hub.schemas import IngestRequest
from app.main import app
from tests.test_operator_endpoints import DECLARED_OPERATOR_ROUTES, _api_routes

_AGENCY = "Zebrafink Personalberatung"


# ---------------------------------------------------------------------------
# The source query
# ---------------------------------------------------------------------------


def test_employer_queries_still_exclude_agencies() -> None:
    params = BundesagenturAdapter().build_params(SourceQuery(where="Leipzig"))
    assert params["pav"] == "false" and params["zeitarbeit"] == "false"


def test_the_private_recruiter_segment_asks_for_private_recruiters_only() -> None:
    params = BundesagenturAdapter().build_params(
        SourceQuery(where="Leipzig", segment=PRIVATE_RECRUITER)
    )
    # Temp agencies (zeitarbeit) are out of scope: decision 2026-11-02.
    assert params["pav"] == "true" and params["zeitarbeit"] == "false"


def test_the_segment_is_part_of_the_question() -> None:
    employer = IngestRequest(where="Leipzig")
    agency = IngestRequest(where="Leipzig", segment=PRIVATE_RECRUITER)
    # Otherwise `max_age_minutes` would answer the agency pass with the
    # employer pass's observation.
    assert service.query_key(employer) != service.query_key(agency)


def test_an_employer_question_keeps_its_old_key() -> None:
    # Existing observations stay reusable: the default segment adds nothing to
    # the fingerprint.
    import hashlib
    import json

    request = IngestRequest(where="Leipzig")
    legacy = json.dumps(
        {
            "source": request.source,
            "what": None,
            "where": "leipzig",
            "berufsfeld": None,
            "radius_km": None,
            "published_since_days": None,
            "page": 1,
            "size": 100,
            "include_staffing": False,
        },
        sort_keys=True,
    )
    assert service.query_key(request) == hashlib.sha256(legacy.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def _result(firma: str, external_id: str) -> FetchResult:
    return FetchResult(
        source="bundesagentur",
        request_url="https://example.invalid/pc/v6/jobs",
        fetched_at=dt.datetime.now(dt.UTC),
        http_status=200,
        total_available=1,
        postings=[
            SourcedPosting(
                external_id=external_id,
                title="Projektleiter (m/w/d)",
                company=SourcedCompany(
                    name=firma, postal_code="04105", city="Leipzig"
                ),
                postal_code="04105",
                city="Leipzig",
                posted_at=dt.datetime.now(dt.UTC),
            )
        ],
    )


class _Replay:
    name = "bundesagentur"

    def __init__(self, result: FetchResult) -> None:
        self.result = result
        self.queries: list[SourceQuery] = []

    async def fetch(self, query: SourceQuery) -> FetchResult:
        self.queries.append(query)
        return self.result


async def test_an_agency_pass_stamps_company_and_posting() -> None:
    adapter = _Replay(_result(_AGENCY, "pav-1"))
    async with SessionLocal() as s:
        await service.ingest(
            s,
            adapter=adapter,
            request=IngestRequest(segment=PRIVATE_RECRUITER),
        )
        company = await s.scalar(select(HubCompany))
        posting = await s.scalar(select(HubJobPosting))

    assert adapter.queries[0].segment == PRIVATE_RECRUITER
    assert company.kind == PRIVATE_RECRUITER
    assert posting.segment == PRIVATE_RECRUITER
    assert company.open_postings_count == 1


async def test_a_client_named_in_an_agency_ad_never_joins_the_employer_row() -> None:
    client = "Die Autobahn GmbH des Bundes"
    async with SessionLocal() as s:
        await service.ingest(s, adapter=_Replay(_result(client, "emp-1")), request=IngestRequest())
        await service.ingest(
            s,
            adapter=_Replay(_result(client, "pav-1")),
            request=IngestRequest(segment=PRIVATE_RECRUITER),
        )
        rows = (await s.execute(select(HubCompany).order_by(HubCompany.kind))).scalars().all()
        employer_postings = (
            await s.execute(
                select(HubJobPosting).where(HubJobPosting.hub_company_id == rows[0].id)
            )
        ).scalars().all()

    assert [r.kind for r in rows] == [EMPLOYER, PRIVATE_RECRUITER]
    assert rows[0].dedupe_key != rows[1].dedupe_key
    # The employer's own count is untouched by the agency's ad for it.
    assert rows[0].open_postings_count == 1
    assert [p.external_id for p in employer_postings] == ["emp-1"]


# ---------------------------------------------------------------------------
# No customer-facing read shows an agency
# ---------------------------------------------------------------------------


async def _seed() -> tuple[HubCompany, HubCompany]:
    now = dt.datetime.now(dt.UTC)
    async with SessionLocal() as s:
        companies = []
        for name, kind, key in (
            ("Klinikum Musterstadt", EMPLOYER, "emp"),
            (_AGENCY, PRIVATE_RECRUITER, "pav:agency"),
        ):
            row = HubCompany(
                name=name,
                normalized_name=normalize_company_name(name),
                dedupe_key=key,
                resolution_basis="name_place",
                city="Leipzig",
                region="SACHSEN",
                source="bundesagentur",
                kind=kind,
                open_postings_count=1,
                suspected_natural_person=False,
                first_seen_at=now,
                last_seen_at=now,
            )
            s.add(row)
            companies.append(row)
        await s.flush()
        for row, title in ((companies[0], "Pflegefachkraft"), (companies[1], "Zebrafink Recruiter")):
            s.add(
                HubJobPosting(
                    hub_company_id=row.id,
                    title=title,
                    berufsfeld="Krankenpflege",
                    region="SACHSEN",
                    city="Leipzig",
                    source="bundesagentur",
                    external_id=f"x-{row.kind}",
                    content_hash=row.kind,
                    segment=row.kind,
                    first_seen_at=now,
                    last_seen_at=now,
                    is_active=True,
                )
            )
        await s.commit()
        return companies[0], companies[1]


def _customer_hub_gets() -> list[str]:
    paths = []
    for route in _api_routes(app.router):
        if "GET" not in route.methods:
            continue
        path = route.path.removeprefix("/api/v1")
        if not path.startswith("/hub") or ("GET", path) in DECLARED_OPERATOR_ROUTES:
            continue
        paths.append(path)
    return sorted(set(paths))


def test_the_leak_walk_actually_covers_the_hub() -> None:
    # A walk that found nothing would pass vacuously.
    paths = _customer_hub_gets()
    assert "/hub/search" in paths and "/hub/companies/{hub_company_id}" in paths
    assert len(paths) >= 8


@pytest.mark.parametrize("path", _customer_hub_gets())
async def test_no_customer_view_shows_an_agency(path: str) -> None:
    employer, agency = await _seed()
    url = "/api/v1" + path.replace("{hub_company_id}", str(agency.id))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        for query in ("", "?q=zebrafink", "?q=recruiter"):
            response = await c.get(url + query)
            body = response.text
            assert "Zebrafink" not in body, f"{path}{query} shows the agency"
            assert str(agency.id) not in body, f"{path}{query} exposes the agency id"


async def test_the_employer_side_still_answers() -> None:
    # Guards the leak test against passing because every route broke.
    employer, _ = await _seed()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        search = await c.get("/api/v1/hub/search?q=pflegefachkraft")
        one = await c.get(f"/api/v1/hub/companies/{employer.id}")
        stats = (await c.get("/api/v1/hub/stats")).json()
        facets = (await c.get("/api/v1/hub/facets")).json()
    assert "Klinikum Musterstadt" in search.text
    # Counts too: the agency's posting shares the Berufsfeld and region.
    assert facets["berufsfelder"] == [{"value": "Krankenpflege", "count": 1}]
    assert facets["regions"] == [{"value": "SACHSEN", "count": 1}]
    assert one.status_code == 200
    assert stats["companies"] == 1 and stats["open_postings"] == 1


async def test_an_agency_cannot_be_tracked_or_adopted_from_the_employer_path() -> None:
    _, agency = await _seed()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        track = await c.put(f"/api/v1/hub/companies/{agency.id}/track", json={})
        adopt = await c.post(f"/api/v1/hub/companies/{agency.id}/adopt", json={})
    assert track.status_code == 404
    assert adopt.status_code == 404


def test_staffing_cannot_be_mixed_into_the_employer_corpus() -> None:
    # `include_staffing` would ingest agencies stamped as employers — straight
    # into every recruiter-facing view. Agencies come in through `segment`.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        IngestRequest(include_staffing=True)


async def test_an_agency_cannot_be_put_in_a_project() -> None:
    from app.core.config import settings
    from app.domain.projects import service as projects
    from app.domain.projects.schemas import ProjectCreate

    employer, agency = await _seed()
    async with SessionLocal() as s:
        project = await projects.create_project(
            s, tenant_id=settings.default_tenant_id, payload=ProjectCreate(name="Akquise")
        )
        added = await projects.add_companies(
            s,
            tenant_id=settings.default_tenant_id,
            project_id=project.id,
            hub_company_ids=[employer.id, agency.id],
        )
    assert added == 1
