"""The redirect chain behind "read this job advert", hop by hop.

`check_url` was already well covered, and it was never the hole. The hole was
that it only ran twice — on the URL the recruiter pasted, and on whatever host
the chain happened to end at — while httpx walked everything in between. A
public advert answering `302 → http://127.0.0.1:8000/` therefore produced a
loopback request that was sent, connected and answered, and was only refused
afterwards.

So these tests assert on the REQUESTS THAT LEFT, not on the return value.
`fetch_posting` raising `NotFetchable` proves nothing by itself: the old code
raised too, after making the call. Every case below counts what the transport
saw.
"""

from __future__ import annotations

import ipaddress

import httpx
import pytest

from app.domain.jobs import jobspec
from app.domain.jobs.jobspec import fetch

PUBLIC_IP = "93.184.216.34"
OTHER_IP = "198.51.100.7"

#: Hostnames that resolve to the public internet in these tests. Anything else
#: must be an IP literal or the lookup fails, which is what a real resolver
#: does with a name that does not exist.
ZONE = {
    "adverts.example.com": PUBLIC_IP,
    "jobs.example.com": PUBLIC_IP,
    "elsewhere.example.com": OTHER_IP,
}


@pytest.fixture(autouse=True)
def _resolver(monkeypatch):
    def getaddrinfo(host, *args, **kwargs):
        if host in ZONE:
            return [(2, 1, 6, "", (ZONE[host], 80))]
        try:
            ipaddress.ip_address(host)
        except ValueError as exc:
            raise OSError(f"name does not resolve: {host}") from exc
        return [(2, 1, 6, "", (host, 80))]

    monkeypatch.setattr(fetch.socket, "getaddrinfo", getaddrinfo)


class Recorder:
    """A transport that answers from a routing table and keeps every request.

    Routing is by `Host`, not by the URL's host, because the whole point of
    the fix is that the URL now carries a pinned IP address.
    """

    def __init__(self, routes: dict[str, httpx.Response]):
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = request.headers.get("host", request.url.host)
        if key not in self.routes:
            raise AssertionError(f"unexpected request to {key} ({request.url})")
        return self.routes[key]

    @property
    def hosts(self) -> list[str]:
        return [r.headers.get("host", r.url.host) for r in self.requests]


def _install(monkeypatch, recorder) -> None:
    """`recorder` is any callable taking a Request and returning a Response."""
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(recorder), **kwargs)

    monkeypatch.setattr(fetch, "_client", client)


def _page(body: str = "<html>Stellenanzeige</html>") -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": "text/html"})


def _redirect(to: str, status: int = 302) -> httpx.Response:
    return httpx.Response(status, headers={"location": to})


# ── the hole ──────────────────────────────────────────────────────────────


async def test_a_redirect_inside_is_never_requested(monkeypatch) -> None:
    """The reported SSRF, as the report describes it.

    The assertion that matters is the second one. Refusing to RETURN the body
    of an internal response is not a fix — the request has been delivered, and
    an internal endpoint that acts on a GET has already acted.
    """
    recorder = Recorder(
        {"adverts.example.com": _redirect("http://127.0.0.1:8000/api/v1/jobs")}
    )
    _install(monkeypatch, recorder)

    with pytest.raises(jobspec.NotFetchable):
        await fetch.fetch_posting("http://adverts.example.com/job/1")

    assert recorder.hosts == ["adverts.example.com"]
    assert not any("127.0.0.1" in str(r.url) for r in recorder.requests)


@pytest.mark.parametrize(
    "location",
    [
        "http://127.0.0.1:8000/api/v1/jobs",
        "http://localhost:8000/",
        "http://169.254.169.254/latest/meta-data/",  # cloud credentials
        "http://10.0.0.5/",
        "http://[::1]/",
        "file:///etc/passwd",
        "gopher://127.0.0.1:11211/",
    ],
)
async def test_no_redirect_target_escapes_the_check(monkeypatch, location) -> None:
    """Every address family the first hop is screened for, screened again.

    The link-local case is the expensive one: `169.254.169.254` is the cloud
    metadata endpoint, and on an instance role it answers credentials to an
    unauthenticated GET.
    """
    recorder = Recorder({"adverts.example.com": _redirect(location)})
    _install(monkeypatch, recorder)

    with pytest.raises(jobspec.NotFetchable):
        await fetch.fetch_posting("http://adverts.example.com/job/1")

    assert len(recorder.requests) == 1


