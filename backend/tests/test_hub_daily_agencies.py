"""The nightly private-recruiter pass (agency finder, Phase 0a PR2).

Same source, same delta, same berufsfeld sharding as the employer sweep — but
every request carries `segment=private_recruiter`, and a shard over the 10,000
cap FAILS the night rather than being split by Bundesland. The employer sweep
splits because losing part of one field is better than losing the crawl; for
leads, a silently truncated field reads as "no agencies there".

Measured 2026-11-02: 4,905 pav postings in the last day, 45,002 in 28 days
over 132 fields, largest field 3,610 — every shard reads whole.
"""

from __future__ import annotations

import json

import httpx
import pytest

from scripts.hub_daily import (
    ShardCapExceeded,
    agency_pass,
    agency_shards,
    agency_verdict,
)


def test_the_shard_plan_is_the_sources_berufsfeld_facets() -> None:
    plan = [{"value": "Einkauf und Vertrieb", "count": 1946}, {"value": "Human- und Zahnmedizin", "count": 3221}]
    assert agency_shards(total=5167, shard_plan=plan) == ["Einkauf und Vertrieb", "Human- und Zahnmedizin"]


def test_a_shard_over_the_cap_fails_instead_of_truncating() -> None:
    plan = [{"value": "Einkauf und Vertrieb", "count": 10_001}]
    with pytest.raises(ShardCapExceeded, match="Einkauf und Vertrieb"):
        agency_shards(total=10_001, shard_plan=plan)


def test_postings_without_a_shard_plan_cannot_be_read_whole() -> None:
    with pytest.raises(ShardCapExceeded):
        agency_shards(total=884, shard_plan=[])


def test_nothing_published_is_no_shards() -> None:
    assert agency_shards(total=0, shard_plan=[]) == []


