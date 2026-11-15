"""The ad-text pass stops on a time budget, cleanly.

Saturday 2026-11-14: both weekly ad-text jobs ran `--target 45000`, a count
of texts STORED. Most of the week's ads have no text to store, so neither job
reached it, and GitHub killed both at their 350-minute timeout after ~95k ads
— which marks the whole weekly run "cancelled". A time budget ends the job
itself, before the timeout, with exit 0.
"""

from __future__ import annotations

import sys

import httpx
import pytest

from scripts import hub_descriptions


async def test_the_pass_stops_when_its_minutes_are_up(monkeypatch, capsys) -> None:
    posts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(401)
        posts.append(str(request.url))
        # Never exhausted, and mostly ads without text: the Saturday shape.
        return httpx.Response(200, json={"attempted": 25, "stored": 5, "empty": 20})

    real_client = httpx.AsyncClient

    def client(**kwargs):
        kwargs.pop("timeout", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    now = {"t": 0.0}

    def clock() -> float:
        now["t"] += 60.0  # every look at the clock is a minute later
        return now["t"]

    monkeypatch.setattr(hub_descriptions.httpx, "AsyncClient", client)
    monkeypatch.setattr(hub_descriptions, "_clock", clock)
    monkeypatch.setenv("ELIGO_API_BASE", "http://api")
    monkeypatch.setenv("ELIGO_INGEST_TOKEN", "t" * 40)
    monkeypatch.setattr(sys, "argv", ["hub_descriptions", "--all", "--minutes", "5"])

    assert await hub_descriptions.main() == 0
    assert 0 < len(posts) <= 5
    assert "time budget" in capsys.readouterr().out


def test_minutes_must_be_positive(monkeypatch, capsys) -> None:
    import asyncio

    monkeypatch.setattr(sys, "argv", ["hub_descriptions", "--minutes", "0"])
    with pytest.raises(SystemExit):
        asyncio.run(hub_descriptions.main())
    assert "--minutes must be positive" in capsys.readouterr().err
