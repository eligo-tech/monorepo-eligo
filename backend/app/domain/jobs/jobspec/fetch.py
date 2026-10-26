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

**Every hop is checked BEFORE it is made, and connects to the address that
was checked.** Both halves of that sentence were missing and each was a hole:

1. `follow_redirects=True` let httpx walk the chain internally, so the only
   check ran on `response.url` — the host at the END. A public advert URL
   answering `302 → http://127.0.0.1:8000/` meant the loopback request had
   already been sent and answered by the time the check refused it. Refusing
   to return the body does not un-send the request; for an internal service
   that acts on a GET, the damage is done before the refusal. Redirects are
   now followed by hand, and `check_url` runs on each `Location` before the
   next request exists.
2. Validating a NAME and then connecting by name resolves DNS twice, so the
   two answers need not agree — a record with a one-second TTL can be public
   for the check and private for the connection (DNS rebinding). Each hop now
   resolves once, and the request is sent to that pinned address.

Pinning keeps TLS intact rather than trading one hole for another: the
request carries `sni_hostname` and a `Host` header, so the certificate is
verified against the real hostname and not against the IP. Verified against
`wrong.host.badssl.com`, which is rejected exactly as it is on the ordinary
path — `certificate is not valid for 'wrong.host.badssl.com'`.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse, urlunparse

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

TIMEOUT = 15.0
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
USER_AGENT = "eligolabs-jobspec/0.1 (+https://eligolabs.com)"


class NotFetchable(Exception):
    """The URL cannot be read, and the message says why in plain words."""


def _public_addresses(host: str) -> list[str]:
    """Every address this name resolves to, or `[]` if ANY of them is internal.

    Checked after resolution, not on the literal: `localhost`,
    `127.0.0.1.nip.io` and a DNS record pointing at `10.0.0.5` all look like
    ordinary hostnames and all reach inside. One private answer among several
    is enough to refuse — a round-robin that is public three times out of four
    is not a public host, it is an intermittent SSRF.

    Returns the addresses rather than a boolean so the caller can CONNECT to
    one it has already checked, instead of resolving the name a second time
    and hoping for the same answer.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    if not infos:
        return []
    addresses: list[str] = []
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return []
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return []
        addresses.append(str(ip))
    return addresses


def _is_public(host: str) -> bool:
    """Does this name resolve ONLY to addresses on the public internet?"""
    return bool(_public_addresses(host))


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


def _pin(url: str, ip: str) -> tuple[str, str]:
    """`(url with the address substituted, Host header)`.

    The connection goes to an address already checked; the hostname still
    travels, in `Host` and in SNI, so virtual hosting and certificate
    verification both behave normally.
    """
    parsed = urlparse(url)
    literal = f"[{ip}]" if ":" in ip else ip
    hostname = parsed.hostname or ""
    named = f"[{hostname}]" if ":" in hostname else hostname
    if parsed.port:
        return (
            urlunparse(parsed._replace(netloc=f"{literal}:{parsed.port}")),
            f"{named}:{parsed.port}",
        )
    return urlunparse(parsed._replace(netloc=literal)), named


def _client(**kwargs) -> httpx.AsyncClient:
    """The seam tests reach through to install a transport. Nothing else."""
    return httpx.AsyncClient(**kwargs)


async def fetch_posting(raw: str) -> str:
    """The advert's HTML (or text). Raises `NotFetchable` on any refusal."""
    url = check_url(raw)
    try:
        async with _client(
            timeout=TIMEOUT,
            # Followed by hand below. With httpx doing it, the internal
            # request of a hostile redirect is sent before anything can
            # object to it.
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"},
        ) as client:
            # One more pass than redirects, for the response that is not one.
            for _ in range(MAX_REDIRECTS + 1):
                parsed = urlparse(url)
                hostname = parsed.hostname or ""
                addresses = _public_addresses(hostname)
                if not addresses:
                    raise NotFetchable("Diese Adresse ist nicht öffentlich erreichbar.")
                target, host_header = _pin(url, addresses[0])

                async with client.stream(
                    "GET",
                    target,
                    headers={"Host": host_header},
                    extensions={"sni_hostname": hostname},
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise NotFetchable(
                                "Die Seite leitet weiter, nennt aber kein Ziel."
                            )
                        # Resolved against the LOGICAL url, not the pinned one,
                        # so a relative Location lands on the right host. The
                        # check happens here — before the next request exists.
                        url = check_url(str(httpx.URL(url).join(location)))
                        continue

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
                    return b"".join(chunks).decode("utf-8", errors="replace")

            raise NotFetchable("Diese Adresse leitet zu oft weiter.")
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
