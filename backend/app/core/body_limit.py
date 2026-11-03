"""Request bodies are limited while they arrive (review 2026-10-31 #5 B).

The routers check `len(content) > _MAX_BYTES` — after Starlette has already
received the whole multipart body and spooled it to disk. So the limit
limited nothing: a 5 GB upload was written in full before the 413.

This is plain ASGI, in front of everything:

* a request that ANNOUNCES too much (Content-Length) is refused before a
  single byte is read;
* one that does not (chunked) is counted as it streams and cut off the moment
  it passes the limit.

Limits are per path. Uploads keep their own sizes plus room for the
multipart framing — the routers still judge the FILE itself, exactly as
before; this only bounds the request. Everything else is JSON.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from app.core.config import settings

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

MB = 1024 * 1024
#: Multipart boundaries, headers and form fields around the file itself.
_FRAMING = MB // 2

#: (path prefix under the API, limit). First match wins.
_LIMITS: tuple[tuple[str, int], ...] = (
    ("/documents/", 10 * MB + _FRAMING),  # CVs, transcripts, attachments — 10 MB files
    ("/imports/", 20 * MB + _FRAMING),  # CSV / XLSX imports — 20 MB files
)
#: Every other body is JSON; the largest real one is a pasted job advert.
DEFAULT_LIMIT = 2 * MB


def limit_for(path: str) -> int:
    prefix = settings.api_v1_prefix
    for sub, limit in _LIMITS:
        if path.startswith(prefix + sub):
            return limit
    return DEFAULT_LIMIT


class BodySizeLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = limit_for(scope["path"])

        headers = dict(scope.get("headers") or [])
        announced = headers.get(b"content-length")
        origin = headers.get(b"origin")
        if announced is not None:
            try:
                if int(announced) > limit:
                    await _refuse(send, limit, origin=origin)
                    return
            except ValueError:
                await _refuse(send, limit, status=400, text="invalid Content-Length", origin=origin)
                return

        received = 0
        started = False
        refused = False

        async def counting_receive() -> Message:
            # Past the limit: answer 413 ourselves and tell the app the client
            # went away. Raising here would not work — FastAPI turns ANY error
            # while it parses a body into a generic 400, swallowing the reason.
            nonlocal received, refused
            if refused:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    refused = True
                    if not started:
                        await _refuse(send, limit, origin=origin)
                    return {"type": "http.disconnect"}
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if refused:
                return  # the 413 has gone out; whatever the app says now is moot
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, counting_receive, tracking_send)


async def _refuse(
    send: Send, limit: int, *, status: int = 413, text: str | None = None,
    origin: bytes | None = None,
) -> None:
    message = text or f"request body too large (max {limit // MB} MB)"
    body = ('{"detail": {"code": "too_large", "message": "%s"}}' % message).encode()
    headers = [(b"content-type", b"application/json"),
               (b"content-length", str(len(body)).encode()),
               (b"connection", b"close")]
    # This sits outside CORSMiddleware (it must also cover /mcp), so a refusal
    # carries the CORS headers itself — for an allowed origin only — or the
    # cockpit would see a network error instead of the reason.
    if origin and origin.decode("latin-1") in settings.cors_origins:
        headers += [(b"access-control-allow-origin", origin),
                    (b"access-control-allow-credentials", b"true"),
                    (b"vary", b"Origin")]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