def _source(fields: dict[str, int], seen: list[dict]):
    """A fake API: every page returns the requested field's postings."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/hub/agencies/refresh"):
            seen.append({"refresh": True})
            return httpx.Response(200, json={"profiles": 7, "agency": 5, "unclear": 1, "client": 1})
        if request.url.path.endswith("/hub/agencies/sites/check"):
            seen.append({"sites": request.url.params.get("limit")})
            # Two agencies left to check, then nothing.
            done = sum(1 for b in seen if "sites" in b)
            n = 2 if done == 1 else 0
            return httpx.Response(200, json={"checked": n, "verified": n, "not_named": 0, "no_impressum": 0, "blocked": 0, "error": 0})
        body = json.loads(request.content)
        seen.append(body)
        field = body.get("berufsfeld")
        total = fields.get(field, 0) if field else sum(fields.values())
        fetched = min(100, max(0, total - (body["page"] - 1) * 100))
        return httpx.Response(
            200,
            json={
                "fetched": fetched,
                "companies_created": 0,
                "postings_created": fetched,
                "postings_updated": 0,
                "total_available": total,
                "posting_external_ids_created": [f"{field}-{body['page']}-{i}" for i in range(fetched)],
                "shard_plan": [{"value": f, "count": c} for f, c in fields.items()],
            },
        )

    return httpx.MockTransport(handler)


async def test_every_request_of_the_pass_asks_for_private_recruiters() -> None:
    seen: list[dict] = []
    created: set[str] = set()
    async with httpx.AsyncClient(transport=_source({"A": 150, "B": 20}, seen), base_url="https://x") as c:
        result = await agency_pass(c, since=1, max_pages=100, delay=0, created_external_ids=created)

    assert seen and all(body["segment"] == "private_recruiter" for body in seen)
    assert {body.get("berufsfeld") for body in seen[1:]} == {"A", "B"}
    assert result["available"] == 170 and result["total"] == 170
    assert result["cap_exceeded"] is None and result["failures"] == []
    # New agency postings get their ad text like any other.
    assert len(created) == 170 + 100  # the probe page ingests too


async def test_the_pass_reports_a_cap_breach_and_reads_nothing_more() -> None:
    seen: list[dict] = []
    async with httpx.AsyncClient(transport=_source({"A": 12_000}, seen), base_url="https://x") as c:
        result = await agency_pass(c, since=28, max_pages=100, delay=0, created_external_ids=set())
    assert "A" in (result["cap_exceeded"] or "")
    assert len(seen) == 1  # the probe only


def test_a_cap_breach_makes_the_night_red_even_at_full_coverage() -> None:
    code, message = agency_verdict(
        {"available": 9_000, "total": 9_000, "failures": [], "cap_exceeded": "A (12000)"},
        min_coverage=90,
    )
    assert code == 1 and "cap" in message


def test_the_agency_verdict_uses_the_same_coverage_rule() -> None:
    ok, _ = agency_verdict({"available": 95, "total": 100, "failures": [], "cap_exceeded": None}, min_coverage=90)
    low, _ = agency_verdict({"available": 50, "total": 100, "failures": ["A"], "cap_exceeded": None}, min_coverage=90)
    assert (ok, low) == (0, 1)


async def _run_main(monkeypatch, argv: list[str], fields: dict[str, int]) -> tuple[int, list[dict]]:
    import sys

    from scripts import hub_daily

    seen: list[dict] = []
    transport = _source(fields, seen)
    real = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr(hub_daily.httpx, "AsyncClient", client)
    monkeypatch.setenv("ELIGO_API_BASE", "https://x")
    monkeypatch.setenv("ELIGO_INGEST_TOKEN", "t")
    monkeypatch.delenv("ELIGO_HUB_REGIONS", raising=False)
    monkeypatch.setattr(sys, "argv", ["hub_daily", *argv])
    _run_main.seen = seen  # type: ignore[attr-defined]
    code = await hub_daily.main()
    return code, [b for b in seen if "source" in b]  # ingest calls only


async def test_the_backfill_runs_the_agency_pass_and_nothing_else(monkeypatch) -> None:
    code, ingests = await _run_main(
        monkeypatch,
        ["--agencies-only", "--since", "28", "--no-descriptions", "--partner-pages", "0", "--delay", "0"],
        {"A": 150},
    )
    assert code == 0
    assert ingests and all(b.get("segment") == "private_recruiter" for b in ingests)
    assert {b["published_since_days"] for b in ingests} == {28}


async def test_the_nightly_run_adds_the_agency_pass_after_the_employers(monkeypatch) -> None:
    code, ingests = await _run_main(
        monkeypatch,
        ["--no-descriptions", "--partner-pages", "0", "--no-profiles", "--delay", "0"],
        {"A": 50},
    )
    employer = [b for b in ingests if "segment" not in b]
    agency = [b for b in ingests if b.get("segment") == "private_recruiter"]
    assert code == 0
    assert employer and agency
    assert ingests.index(agency[0]) > ingests.index(employer[-1])


async def test_a_cap_breach_fails_the_nightly_run(monkeypatch) -> None:
    code, _ = await _run_main(
        monkeypatch,
        ["--agencies-only", "--since", "28", "--no-descriptions", "--partner-pages", "0", "--delay", "0"],
        {"A": 12_000},
    )
    assert code == 1


def _flaky(fields: dict[str, int], seen: list[dict], *, fail: callable):
    """Like `_source`, but `fail(body, n)` may return an error response."""
    inner = _source(fields, seen)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        body = json.loads(request.content) if request.content else {}
        error = fail(body, calls["n"])
        if error is not None:
            seen.append(body)
            return error
        return inner.handle_request(request)

    return httpx.MockTransport(handler)


@pytest.fixture
def no_sleep(monkeypatch):
    import asyncio

    original = asyncio.sleep

    async def instant(_s: float) -> None:
        await original(0)

    monkeypatch.setattr(asyncio, "sleep", instant)


async def test_a_dropped_probe_is_retried(no_sleep) -> None:
    seen: list[dict] = []
    transport = _flaky({"A": 50}, seen, fail=lambda b, n: httpx.Response(500) if n == 1 else None)
    async with httpx.AsyncClient(transport=transport, base_url="https://x") as c:
        result = await agency_pass(c, since=1, max_pages=100, delay=0, created_external_ids=set())
    assert result["available"] == 50 and result["failures"] == []


async def test_a_shard_that_fails_once_is_recovered(no_sleep) -> None:
    seen: list[dict] = []
    failed_once: set[str] = set()

    def fail(body, n):
        field = body.get("berufsfeld")
        if field == "B" and field not in failed_once:
            failed_once.add(field)
            return httpx.Response(500)
        return None

    async with httpx.AsyncClient(transport=_flaky({"A": 10, "B": 10}, seen, fail=fail), base_url="https://x") as c:
        result = await agency_pass(
            c, since=1, max_pages=100, delay=0, created_external_ids=set(), retry_wait=0
        )
    assert result["failures"] == [] and result["available"] == 20


async def test_a_page_cap_that_cuts_a_field_is_a_cap_breach() -> None:
    # `--max-pages 1` on a 150-posting field: page 2 is never read, so the
    # field is short. For leads that must not count as covered.
    seen: list[dict] = []
    async with httpx.AsyncClient(transport=_source({"A": 150}, seen), base_url="https://x") as c:
        result = await agency_pass(c, since=1, max_pages=1, delay=0, created_external_ids=set())
    assert result["cap_exceeded"] and "A" in result["cap_exceeded"]


async def test_the_source_going_down_in_the_agency_pass_leaves_the_employer_verdict_alone(
    monkeypatch, no_sleep
) -> None:
    import sys

    from scripts import hub_daily

    def fail(body, n):
        if body.get("segment") == "private_recruiter":
            return httpx.Response(422, json={"detail": "source unreachable"})
        return None

    seen: list[dict] = []
    transport = _flaky({"A": 50}, seen, fail=fail)
    real = httpx.AsyncClient
    monkeypatch.setattr(hub_daily.httpx, "AsyncClient", lambda *a, **k: real(*a, **{**k, "transport": transport}))
    monkeypatch.setenv("ELIGO_API_BASE", "https://x")
    monkeypatch.setenv("ELIGO_INGEST_TOKEN", "t")
    monkeypatch.delenv("ELIGO_HUB_REGIONS", raising=False)
    monkeypatch.setattr(sys, "argv", ["hub_daily", "--no-descriptions", "--partner-pages", "0", "--no-profiles", "--delay", "0"])

    lines: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: lines.append(" ".join(map(str, a))))
    code = await hub_daily.main()
    assert code == 1  # the agency pass failed
    assert any(line.startswith("ok: ") for line in lines), lines  # the employers did not


async def test_no_agencies_sends_no_private_recruiter_request(monkeypatch) -> None:
    code, ingests = await _run_main(
        monkeypatch,
        ["--no-agencies", "--no-descriptions", "--partner-pages", "0", "--no-profiles", "--delay", "0"],
        {"A": 50},
    )
    assert code == 0 and ingests
    assert not [b for b in ingests if "segment" in b]


async def test_the_backfill_never_touches_employer_postings(monkeypatch) -> None:
    # A stale sweep after a run that saw no employer would close all of them;
    # and 45k ad-text calls would outlast the workflow timeout.
    seen_paths: list[str] = []
    from scripts import hub_daily

    original = hub_daily._fetch_descriptions

    async def spy(*a, **k):
        seen_paths.append("descriptions")
        return await original(*a, **k)

    monkeypatch.setattr(hub_daily, "_fetch_descriptions", spy)
    code, _ = await _run_main(monkeypatch, ["--agencies-only", "--stale-days", "14", "--delay", "0"], {"A": 50})
    assert code == 0
    assert seen_paths == []


async def test_a_backfill_with_nothing_published_is_not_red(monkeypatch) -> None:
    code, _ = await _run_main(monkeypatch, ["--agencies-only", "--since", "0", "--delay", "0"], {})
    assert code == 0


async def test_source_down_during_the_agency_pass_still_gives_employers_their_ad_text(monkeypatch) -> None:
    from scripts import hub_daily

    async def down(*a, **k):
        raise hub_daily.SourceDown("5 pages in a row")

    called: list[str] = []

    async def descriptions(*a, **k):
        called.append("descriptions")
        return {"attempted": 0, "stored": 0, "empty": 0, "with_description": 0, "active_postings": 0}

    monkeypatch.setattr(hub_daily, "agency_pass", down)
    monkeypatch.setattr(hub_daily, "_fetch_descriptions", descriptions)
    lines: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: lines.append(" ".join(map(str, a))))
    code, _ = await _run_main(monkeypatch, ["--partner-pages", "0", "--no-profiles", "--delay", "0"], {"A": 50})
    assert code == 1
    assert called == ["descriptions"]
    assert any(line.startswith("ok: ") for line in lines), lines
    assert any(line.startswith("agencies FAILED: source unreachable") for line in lines), lines


async def test_the_profiles_are_rebuilt_after_the_agency_pass(monkeypatch) -> None:
    code, _ = await _run_main(
        monkeypatch, ["--agencies-only", "--since", "1", "--delay", "0"], {"A": 50}
    )
    seen = _run_main.seen  # type: ignore[attr-defined]
    assert code == 0
    assert seen[-1] == {"refresh": True}


async def test_no_rebuild_when_the_agency_pass_is_off(monkeypatch) -> None:
    await _run_main(
        monkeypatch,
        ["--no-agencies", "--no-descriptions", "--partner-pages", "0", "--no-profiles", "--delay", "0"],
        {"A": 50},
    )
    assert {"refresh": True} not in _run_main.seen  # type: ignore[attr-defined]


def test_a_failed_profile_rebuild_is_red() -> None:
    code, message = agency_verdict(
        {"available": 100, "total": 100, "failures": [], "cap_exceeded": None, "refresh_failed": "500"},
        min_coverage=90,
    )
    assert code == 1 and "profiles" in message


async def test_the_rebuild_runs_after_tonights_ad_text(monkeypatch) -> None:
    # Otherwise tonight's new agencies are judged without their text.
    from scripts import hub_daily

    order: list[str] = []

    async def descriptions(*a, **k):
        refreshed = {"refresh": True} in _run_main.seen  # type: ignore[attr-defined]
        order.append("descriptions after refresh" if refreshed else "descriptions")
        return {"attempted": 0, "stored": 0, "empty": 0, "with_description": 0, "active_postings": 0}

    monkeypatch.setattr(hub_daily, "_fetch_descriptions", descriptions)
    await _run_main(monkeypatch, ["--partner-pages", "0", "--no-profiles", "--delay", "0"], {"A": 50})
    assert order == ["descriptions"]
    assert {"refresh": True} in _run_main.seen  # type: ignore[attr-defined]


async def test_site_checks_run_before_the_profile_rebuild_within_a_budget(monkeypatch) -> None:
    await _run_main(monkeypatch, ["--agencies-only", "--since", "1", "--delay", "0", "--site-checks", "12"], {"A": 50})
    seen = _run_main.seen  # type: ignore[attr-defined]
    order = [next(iter(b)) for b in seen if "sites" in b or "refresh" in b]
    assert order[-1] == "refresh" and "sites" in order
    assert order.index("sites") < order.index("refresh")
    # Stops when the server reports nothing left, well inside the budget.
    assert sum(1 for b in seen if "sites" in b) == 2


async def test_no_site_checks_when_switched_off(monkeypatch) -> None:
    await _run_main(monkeypatch, ["--agencies-only", "--since", "1", "--delay", "0", "--site-checks", "0"], {"A": 50})
    assert not [b for b in _run_main.seen if "sites" in b]  # type: ignore[attr-defined]
