"""The ad-text pass must terminate.

Regression for a production incident: work was selected with
`description IS NULL`, but a posting whose detail call 404s never gains text —
so it stayed NULL and was selected again on the very next batch. The run
re-requested the same 25 references every few seconds against a public API and
would never have finished.

The fix is to record the ATTEMPT rather than only the result. These tests pin
that, because "it eventually stops" is not something to take on trust twice.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.domain.hub import service
from app.domain.hub.adapters.base import SourceQuery
from app.domain.hub.models import HubCompany, HubJobPosting


class _Adapter:
    """Returns text for some postings and nothing for others, like the source."""

    name = "test"

    def __init__(self, texts: dict[str, str | None]) -> None:
        self._texts = texts
        self.calls: list[str] = []

    async def fetch(self, query: SourceQuery):  # pragma: no cover - unused here
        raise NotImplementedError

    async def fetch_description(self, external_id: str) -> str | None:
        self.calls.append(external_id)
        return self._texts.get(external_id)


@pytest.fixture
async def postings() -> None:
    now = dt.datetime.now(dt.UTC)
    async with SessionLocal() as s:
        company = HubCompany(
            name="Test GmbH",
            normalized_name="test",
            dedupe_key=f"k-{uuid.uuid4()}",
            resolution_basis="name_place",
            source="test",
            first_seen_at=now,
            last_seen_at=now,
        )
        s.add(company)
        await s.flush()
        for ext in ("has-text", "no-text-1", "no-text-2"):
            s.add(
                HubJobPosting(
                    hub_company_id=company.id,
                    title=f"Role {ext}",
                    source="test",
                    external_id=ext,
                    content_hash=ext,
                    first_seen_at=now,
                    last_seen_at=now,
                    is_active=True,
                )
            )
        await s.commit()


async def test_a_posting_without_text_is_never_requested_twice(postings) -> None:
    """THE regression. Two passes must not re-request the same dead posting."""
    adapter = _Adapter({"has-text": "Wir suchen Kotlin."})

    async with SessionLocal() as s:
        first = await service.fetch_missing_descriptions(
            s, adapter=adapter, limit=10, delay=0
        )
    assert first == {"attempted": 3, "stored": 1, "empty": 2}
    assert sorted(adapter.calls) == ["has-text", "no-text-1", "no-text-2"]

    # Second pass: nothing is left to try, and NOTHING is re-requested.
    calls_before = len(adapter.calls)
    async with SessionLocal() as s:
        second = await service.fetch_missing_descriptions(
            s, adapter=adapter, limit=10, delay=0
        )
    assert second["attempted"] == 0, "re-selected postings that were already tried"
    assert len(adapter.calls) == calls_before, "re-requested a dead posting"


async def test_exact_scope_never_falls_through_to_backlog(postings) -> None:
    """Nightly IDs are a hard boundary, not merely a priority hint."""
    adapter = _Adapter({"no-text-2": "new job text"})

    async with SessionLocal() as s:
        result = await service.fetch_missing_descriptions(
            s,
            adapter=adapter,
            limit=25,
            external_ids=["no-text-2", "not-in-the-corpus"],
            delay=0,
        )

    assert result == {"attempted": 1, "stored": 1, "empty": 0}
    assert adapter.calls == ["no-text-2"]


async def test_every_attempt_is_stamped_even_when_empty(postings) -> None:
    adapter = _Adapter({"has-text": "text"})
    async with SessionLocal() as s:
        await service.fetch_missing_descriptions(s, adapter=adapter, limit=10, delay=0)
        rows = (await s.execute(select(HubJobPosting))).scalars().all()

    assert all(r.description_fetched_at is not None for r in rows)
    # The distinction survives: tried-and-empty is not the same as has-text.
    assert {r.external_id for r in rows if r.description} == {"has-text"}


async def test_progress_separates_never_tried_from_nothing_there(postings) -> None:
    adapter = _Adapter({"has-text": "text"})
    async with SessionLocal() as s:
        before = await service.descriptions_progress(s)
        assert before == {
            "active_postings": 3,
            "with_description": 0,
            "corpus_attempted": 0,
            "remaining": 3,
        }
        await service.fetch_missing_descriptions(s, adapter=adapter, limit=10, delay=0)
        after = await service.descriptions_progress(s)

    assert after["corpus_attempted"] == 3
    assert after["with_description"] == 1
    # Nothing remaining, so a caller looping on progress terminates.
    assert after["remaining"] == 0


async def test_a_failing_source_does_not_end_the_run(postings) -> None:
    """One unreachable posting must not stop the others being tried."""

    class _Flaky(_Adapter):
        async def fetch_description(self, external_id: str) -> str | None:
            self.calls.append(external_id)
            if external_id == "no-text-1":
                raise RuntimeError("upstream exploded")
            return self._texts.get(external_id)

    adapter = _Flaky({"has-text": "text"})
    async with SessionLocal() as s:
        result = await service.fetch_missing_descriptions(
            s, adapter=adapter, limit=10, delay=0
        )
    assert result["attempted"] == 3 and result["stored"] == 1
    # And the exploded one is still marked tried, so it will not loop either.
    async with SessionLocal() as s:
        row = (
            await s.execute(
                select(HubJobPosting).where(HubJobPosting.external_id == "no-text-1")
            )
        ).scalar_one()
    assert row.description_fetched_at is not None


async def test_an_adapter_without_detail_support_is_a_no_op(postings) -> None:
    class _NoDetail:
        name = "test"

        async def fetch(self, query: SourceQuery):  # pragma: no cover
            raise NotImplementedError

    async with SessionLocal() as s:
        assert await service.fetch_missing_descriptions(
            s, adapter=_NoDetail(), limit=10, delay=0
        ) == {"attempted": 0, "stored": 0, "empty": 0}


async def test_the_endpoint_keeps_the_batch_count_distinct(postings) -> None:
    """The response merges a batch result with corpus progress.

    Regression: both used the key `attempted`, so the corpus total overwrote the
    batch count and the caller's `attempted == 0` exhaustion check could never
    fire — a second infinite loop, hidden behind the fix for the first.
    """
    from httpx import ASGITransport, AsyncClient

    from app.core.config import settings
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        body = (
            await client.post(f"{settings.api_v1_prefix}/hub/descriptions/fetch?limit=5")
        ).json()

    assert "attempted" in body and "corpus_attempted" in body
    # The batch count is bounded by the batch, never the corpus.
    assert body["attempted"] <= 5
    assert body["corpus_attempted"] >= body["attempted"]
