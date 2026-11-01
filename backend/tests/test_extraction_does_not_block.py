"""Review 2026-10-31, High #2: an LLM or PDF call must not stall the server.

The OpenAI extractors are synchronous. Called straight from an async request
they block the event loop for the length of the call — seconds per CV — and
every other request on that worker waits, including other users' page loads.

Each test runs the path with a deliberately slow, blocking fake (time.sleep,
exactly what a sync HTTP client does) and a ticker coroutine beside it. If the
call runs on the loop the ticker freezes; off the loop it keeps ticking.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from httpx import ASGITransport, AsyncClient

from app.core.database import SessionLocal
from app.domain.documents import parser
from app.domain.documents import service as documents
from app.domain.documents.extraction.base import CVSections

BLOCK = 0.4  # seconds each fake holds the thread
CV_TEXT = "Anna Beispiel\nanna@example.com\nSenior Java Developer bei Firma GmbH\n" * 5


async def _ticks_during(coro) -> int:
    ticks = 0
    done = False

    async def ticker() -> None:
        nonlocal ticks
        while not done:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0)  # let it start
    try:
        await coro
    finally:
        done = True
        await task
    return ticks


def _slow(value):
    def fake(*args, **kwargs):
        time.sleep(BLOCK)
        return value

    return fake


# A blocked loop gets ~0 ticks over BLOCK seconds; a free one gets ~BLOCK/0.01.
FREE = int(BLOCK / 0.01 / 3)


async def test_cv_extraction_keeps_the_server_responsive(monkeypatch) -> None:
    monkeypatch.setattr(parser, "pdf_to_text", _slow(CV_TEXT))
    monkeypatch.setattr(documents, "_run_extractor", _slow(([], CVSections(), "slow-fake")))
    async with SessionLocal() as s:
        ticks = await _ticks_during(
            documents.extract_cv(s, filename="cv.pdf", content=b"%PDF", tenant_id=uuid.uuid4(),
                                 persist=False)
        )
    assert ticks >= 2 * FREE, f"the event loop froze during extraction ({ticks} ticks)"


async def test_transcript_extraction_keeps_the_server_responsive(monkeypatch) -> None:
    from app.domain.candidates.models import Candidate

    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        cand = Candidate(tenant_id=tenant, full_name="Anna Beispiel")
        s.add(cand)
        await s.commit()
        monkeypatch.setattr(documents, "_document_text", _slow(CV_TEXT))
        monkeypatch.setattr(documents, "_run_qualification_extractor", _slow(([], "slow-fake")))
        ticks = await _ticks_during(
            documents.extract_transcript(s, tenant_id=tenant, candidate_id=cand.id,
                                         filename="t.txt", content=b"x", content_type="text/plain")
        )
    assert ticks >= 2 * FREE, f"the event loop froze during extraction ({ticks} ticks)"


async def test_job_spec_extraction_keeps_the_server_responsive(monkeypatch) -> None:
    from app.domain.jobs import jobspec
    from app.domain.jobs.jobspec.heuristic import HeuristicJobSpecExtractor
    from app.main import app

    real = HeuristicJobSpecExtractor()

    class Slow:
        name = "slow-fake"

        def extract(self, text, title=""):
            time.sleep(BLOCK)
            return real.extract(text, title)

    monkeypatch.setattr(jobspec, "get_job_spec_extractor", lambda *a, **k: Slow())
    advert = "Senior Java Entwickler (m/w/d) in München. Wir suchen ... " * 5
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        ticks = await _ticks_during(client.post("/api/v1/jobs/parse-spec", json={"text": advert}))
    assert ticks >= FREE, f"the event loop froze during extraction ({ticks} ticks)"
