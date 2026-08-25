"""Regression tests for the nightly ingestion coordinator."""

from __future__ import annotations

import httpx

from scripts.hub_daily import _DESCRIPTION_BATCH_SIZE, _fetch_descriptions


async def test_description_top_up_uses_proxy_safe_batches() -> None:
    requested: list[int] = []
    corpus_attempted = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal corpus_attempted
        batch = int(request.url.params["limit"])
        requested.append(batch)
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
        result = await _fetch_descriptions(client, limit=63)

    assert requested == [_DESCRIPTION_BATCH_SIZE, _DESCRIPTION_BATCH_SIZE, 13]
    assert result["attempted"] == 63
    assert result["stored"] == 60
    assert result["empty"] == 3
    assert result["with_description"] == 63


async def test_description_top_up_stops_when_no_work_remains() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "attempted": 0,
                "stored": 0,
                "empty": 0,
                "active_postings": 10,
                "with_description": 8,
                "corpus_attempted": 10,
                "remaining": 0,
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.test"
    ) as client:
        result = await _fetch_descriptions(client, limit=300)

    assert calls == 1
    assert result["attempted"] == 0
