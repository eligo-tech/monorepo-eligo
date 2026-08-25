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
