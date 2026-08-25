"""Hub ingestion — parsing, deduplication, idempotency and the gate.

Runs entirely offline: the adapter is split into a pure `parse_response` and a
thin HTTP wrapper, so CI exercises the real parser against a real captured
Bundesagentur payload (tests/fixtures/bundesagentur_jobs.json) with no network.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.hub import service
from app.domain.hub.adapters.base import (
    FetchResult,
    SourcedCompany,
    SourcedPosting,
    SourceQuery,
)
from app.domain.hub.adapters.bundesagentur import BundesagenturAdapter, parse_response
from app.domain.hub.gate import PreconditionFailed, check_posting
from app.domain.hub.models import HubCompany, HubJobPosting, HubObservation
from app.domain.hub.schemas import IngestRequest
from app.main import app

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "bundesagentur_jobs.json"


def _payload() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _fetch_result() -> FetchResult:
    return parse_response(
        _payload(),
        request_url="https://example.invalid/pc/v6/jobs?was=Softwareentwickler",
        fetched_at=dt.datetime.now(dt.UTC),
    )


class StubAdapter:
    """A `SourceAdapter` that replays a captured payload instead of doing I/O."""

    name = "bundesagentur"

    def __init__(self, result: FetchResult | None = None) -> None:
        self._result = result

    async def fetch(self, query: SourceQuery) -> FetchResult:
        return self._result if self._result is not None else _fetch_result()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parse_maps_the_real_payload_shape() -> None:
    result = _fetch_result()
    payload = _payload()

    assert result.source == "bundesagentur"
    assert result.total_available == payload["maxErgebnisse"]
    assert len(result.postings) == len(payload["ergebnisliste"])
    assert result.content_hash

    for posting in result.postings:
        assert posting.external_id and posting.title and posting.company.name
        # The agency geocodes every record — the hub never needs to for these.
        assert posting.latitude is not None and posting.longitude is not None
        assert posting.country == "DEUTSCHLAND"


def test_parse_returns_timezone_aware_dates() -> None:
    for posting in _fetch_result().postings:
        if posting.posted_at is not None:
            assert posting.posted_at.tzinfo is not None


def test_parse_drops_records_that_cannot_be_attributed() -> None:
    payload = _payload()
    payload["ergebnisliste"] = [
        {**payload["ergebnisliste"][0], "firma": ""},              # no employer
        {**payload["ergebnisliste"][1], "referenznummer": None},   # not deduplicable
        payload["ergebnisliste"][2],                               # keeper
    ]
    result = parse_response(
        payload, request_url="https://example.invalid", fetched_at=dt.datetime.now(dt.UTC)
    )
    assert len(result.postings) == 1


def test_staffing_agencies_are_excluded_by_default() -> None:
    params = BundesagenturAdapter().build_params(SourceQuery(where="Berlin"))
    # Temp agencies and private recruiters are competitors, not leads.
    assert params["zeitarbeit"] == "false"
    assert params["pav"] == "false"

    opted_in = BundesagenturAdapter().build_params(
        SourceQuery(where="Berlin", include_staffing=True)
    )
    assert "zeitarbeit" not in opted_in and "pav" not in opted_in


def test_page_size_is_clamped_to_the_api_maximum() -> None:
    assert BundesagenturAdapter().build_params(SourceQuery(size=5000))["size"] == 100


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


def _posting(**overrides) -> SourcedPosting:
    base = dict(
        external_id="ref-1",
        title="Softwareentwickler",
        company=SourcedCompany(name="Muster GmbH", postal_code="10115", city="Berlin"),
    )
    company = overrides.pop("company", None)
    posting = SourcedPosting(**{**base, **overrides})
    if company is not None:
        posting.company = company
    return posting


def test_gate_accepts_a_complete_record() -> None:
    ok, reason = check_posting(_posting())
    assert ok, reason


@pytest.mark.parametrize(
    "kwargs, fragment",
    [
        ({"title": "  "}, "empty title"),
        ({"external_id": ""}, "external id"),
        ({"company": SourcedCompany(name="")}, "employer name"),
        ({"company": SourcedCompany(name="Muster GmbH")}, "resolvable identity"),
        ({"source_url": "javascript:alert(1)"}, "absolute URL"),
    ],
)
def test_gate_rejects_and_names_the_reason(kwargs, fragment) -> None:
    ok, reason = check_posting(_posting(**kwargs))
    assert not ok
    assert fragment in reason


def test_gate_rejects_a_posting_dated_in_the_future() -> None:
    future = dt.datetime.now(dt.UTC) + dt.timedelta(days=30)
    ok, reason = check_posting(_posting(posted_at=future))
    assert not ok and "future" in reason


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


@pytest.fixture
def tenant() -> uuid.UUID:
    return settings.default_tenant_id


async def _ingest(adapter: StubAdapter, tenant: uuid.UUID | None = None):
    """Ingest writes the SHARED corpus, so it takes no tenant."""
    async with SessionLocal() as session:
        return await service.ingest(
            session,
            adapter=adapter,
            request=IngestRequest(source="bundesagentur", where="Berlin"),
        )


async def test_ingest_deduplicates_employers_across_postings(tenant) -> None:
    summary = await _ingest(StubAdapter(), tenant)

    assert summary.postings_created == len(_fetch_result().postings)
    assert set(summary.posting_external_ids_created) == {
        posting.external_id for posting in _fetch_result().postings
    }
    assert not summary.rejected
    # The fixture contains employers posting several roles, so the corpus must
    # hold strictly fewer companies than postings.
    assert 0 < summary.companies_created < summary.postings_created
    assert summary.companies_matched == 0  # nothing pre-existing on a fresh DB

    async with SessionLocal() as session:
        companies = (await session.scalar(select(func.count(HubCompany.id)))) or 0
        postings = (await session.scalar(select(func.count(HubJobPosting.id)))) or 0
        signal_total = (
            await session.scalar(select(func.sum(HubCompany.open_postings_count)))
        ) or 0

    assert companies == summary.companies_created
    assert postings == summary.postings_created
    # The denormalized BD signal must agree with the postings actually stored.
    assert signal_total == postings


async def test_ingest_is_idempotent(tenant) -> None:
    first = await _ingest(StubAdapter(), tenant)
    second = await _ingest(StubAdapter(), tenant)

    assert second.postings_created == 0
    assert second.posting_external_ids_created == []
    assert second.postings_updated == first.postings_created
    assert second.companies_created == 0
    assert second.companies_matched == first.companies_created

    async with SessionLocal() as session:
        postings = (await session.scalar(select(func.count(HubJobPosting.id)))) or 0
        companies = (await session.scalar(select(func.count(HubCompany.id)))) or 0
    assert postings == first.postings_created
    assert companies == first.companies_created


async def test_every_posting_links_to_the_observation_that_produced_it(tenant) -> None:
    summary = await _ingest(StubAdapter(), tenant)

    async with SessionLocal() as session:
        observation = await session.get(HubObservation, summary.observation_id)
        orphans = (
            await session.scalar(
                select(func.count(HubJobPosting.id)).where(
                    HubJobPosting.observation_id.is_(None)
                )
            )
        ) or 0

    assert observation is not None
    assert observation.record_count == summary.fetched
    assert observation.total_available == summary.total_available
    assert orphans == 0  # every claim traces back to a retrieval


async def test_a_refused_fetch_blocks_ingest_but_still_leaves_evidence(tenant) -> None:
    refused = FetchResult(
        source="bundesagentur",
        request_url="https://example.invalid/blocked",
        fetched_at=dt.datetime.now(dt.UTC),
        http_status=200,
        robots_allowed=False,
    )

    with pytest.raises(PreconditionFailed):
        await _ingest(StubAdapter(refused), tenant)

    async with SessionLocal() as session:
        rows = (await session.execute(select(HubObservation))).scalars().all()

    # The refusal survives the rolled-back request: a refusal is evidence too.
    assert len(rows) == 1
    assert rows[0].robots_allowed is False
    assert rows[0].record_count == 0


async def test_a_non_200_fetch_is_recorded_and_rejected(tenant) -> None:
    failed = FetchResult(
        source="bundesagentur",
        request_url="https://example.invalid/boom",
        fetched_at=dt.datetime.now(dt.UTC),
        http_status=503,
    )
    with pytest.raises(PreconditionFailed):
        await _ingest(StubAdapter(failed), tenant)

    async with SessionLocal() as session:
        row = (await session.execute(select(HubObservation))).scalars().one()
    assert row.http_status == 503


async def test_the_corpus_is_shared_not_per_tenant(tenant) -> None:
    """One crawl serves every workspace — that is the point of a shared basis."""
    await _ingest(StubAdapter(), tenant)

    async with SessionLocal() as session:
        company = (await session.execute(select(HubCompany))).scalars().first()
        posting = (await session.execute(select(HubJobPosting))).scalars().first()
        observation = (await session.execute(select(HubObservation))).scalars().one()

    # Public facts carry no owner. If tenant_id ever comes back onto these
    # tables, the shared basis has silently become N private copies again.
    for row in (company, posting, observation):
        assert not hasattr(row, "tenant_id"), type(row).__name__


async def test_a_second_ingest_does_not_duplicate_for_another_caller(tenant) -> None:
    first = await _ingest(StubAdapter(), tenant)
    second = await _ingest(StubAdapter(), uuid.uuid4())  # a different workspace

    # The corpus is shared, so the second caller finds everything already there
    # rather than creating a parallel copy.
    assert second.companies_created == 0
    assert second.companies_matched == first.companies_created
    async with SessionLocal() as session:
        assert (await session.scalar(select(func.count(HubCompany.id)))) == (
            first.companies_created
        )


# ---------------------------------------------------------------------------
# Freshness — why a per-user refresh button is safe on a shared corpus
# ---------------------------------------------------------------------------


class CountingAdapter(StubAdapter):
    """Counts how many times the source was actually asked."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def fetch(self, query: SourceQuery) -> FetchResult:
        self.calls += 1
        return await super().fetch(query)


