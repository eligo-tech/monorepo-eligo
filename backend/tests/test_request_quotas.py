"""Request quotas for the REST API (review 2026-10-31 #5 C).

Only the Claude connector had a limit. Any signed-in user — or a script with
their token — could call the API without bound, including the three routes
that pay an LLM per call. Two limits now, both per user, both answered with
429 and Retry-After:

* every authenticated request: `rest_rate_limit_per_minute` (generous);
* CV / transcript extraction and job-advert parsing:
  `ai_rate_limit_per_minute` (tight — each is a paid model call).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import ratelimit
from app.core.config import settings
from app.main import app

P = settings.api_v1_prefix


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_the_paid_ai_routes_have_a_tight_limit(monkeypatch) -> None:
    from app.domain.jobs import jobspec
    from app.domain.jobs.jobspec.heuristic import HeuristicJobSpecExtractor

    monkeypatch.setattr(settings, "ai_rate_limit_per_minute", 3)
    calls = []
    real = HeuristicJobSpecExtractor()

    class Counting:
        name = "counting"

        def extract(self, text, title=""):
            calls.append(1)
            return real.extract(text, title)

    monkeypatch.setattr(jobspec, "get_job_spec_extractor", lambda *a, **k: Counting())
    advert = {"text": "Senior Java Entwickler (m/w/d) in München. " * 5}
    async with _client() as c:
        answers = [await c.post(f"{P}/jobs/parse-spec", json=advert) for _ in range(4)]
    assert [r.status_code for r in answers[:3]] == [200, 200, 200]
    assert answers[3].status_code == 429
    assert answers[3].json()["detail"]["code"] == "rate_limited"
    assert 1 <= int(answers[3].headers["retry-after"]) <= 60
    assert len(calls) == 3, "the refused call must not reach the paid model"


async def test_every_authenticated_route_has_a_general_limit(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rest_rate_limit_per_minute", 5)
    async with _client() as c:
        codes = [(await c.get(f"{P}/candidates")).status_code for _ in range(6)]
        health = await c.get(f"{P}/health")  # unauthenticated: not counted
    assert codes == [200] * 5 + [429]
    assert health.status_code == 200


def test_the_limit_is_per_user_and_the_window_slides(monkeypatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: now[0])
    limit = ratelimit.Limiter("test", lambda: 2)
    limit.check("anna")
    limit.check("anna")
    with pytest.raises(ratelimit.RateLimited) as refused:
        limit.check("anna")
    assert refused.value.retry_after == 60
    limit.check("bob")  # somebody else is not held back by Anna
    now[0] += 60.5
    limit.check("anna")  # the window moved on