async def test_the_second_hop_is_checked_too(monkeypatch) -> None:
    """A public redirect to a public redirect to the inside.

    One check on the first URL and one on the last would pass the middle of a
    chain unexamined; this is the shape that exploits it.
    """
    recorder = Recorder(
        {
            "adverts.example.com": _redirect("http://jobs.example.com/b"),
            "jobs.example.com": _redirect("http://169.254.169.254/"),
        }
    )
    _install(monkeypatch, recorder)

    with pytest.raises(jobspec.NotFetchable):
        await fetch.fetch_posting("http://adverts.example.com/a")

    assert recorder.hosts == ["adverts.example.com", "jobs.example.com"]


# ── the connection goes where the check went ──────────────────────────────


async def test_the_request_is_sent_to_the_address_that_was_checked(
    monkeypatch,
) -> None:
    """Resolve once, connect to that. Not resolve, then resolve again.

    Checking a NAME and then connecting by NAME is two lookups, and a record
    with a one-second TTL is free to answer differently the second time. The
    URL on the wire therefore carries the address, and the hostname rides in
    `Host` and SNI so virtual hosting and certificate verification are
    unaffected.
    """
    recorder = Recorder({"adverts.example.com": _page()})
    _install(monkeypatch, recorder)

    await fetch.fetch_posting("http://adverts.example.com/job/1")

    sent = recorder.requests[0]
    assert sent.url.host == PUBLIC_IP
    assert sent.headers["host"] == "adverts.example.com"
    assert sent.extensions.get("sni_hostname") == "adverts.example.com"
    assert sent.url.path == "/job/1"


async def test_a_port_survives_pinning(monkeypatch) -> None:
    recorder = Recorder({"adverts.example.com:8443": _page()})
    _install(monkeypatch, recorder)

    await fetch.fetch_posting("http://adverts.example.com:8443/job/1")

    sent = recorder.requests[0]
    assert sent.url.host == PUBLIC_IP
    assert sent.url.port == 8443
    assert sent.headers["host"] == "adverts.example.com:8443"


# ── the ordinary path still works ─────────────────────────────────────────


async def test_a_public_chain_is_followed_and_read(monkeypatch) -> None:
    recorder = Recorder(
        {
            "adverts.example.com": _redirect("http://jobs.example.com/real"),
            "jobs.example.com": _page("<html>Senior Developer</html>"),
        }
    )
    _install(monkeypatch, recorder)

    body = await fetch.fetch_posting("http://adverts.example.com/short")

    assert "Senior Developer" in body
    assert recorder.hosts == ["adverts.example.com", "jobs.example.com"]


async def test_a_relative_location_resolves_against_the_hostname(
    monkeypatch,
) -> None:
    """`Location: /stellen/42` must join onto the hostname, not the pinned IP.

    Joining onto the address would send the site a URL naming its own numeric
    address, which breaks virtual hosting and any canonical-host check the
    site makes on itself.
    """
    calls: list[httpx.Request] = []

    def router(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/stellen/42":
            return _page("<html>Stelle 42</html>")
        return _redirect("/stellen/42")

    _install(monkeypatch, router)

    body = await fetch.fetch_posting("http://adverts.example.com/job/1")

    assert "Stelle 42" in body
    assert [c.url.path for c in calls] == ["/job/1", "/stellen/42"]
    assert all(c.url.host == PUBLIC_IP for c in calls)
    assert all(c.headers["host"] == "adverts.example.com" for c in calls)


async def test_too_many_redirects_is_refused(monkeypatch) -> None:
    """A loop must end as a refusal, not as a request budget nobody set."""
    calls: list[httpx.Request] = []

    def router(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _redirect("http://adverts.example.com/again")

    _install(monkeypatch, router)

    with pytest.raises(jobspec.NotFetchable):
        await fetch.fetch_posting("http://adverts.example.com/loop")

    assert len(calls) == fetch.MAX_REDIRECTS + 1


async def test_a_redirect_with_no_location_is_refused(monkeypatch) -> None:
    recorder = Recorder({"adverts.example.com": httpx.Response(302)})
    _install(monkeypatch, recorder)

    with pytest.raises(jobspec.NotFetchable):
        await fetch.fetch_posting("http://adverts.example.com/job/1")

    assert len(recorder.requests) == 1
