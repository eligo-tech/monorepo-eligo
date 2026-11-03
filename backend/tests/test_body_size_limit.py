"""Upload size is enforced while the body arrives, not after (review 2026-10-31 #5 B).

The routers checked `len(await file.read()) > _MAX_BYTES` — after Starlette
had already received the whole body and spooled it to disk. A 5 GB upload was
written in full before anyone said no. These tests send oversized bodies with
and without a Content-Length and assert the server stops reading early and
the handler never runs.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app

MB = 1024 * 1024
P = settings.api_v1_prefix


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.fixture
def handler_calls(monkeypatch) -> list:
    """Records whether the CV handler's service ran at all."""
    from app.domain.documents import service

    calls: list = []

    async def fake(*args, **kwargs):
        calls.append(1)
        raise AssertionError("the handler must not run for an oversized body")

    monkeypatch.setattr(service, "extract_cv", fake)
    return calls


async def test_an_upload_announced_as_too_large_is_refused_without_reading(handler_calls) -> None:
    """The client says 12 MB up front; nothing of it needs to be read."""
    sent = 0

    async def body():
        nonlocal sent
        for _ in range(12):
            sent += 1
            yield b"x" * MB

    async with _client() as c:
        resp = await c.post(
            f"{P}/documents/extract-cv",
            content=body(),
            headers={"content-type": "multipart/form-data; boundary=zzz",
                     "content-length": str(12 * MB)},
        )
    assert resp.status_code == 413
    assert handler_calls == []
    assert sent <= 1, f"read {sent} MB of a body announced as too large"


async def test_an_oversized_stream_without_a_length_is_cut_off_early(handler_calls) -> None:
    sent = 0

    async def body():
        # A well-formed multipart file part, so the form parser streams it
        # happily and only the size limit can stop it.
        nonlocal sent
        yield (b'--zzz\r\nContent-Disposition: form-data; name="file"; filename="cv.pdf"\r\n'
               b"Content-Type: application/pdf\r\n\r\n")
        for _ in range(100):  # 100 MB offered, chunked, no Content-Length
            sent += 1
            yield b"x" * MB

    async with _client() as c:
        resp = await c.post(
            f"{P}/documents/extract-cv",
            content=body(),
            headers={"content-type": "multipart/form-data; boundary=zzz"},
        )
    assert resp.status_code == 413
    assert handler_calls == []
    assert sent <= 13, f"the server kept reading: {sent} MB consumed"


async def test_a_json_body_over_the_default_is_refused() -> None:
    async with _client() as c:
        resp = await c.post(f"{P}/candidates", content=b"{" + b" " * (3 * MB) + b"}",
                            headers={"content-type": "application/json"})
    assert resp.status_code == 413


async def test_the_file_import_keeps_its_larger_limit() -> None:
    """15 MB is over the documents limit but inside the import's 20 MB: the
    middleware must let it reach the router (which then judges the file)."""
    async with _client() as c:
        resp = await c.post(
            f"{P}/imports/preview",
            files={"file": ("x.csv", b"a;b\n" * (15 * MB // 4), "text/csv")},
            data={"kind": "candidates"},
        )
    assert resp.status_code != 413, resp.text


async def test_normal_requests_are_untouched() -> None:
    async with _client() as c:
        resp = await c.get(f"{P}/health")
        created = await c.post(f"{P}/candidates", json={"full_name": "Normal Size"})
    assert resp.status_code == 200
    assert created.status_code == 201


async def test_the_mcp_endpoint_is_covered_too() -> None:
    """/mcp is dispatched before the rest of the app; the limit sits in front."""
    async with _client() as c:
        resp = await c.post("/mcp", content=b"{" + b" " * (3 * MB) + b"}",
                            headers={"content-type": "application/json"})
    assert resp.status_code == 413


async def test_the_browser_can_read_the_refusal(monkeypatch) -> None:
    """Without CORS headers the cockpit sees a network error, not the 413."""
    monkeypatch.setattr(settings, "cors_origins", ["https://app.example"])
    async with _client() as c:
        allowed = await c.post(f"{P}/candidates", content=b" " * (3 * MB),
                               headers={"content-type": "application/json",
                                        "origin": "https://app.example"})
        foreign = await c.post(f"{P}/candidates", content=b" " * (3 * MB),
                               headers={"content-type": "application/json",
                                        "origin": "https://evil.example"})
    assert allowed.status_code == 413
    assert allowed.headers.get("access-control-allow-origin") == "https://app.example"
    assert foreign.status_code == 413
    assert "access-control-allow-origin" not in foreign.headers
