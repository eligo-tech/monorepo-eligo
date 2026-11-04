"""Verify agency website candidates against their Impressum (PR7, option A).

A machine-only nightly step (ARCHITECTURE.md RULE 1). For each agency, best
score first, it takes the best website candidate from the ads (`domains.py`)
that is not likely the client's and not yet checked, fetches the homepage and
its Impressum through `SiteFetcher`, and records the outcome in
`hub_site_checks`. Only when the Impressum names the agency as its operator
(`impressum.names_firm`) are company facts written onto the agency's corpus
rows — website, VAT, register — and only where they are still empty: a fact
already on record outranks this one.

People named in the Impressum are parsed by the adapter and dropped here: not
stored until the GDPR Art. 14 question is answered (decision 2026-11-04).

`SiteFetcher` is the partner-page discipline (robots.txt, one identified
User-Agent, a pause per host) plus what fetching arbitrary agency sites needs:
redirects are followed by hand, and every hop must be a public host name that
resolves only to public addresses. Measured: one agency's Impressum link points
at http://localhost:8093/.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import hashlib
import ipaddress
import socket
import time
import uuid
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.hub.adapters.impressum import (
    find_impressum_link,
    names_firm,
    parse_impressum,
    public_host,
)
from app.domain.hub.adapters.partner_pages import page_text, strip_control
from app.domain.hub.domains import registrable_domain
from app.domain.hub.models import (
    SITE_BLOCKED,
    SITE_ERROR,
    SITE_NO_IMPRESSUM,
    SITE_NOT_NAMED,
    SITE_VERIFIED,
    HubAgencyProfile,
    HubCompany,
    HubObservation,
    HubSiteCheck,
)

logger = get_logger(__name__)

STATUS_BLOCKED = 1  # robots.txt, or an unsafe host/redirect
STATUS_ERROR = 2  # network failure
_MAX_REDIRECTS = 5
_MAX_HTML = 2_000_000
#: A network error is "not now", not "not ever".
ERROR_RETRY_AFTER = dt.timedelta(days=7)


@dataclasses.dataclass(frozen=True)
class SitePage:
    url: str
    final_url: str
    status: int
    html: str | None
    note: str | None = None


async def _resolves_public(host: str) -> bool:
    """Every address the name resolves to is a public one. A public name that
    points into a private network is refused like an IP literal."""
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except OSError:
        return False
    addresses = {info[4][0] for info in infos}
    return bool(addresses) and all(ipaddress.ip_address(a).is_global for a in addresses)


class SiteFetcher:
    """Fetches agency homepages and Impressum pages politely and safely."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        per_host_delay: float = 1.0,
        user_agent: str | None = None,
    ) -> None:
        self._client = client
        self._owns = False
        self._delay = per_host_delay
        self._ua = user_agent or settings.hub_user_agent
        self._robots: dict[str, robotparser.RobotFileParser] = {}
        self._last_hit: dict[str, float] = {}

    async def __aenter__(self) -> SiteFetcher:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=15,
                follow_redirects=False,  # by hand, each hop checked
                headers={"User-Agent": self._ua, "Accept-Language": "de"},
            )
            self._owns = True
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._owns and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _pace(self, host: str) -> None:
        last = self._last_hit.get(host)
        if last is not None and self._delay:
            wait = self._delay - (time.monotonic() - last)
            if wait > 0:
                await asyncio.sleep(wait)
        self._last_hit[host] = time.monotonic()

    async def _safe(self, url: str) -> bool:
        return public_host(url) and await _resolves_public(urlparse(url).hostname or "")

    async def _robots_allow(self, url: str) -> bool:
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        parser = self._robots.get(origin)
        if parser is None:
            parser = robotparser.RobotFileParser()
            lines: list[str] = []
            target = origin + "/robots.txt"
            try:
                for _ in range(_MAX_REDIRECTS):
                    r = await self._client.get(target)
                    if r.is_redirect and r.headers.get("location"):
                        target = urljoin(target, r.headers["location"])
                        if not await self._safe(target):
                            break
                        continue
                    if r.status_code in (401, 403):
                        lines = ["User-agent: *", "Disallow: /"]
                    elif r.status_code == 200:
                        lines = r.text.splitlines()
                    break
            except httpx.HTTPError:
                lines = []
            parser.parse(lines)
            self._robots[origin] = parser
        return parser.can_fetch(self._ua, url)

    async def get(self, url: str) -> SitePage:
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            if not await self._safe(current):
                return SitePage(url, current, STATUS_BLOCKED, None, "not a public host")
            if not await self._robots_allow(current):
                return SitePage(url, current, STATUS_BLOCKED, None, "robots.txt disallows")
            await self._pace(urlparse(current).netloc)
            try:
                r = await self._client.get(current)
            except Exception as exc:  # noqa: BLE001 — one site must not end a batch
                return SitePage(url, current, STATUS_ERROR, None, type(exc).__name__)
            if r.is_redirect and r.headers.get("location"):
                current = urljoin(current, r.headers["location"])
                continue
            if r.status_code != 200:
                return SitePage(url, current, r.status_code, None)
            try:
                html = strip_control(r.text[:_MAX_HTML])
            except Exception as exc:  # noqa: BLE001 — a broken charset
                return SitePage(url, current, STATUS_ERROR, None, type(exc).__name__)
            return SitePage(url, current, 200, html)
        return SitePage(url, current, STATUS_BLOCKED, None, "too many redirects")


