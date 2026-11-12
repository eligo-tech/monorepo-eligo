"""Markt's corpus stats and filter counts, computed by the weekly job.

On prod (2026-11-12) the filter counts took 37 s and the stats 12.5 s to
compute cold, and every backend restart empties the in-process cache — so the
first Markt load after a deploy or a database restart paid both, on an
instance already short of Disk IO. The weekly job now stores them
(`hub_corpus_snapshots`); Markt reads one row. With no row yet (a fresh
deploy) it computes live, as before, and does not write: presentation reads.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.hub import service
from app.domain.hub.models import HubCorpusSnapshot
from app.main import app
from tests.test_hub_ingest import StubAdapter, _ingest


async def _stats_and_facets() -> tuple[dict, dict]:
    service._corpus_cache.clear()
    async with SessionLocal() as s:
        return await service.corpus_stats(s), await service.corpus_facets(s)


async def _snapshot_rows() -> int:
    async with SessionLocal() as s:
        return (await s.scalar(select(func.count()).select_from(HubCorpusSnapshot))) or 0


async def test_markt_reads_the_stored_numbers_not_the_live_corpus() -> None:
    await _ingest(StubAdapter())
    async with SessionLocal() as s:
        stored = await service.refresh_corpus_snapshots(s)
    live_stats, live_facets = await _stats_and_facets()

    # The corpus changes after the job ran: Markt keeps showing the job's numbers.
    async with SessionLocal() as s:
        await s.execute(service.HubJobPosting.__table__.update().values(is_active=False))
        await s.commit()
    stats, facets = await _stats_and_facets()

    assert stats["open_postings"] == live_stats["open_postings"] > 0
    assert facets == live_facets
    assert stats["snapshot_at"] == stored["computed_at"]


async def test_a_refresh_replaces_the_numbers() -> None:
    await _ingest(StubAdapter())
    async with SessionLocal() as s:
        await service.refresh_corpus_snapshots(s)
        await s.execute(service.HubJobPosting.__table__.update().values(is_active=False))
        await s.commit()
        await service.refresh_corpus_snapshots(s)
    stats, _ = await _stats_and_facets()

    assert stats["open_postings"] == 0
    assert await _snapshot_rows() == 2  # one row each, replaced, never appended


async def test_without_a_snapshot_markt_computes_live_and_writes_nothing() -> None:
    await _ingest(StubAdapter())
    stats, facets = await _stats_and_facets()

    assert stats["open_postings"] > 0 and facets["regions"]
    assert stats["snapshot_at"] is None
    assert await _snapshot_rows() == 0


async def test_the_refresh_endpoint_is_machine_only_and_stores_both(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ingest_token", "t" * 40)
    await _ingest(StubAdapter())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            f"{settings.api_v1_prefix}/hub/corpus-snapshots/refresh",
            headers={"Authorization": f"Bearer {'t' * 40}"},
        )
    assert resp.status_code == 200, resp.text
    assert set(resp.json()) == {"computed_at", "open_postings"}
    assert await _snapshot_rows() == 2