async def _ingest_with(adapter, **overrides):
    async with SessionLocal() as session:
        return await service.ingest(
            session,
            adapter=adapter,
            request=IngestRequest(source="bundesagentur", where="Berlin", **overrides),
        )


def test_the_same_slice_produces_the_same_query_key() -> None:
    a = IngestRequest(source="bundesagentur", where="Berlin", radius_km=25)
    b = IngestRequest(source="bundesagentur", where="  berlin ", radius_km=25)
    # Two recruiters typing the same city differently ask the same question.
    assert service.query_key(a) == service.query_key(b)
    # A different page is a different question.
    assert service.query_key(a) != service.query_key(
        IngestRequest(source="bundesagentur", where="Berlin", radius_km=25, page=2)
    )


async def test_a_fresh_slice_is_reused_instead_of_refetched() -> None:
    adapter = CountingAdapter()
    first = await _ingest_with(adapter, max_age_minutes=60)
    assert adapter.calls == 1
    assert first.skipped is False
    assert first.postings_created > 0

    # A second workspace pressing refresh must NOT hit the public source again.
    second = await _ingest_with(adapter, max_age_minutes=60)
    assert adapter.calls == 1, "the source was called twice for one slice"
    assert second.skipped is True
    assert "already current" in (second.skipped_reason or "")
    assert second.postings_created == 0
    # It reports the earlier fetch's evidence, not a fabricated empty one.
    assert second.observation_id == first.observation_id
    assert second.fetched == first.fetched