def _company_facts(facts) -> dict:
    """What may be stored: company facts only — never `facts.people`."""
    register = (
        f"{facts.register_type} {facts.register_number}" if facts.register_number else None
    )
    return {
        k: v
        for k, v in {
            "vat_id": facts.vat_id,
            "register": register,
            "register_court": facts.register_court,
            "phone": facts.phone,
            "emails": facts.emails or None,
        }.items()
        if v
    }


def _pick(profiles, checks: dict[str, HubSiteCheck], now: dt.datetime, limit: int):
    picked: list[tuple[HubAgencyProfile, str]] = []
    for profile in profiles:
        candidates = [c for c in (profile.website_candidates or []) if not c.get("likely_client")]
        if any(
            checks.get(c["domain"]) is not None and checks[c["domain"]].status == SITE_VERIFIED
            for c in candidates
        ):
            continue  # this agency's website is known
        for c in candidates:
            check = checks.get(c["domain"])
            if check is not None:
                checked_at = check.checked_at
                if checked_at.tzinfo is None:  # SQLite
                    checked_at = checked_at.replace(tzinfo=dt.UTC)
                if not (check.status == SITE_ERROR and checked_at < now - ERROR_RETRY_AFTER):
                    continue
            picked.append((profile, c["domain"]))
            break
        if len(picked) >= limit:
            break
    return picked


async def check_agency_sites(session: AsyncSession, *, fetcher, limit: int = 10) -> dict[str, int]:
    """Check up to `limit` agencies' best unchecked website candidate."""
    now = dt.datetime.now(dt.UTC)
    checks = {c.domain: c for c in (await session.execute(select(HubSiteCheck))).scalars()}
    profiles = (
        await session.execute(
            select(HubAgencyProfile)
            .where(HubAgencyProfile.verdict.in_(("agency", "unclear")))
            .order_by(HubAgencyProfile.score.desc(), HubAgencyProfile.name)
        )
    ).scalars().all()
    counts = {"checked": 0, SITE_VERIFIED: 0, SITE_NOT_NAMED: 0, SITE_NO_IMPRESSUM: 0, SITE_BLOCKED: 0, SITE_ERROR: 0}
    for profile, domain in _pick(profiles, checks, now, limit):
        status = await _check_one(session, fetcher, profile, domain, now, checks)
        await session.commit()
        counts["checked"] += 1
        counts[status] += 1
    logger.info("agency site checks: %s", counts)
    return counts


async def _check_one(session, fetcher, profile, domain, now, checks) -> str:
    home = await fetcher.get(f"https://{domain}/")
    impressum_url: str | None = None
    page = home
    if home.status == 200:
        site = registrable_domain(urlparse(home.final_url).hostname) or domain
        impressum_url = find_impressum_link(home.html, home.final_url, site) or urljoin(home.final_url, "/impressum")
        page = await fetcher.get(impressum_url)
    text = page_text(page.html) if page.status == 200 else ""
    facts = parse_impressum(text)

    ids = [uuid.UUID(str(i)) for i in profile.company_ids]
    companies = (
        await session.execute(select(HubCompany).where(HubCompany.id.in_(ids)))
    ).scalars().all() if ids else []
    names = sorted({c.name for c in companies} | {profile.name})

    if page.status == STATUS_BLOCKED:
        status = SITE_BLOCKED
    elif page.status == STATUS_ERROR or page.status >= 500:
        status = SITE_ERROR
    elif not facts.is_impressum:
        status = SITE_NO_IMPRESSUM
    elif names_firm(text, names):
        status = SITE_VERIFIED
    else:
        status = SITE_NOT_NAMED

    observation = HubObservation(
        source="impressum",
        request_url=(impressum_url or home.url)[:1000],
        http_status=page.status if page.status >= 100 else None,
        robots_allowed=page.status != STATUS_BLOCKED,
        record_count=1 if facts.is_impressum else 0,
        content_hash=hashlib.sha256(text.encode()).hexdigest() if text else None,
        fetched_at=now,
        note=(f"{status}" + (f"; {page.note}" if page.note else ""))[:500],
    )
    session.add(observation)
    await session.flush()

    stored = _company_facts(facts) if status == SITE_VERIFIED else {}
    if status == SITE_VERIFIED:
        # Backfill only — a fact already on record outranks this one.
        for company in companies:
            if company.website_domain is None:
                company.website_domain = domain
            if company.vat_id is None and facts.vat_id:
                company.vat_id = facts.vat_id
            if company.register_number is None and stored.get("register"):
                company.register_number = stored["register"]
                company.register_court = company.register_court or facts.register_court

    check = checks.get(domain)
    if check is None:
        check = HubSiteCheck(domain=domain, group_key=profile.group_key, status=status, checked_at=now)
        session.add(check)
        checks[domain] = check
    check.group_key = profile.group_key
    check.status = status
    check.impressum_url = impressum_url[:1000] if impressum_url else None
    check.observation_id = observation.id
    check.facts = stored
    check.checked_at = now
    return status
