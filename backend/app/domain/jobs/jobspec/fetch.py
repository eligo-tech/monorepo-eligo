"""Reading ONE advert, with the limits written down rather than assumed.

This is the only place in the product where a request a human made causes an
outbound fetch, so the difference between it and ingestion has to be
enforced, not described:

  * **one document** — the URL as given, no link following, no pagination,
    and redirects capped so a short link cannot become a crawl;
  * **http(s) only, public hosts only** — a pasted URL is attacker-controlled
    input the moment somebody shares a "job advert" link, and a server that
    fetches `http://169.254.169.254/` or `http://localhost:8000/` on request
    is an SSRF, not a parser;
  * **bounded** — a timeout and a byte cap, because the caller is holding an
    HTTP request open.

Nothing here writes anything. It returns text.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

TIMEOUT = 15.0
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
USER_AGENT = "eligolabs-jobspec/0.1 (+https://eligolabs.com)"


class NotFetchable(Exception):
    """The URL cannot be read, and the message says why in plain words."""


def _is_public(host: str) -> bool:
    """Does this name resolve ONLY to addresses on the public internet?

    Checked after resolution, not on the literal: `localhost`,
    `127.0.0.1.nip.io` and a DNS record pointing at `10.0.0.5` all look like
    ordinary hostnames and all reach inside. Every answer must be public —
    one private address among several is enough to refuse.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


def check_url(raw: str) -> str:
    """Validate and normalise, or raise `NotFetchable` with a reason."""
    url = raw.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise NotFetchable("Nur http- und https-Adressen können gelesen werden.")
    if not parsed.hostname:
        raise NotFetchable("Diese Adresse hat keinen Host.")
    if not _is_public(parsed.hostname):
        raise NotFetchable("Diese Adresse ist nicht öffentlich erreichbar.")
    return url


async def fetch_posting(raw: str) -> str:
    """The advert's HTML (or text). Raises `NotFetchable` on any refusal."""
    url = check_url(raw)
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"},
        ) as client:
            async with client.stream("GET", url) as response:
                # Re-check after redirects: the first hop was public, the
                # last one is what we actually read.
                final = urlparse(str(response.url))
                if final.hostname and not _is_public(final.hostname):
                    raise NotFetchable("Die Weiterleitung führt auf eine interne Adresse.")
                response.raise_for_status()
                kind = response.headers.get("content-type", "")
                if "html" not in kind and "text" not in kind:
                    raise NotFetchable(
                        f"Diese Adresse liefert {kind or 'einen unbekannten Typ'} — "
                        "erwartet wird eine Webseite."
                    )
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        break  # take the head; an advert is in the first 2 MB
                    chunks.append(chunk)
    except NotFetchable:
        raise
    except httpx.TimeoutException as exc:
        raise NotFetchable("Die Seite hat nicht rechtzeitig geantwortet.") from exc
    except httpx.HTTPStatusError as exc:
        raise NotFetchable(
            f"Die Seite hat mit HTTP {exc.response.status_code} geantwortet."
        ) from exc
    except httpx.HTTPError as exc:
        raise NotFetchable("Die Seite konnte nicht geladen werden.") from exc

    raw_bytes = b"".join(chunks)
    return raw_bytes.decode("utf-8", errors="replace")
