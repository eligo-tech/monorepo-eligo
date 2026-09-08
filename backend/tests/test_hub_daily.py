"""Regression tests for the nightly ingestion coordinator."""

from __future__ import annotations

import json

import httpx

from scripts.hub_daily import _DESCRIPTION_BATCH_SIZE, _fetch_descriptions


async def test_description_top_up_uses_proxy_safe_batches() -> None:
    requested: list[int] = []
    requested_ids: list[str] = []
    corpus_attempted = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal corpus_attempted
        batch = int(request.url.params["limit"])
        body = json.loads(request.content)
        requested.append(batch)
        requested_ids.extend(body["external_ids"])
        corpus_attempted += batch
        return httpx.Response(
            200,
            json={
                "attempted": batch,
                "stored": batch - 1,
                "empty": 1,
                "active_postings": 10_000,
                "with_description": corpus_attempted,
                "corpus_attempted": corpus_attempted,
                "remaining": 10_000 - corpus_attempted,
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.test"
    ) as client:
        result = await _fetch_descriptions(
            client, external_ids={f"job-{i:03}" for i in range(63)}
        )

    assert requested == [_DESCRIPTION_BATCH_SIZE, _DESCRIPTION_BATCH_SIZE, 13]
    assert requested_ids == [f"job-{i:03}" for i in range(63)]
    assert result["attempted"] == 63
    assert result["stored"] == 60
    assert result["empty"] == 3
    assert result["with_description"] == 63


async def test_description_top_up_does_nothing_without_new_ids() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: (_ for _ in ()).throw(
            AssertionError("must not call the API")
        )),
        base_url="https://example.test",
    ) as client:
        result = await _fetch_descriptions(client, external_ids=set())

    assert result["attempted"] == 0


async def test_a_page_cut_off_by_the_proxy_is_retried_not_lost() -> None:
    """One transient 500 must not fail the whole nightly run.

    On 2026-09-07 a single shard — "Immobilienwirtschaft und Facility-Management"
    — went quiet for 62 seconds and came back 500: the request outlived the
    hosting proxy, which is the same failure the description batches already
    retry. With no retry here, that one cut-off shard failed the run's exit code
    even though the sweep had reached 100.1% coverage and written 3,853 roles.

    A crawl slice is idempotent — upserts keyed on the source id — so
    re-sending one is safe.
    """
    import asyncio

    from scripts.hub_daily import _ingest_region

    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(500, text="Internal Server Error")
        return httpx.Response(
            200,
            json={
                "fetched": 3,
                "companies_created": 1,
                "postings_created": 2,
                "postings_updated": 1,
                "total_available": 3,
                "posting_external_ids_created": ["a", "b"],
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.test"
    ) as client:
        # No real waiting: the backoff is behaviour we want, not latency we
        # want to sit through in a test.
        original = asyncio.sleep

        async def instant(_seconds: float) -> None:
            await original(0)

        asyncio.sleep = instant
        try:
            totals = await _ingest_region(
                client,
                region=None,
                berufsfeld="Immobilienwirtschaft und Facility-Management",
                what=None,
                radius_km=None,
                since_days=1,
                max_pages=1,
                delay=0,
                primary=True,
            )
        finally:
            asyncio.sleep = original

    assert attempts == 2, "the first response was a 500; it should have retried"
    assert totals["postings"] == 2
    assert totals["available"] == 3