async def test_no_max_age_always_fetches() -> None:
    """A scheduled backfill wants the real thing, not a cached answer."""
    adapter = CountingAdapter()
    await _ingest_with(adapter)
    await _ingest_with(adapter)
    assert adapter.calls == 2


async def test_a_stale_slice_is_refetched() -> None:
    adapter = CountingAdapter()
    await _ingest_with(adapter, max_age_minutes=60)

    # Age the observation past the window.
    async with SessionLocal() as session:
        obs = (await session.execute(select(HubObservation))).scalars().one()
        obs.fetched_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=3)
        await session.commit()

    again = await _ingest_with(adapter, max_age_minutes=60)
    assert adapter.calls == 2
    assert again.skipped is False


async def test_a_failed_fetch_is_never_reused_as_fresh() -> None:
    """Caching a 503 would turn one outage into an hour of silent staleness."""
    failed = FetchResult(
        source="bundesagentur",
        request_url="https://example.invalid/boom",
        fetched_at=dt.datetime.now(dt.UTC),
        http_status=503,
    )
    with pytest.raises(PreconditionFailed):
        await _ingest_with(StubAdapter(failed), max_age_minutes=60)

    adapter = CountingAdapter()
    summary = await _ingest_with(adapter, max_age_minutes=60)
    assert adapter.calls == 1
    assert summary.skipped is False


# ---------------------------------------------------------------------------
# Staleness — what a delta crawl cannot see
# ---------------------------------------------------------------------------


async def test_stale_postings_are_closed_and_counts_follow(tenant) -> None:
    """A filled vacancy just stops appearing; only `last_seen_at` reveals it."""
    summary = await _ingest(StubAdapter(), tenant)

    async with SessionLocal() as session:
        rows = (await session.execute(select(HubJobPosting).limit(3))).scalars().all()
        victim_company = rows[0].hub_company_id
        old = dt.datetime.now(dt.UTC) - dt.timedelta(days=30)
        for row in rows:
            row.last_seen_at = old
        await session.commit()

    async with SessionLocal() as session:
        closed = await service.deactivate_stale_postings(session, older_than_days=14)

    assert closed["deactivated"] == 3
    assert closed["companies_recounted"] >= 1

    async with SessionLocal() as session:
        active = (
            await session.scalar(
                select(func.count(HubJobPosting.id)).where(
                    HubJobPosting.is_active.is_(True)
                )
            )
        ) or 0
        # Deactivated, never deleted: a closed role is itself a BD signal.
        total = (await session.scalar(select(func.count(HubJobPosting.id)))) or 0
        signal = (
            await session.scalar(
                select(HubCompany.open_postings_count).where(
                    HubCompany.id == victim_company
                )
            )
        ) or 0
        still_active_for_company = (
            await session.scalar(
                select(func.count(HubJobPosting.id)).where(
                    HubJobPosting.hub_company_id == victim_company,
                    HubJobPosting.is_active.is_(True),
                )
            )
        ) or 0

    assert total == summary.postings_created
    assert active == summary.postings_created - 3
    # The denormalized "who is hiring hardest" signal must not keep counting
    # vacancies that closed.
    assert signal == still_active_for_company


