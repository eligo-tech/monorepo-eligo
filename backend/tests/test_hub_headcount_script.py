"""ELI-54: the weekly headcount step pages its queue and stops on a refusal."""

from __future__ import annotations

import time

import httpx

from scripts.hub_headcount import _ad_texts, _wikidata


async def test_the_ad_text_pass_follows_the_cursor_until_done() -> None:
    seen: list[str] = []
    pages = [
        {"read": 500, "sized": 3, "cleared": 0, "last_id": "00000000-0000-0000-0000-000000000001", "done": False},
        {"read": 20, "sized": 1, "cleared": 1, "last_id": "00000000-0000-0000-0000-000000000002", "done": True},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=pages[len(seen) - 1])

    async with httpx.AsyncClient(base_url="http://api", transport=httpx.MockTransport(handler)) as client:
        totals = await _ad_texts(client, deadline=time.monotonic() + 60)
    assert totals["read"] == 520 and totals["sized"] == 4 and totals["cleared"] == 1
    assert "after=" not in seen[0]
    assert "after=00000000-0000-0000-0000-000000000001" in seen[1]


async def test_the_wikidata_pass_stops_when_the_endpoint_refuses() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"asked": 0, "matched": 0, "sized": 0, "failed": 40,
                                         "last_domain": "a.de", "done": False})

    async with httpx.AsyncClient(base_url="http://api", transport=httpx.MockTransport(handler)) as client:
        totals = await _wikidata(client, budget=20_000, deadline=time.monotonic() + 60)
    assert calls == 1 and totals["failed"] == 40