async def test_expiring_nothing_is_a_no_op(tenant) -> None:
    await _ingest(StubAdapter(), tenant)
    async with SessionLocal() as session:
        assert await service.deactivate_stale_postings(session, older_than_days=14) == {
            "deactivated": 0,
            "companies_recounted": 0,
        }


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_sources_endpoint_lists_registered_adapters(client) -> None:
    resp = await client.get("/api/v1/hub/sources")
    assert resp.status_code == 200
    assert "bundesagentur" in resp.json()["sources"]


async def test_ingest_endpoint_rejects_an_unknown_source(client) -> None:
    resp = await client.post("/api/v1/hub/ingest", json={"source": "linkedin"})
    assert resp.status_code == 400
    assert "unknown hub source" in resp.json()["detail"]


async def test_corpus_endpoints_read_back_what_was_ingested(client, tenant) -> None:
    summary = await _ingest(StubAdapter(), tenant)

    companies = (await client.get("/api/v1/hub/companies?limit=500")).json()
    assert len(companies) == summary.companies_created
    # Most actively hiring first — the ordering is the point of the hub.
    counts = [c["open_postings_count"] for c in companies]
    assert counts == sorted(counts, reverse=True)
    assert all(c["resolution_basis"] == "name_place" for c in companies)

    hiring = (await client.get("/api/v1/hub/companies?hiring_only=true&limit=500")).json()
    assert all(c["open_postings_count"] > 0 for c in hiring)

    postings = (await client.get("/api/v1/hub/postings?limit=500")).json()
    assert len(postings) == summary.postings_created

    top = companies[0]
    nested = (
        await client.get(f"/api/v1/hub/companies/{top['id']}/postings")
    ).json()
    assert len(nested) == top["open_postings_count"]

    observations = (await client.get("/api/v1/hub/observations")).json()
    assert len(observations) == 1
    assert observations[0]["source"] == "bundesagentur"


async def test_tracking_is_the_tenant_boundary(client, tenant) -> None:
    """The corpus is shared; what a tenant makes of it is not."""
    await _ingest(StubAdapter(), tenant)
    companies = (await client.get("/api/v1/hub/companies?limit=5")).json()
    target = companies[0]

    assert target["tracked"] is False
    assert (await client.get("/api/v1/hub/links")).json() == []

    put = await client.put(
        f"/api/v1/hub/companies/{target['id']}/track",
        json={"relationship": "prospect", "note": "hiring hard"},
    )
    assert put.status_code == 200
    assert put.json()["relationship"] == "prospect"

    # Idempotent: tracking twice updates rather than duplicating.
    again = await client.put(
        f"/api/v1/hub/companies/{target['id']}/track", json={"relationship": "client"}
    )
    assert again.status_code == 200
    assert again.json()["id"] == put.json()["id"]
    assert again.json()["relationship"] == "client"

    listed = (await client.get("/api/v1/hub/companies?limit=5")).json()
    assert [c["tracked"] for c in listed if c["id"] == target["id"]] == [True]
    assert len((await client.get("/api/v1/hub/links")).json()) == 1

    only_tracked = (
        await client.get("/api/v1/hub/companies?tracked_only=true&limit=500")
    ).json()
    assert [c["id"] for c in only_tracked] == [target["id"]]

    # Untracking drops the overlay row, never the corpus company.
    assert (
        await client.delete(f"/api/v1/hub/companies/{target['id']}/track")
    ).status_code == 204
    assert (await client.get("/api/v1/hub/links")).json() == []
    assert (await client.get(f"/api/v1/hub/companies/{target['id']}")).status_code == 200


async def test_tracking_an_unknown_company_is_404(client) -> None:
    resp = await client.put(
        f"/api/v1/hub/companies/{uuid.uuid4()}/track", json={"relationship": "watching"}
    )
    assert resp.status_code == 404


async def test_unknown_hub_company_is_404(client) -> None:
    resp = await client.get(f"/api/v1/hub/companies/{uuid.uuid4()}")
    assert resp.status_code == 404
