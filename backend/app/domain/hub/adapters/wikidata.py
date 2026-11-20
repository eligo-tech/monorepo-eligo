"""Wikidata P1128 "number of employees" for corpus employers (ELI-54).

Free (CC0) and public. Matched ONLY by exact identity: an item counts when its
official website (P856) reduces to the company's stored registrable domain
(`resolution.normalize_domain`). Never by name — "Müller GmbH" names
thousands of firms. A domain that two items claim is ambiguous and skipped.

The query lists each domain's literal URL spellings (http/https, with and
without `www.`, with and without the trailing slash) as IRIs, which the
endpoint answers from its index; a site recorded with a path ("…/de/") is
missed on purpose rather than found by a substring scan. Every match is then
re-checked in Python by `normalize_domain` equality.

Of an item's P1128 statements (deprecated ones excluded by the query) the
newest by point in time (P585) wins; an undated figure counts as oldest, and
two different figures for the same date are ambiguous and skipped.

Etiquette (https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual):
a descriptive User-Agent without personal data (`settings.hub_user_agent`),
batched queries via POST, one request at a time with a pause between them,
and any answer but 200 (a 429, a 5xx, a timeout) ends the pass — the weekly
job resumes next week. A query times out after 30 s, so one operator request
(`BATCH` x 3 domains) stays well inside the job's HTTP timeout.
`parse_bindings` is pure, so CI tests it with no network.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.domain.hub.resolution import normalize_domain

SOURCE_NAME = "wikidata"
ENDPOINT = "https://query.wikidata.org/sparql"
#: Domains per query: 8 IRIs each, well inside the endpoint's limits.
BATCH = 40
#: Seconds between queries, and per query.
PAUSE = 1.0
QUERY_TIMEOUT = 30.0


@dataclass(frozen=True)
class WikidataSize:
    qid: str
    employees: int
    as_of: dt.datetime | None

    @property
    def evidence(self) -> str:
        when = self.as_of.date().isoformat() if self.as_of else "ohne Datum"
        return f"Wikidata {self.qid}: Anzahl der Beschäftigten (P1128) = {self.employees} (Stand {when})"


def _spellings(domain: str) -> list[str]:
    return [
        f"<{scheme}://{host}{slash}>"
        for scheme in ("https", "http")
        for host in (domain, f"www.{domain}")
        for slash in ("/", "")
    ]


def build_query(domains: list[str]) -> str:
    values = " ".join(s for d in domains for s in _spellings(d))
    return (
        "SELECT ?item ?site ?n ?t WHERE { "
        f"VALUES ?site {{ {values} }} "
        "?item wdt:P856 ?site . "
        "?item p:P1128 ?st . ?st ps:P1128 ?n . ?st wikibase:rank ?rank . "
        "FILTER(?rank != wikibase:DeprecatedRank) "
        "OPTIONAL { ?st pq:P585 ?t } }"
    )


def _when(raw: str | None) -> dt.datetime | None:
    if not raw:
        return None
    try:
        value = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def parse_bindings(payload: dict[str, Any], domains: list[str]) -> dict[str, WikidataSize]:
    """SPARQL JSON → the unambiguous size per asked domain. Pure."""
    asked = set(domains)
    items: dict[str, set[str]] = {}
    figures: dict[str, list[tuple[int, dt.datetime | None]]] = {}
    for b in (payload.get("results") or {}).get("bindings") or []:
        site = (b.get("site") or {}).get("value")
        item = (b.get("item") or {}).get("value", "")
        raw_n = (b.get("n") or {}).get("value")
        domain = normalize_domain(site)
        if domain not in asked or not item or raw_n is None:
            continue
        try:
            n = int(float(raw_n))
        except ValueError:
            continue
        if n <= 0:
            continue
        qid = item.rsplit("/", 1)[-1]
        items.setdefault(domain, set()).add(qid)
        figures.setdefault(qid, []).append((n, _when((b.get("t") or {}).get("value"))))

    out: dict[str, WikidataSize] = {}
    for domain, qids in items.items():
        if len(qids) != 1:
            continue  # two items claim this website: not an identity
        (qid,) = qids
        oldest = dt.datetime.min.replace(tzinfo=dt.UTC)
        latest = max((t or oldest) for _, t in figures[qid])
        values = {n for n, t in figures[qid] if (t or oldest) == latest}
        if len(values) != 1:
            continue  # two figures for the same date
        out[domain] = WikidataSize(qid, values.pop(), latest if latest != oldest else None)
    return out


class WikidataClient:
    """Batched, paced lookups; each request recorded as a `hub_observations` row."""

    def __init__(self, *, http: httpx.AsyncClient | None = None, pause: float = PAUSE) -> None:
        self._http = http
        self._pause = pause

    async def _post(self, query: str) -> httpx.Response:
        headers = {"User-Agent": settings.hub_user_agent, "Accept": "application/sparql-results+json"}
        if self._http is not None:
            return await self._http.post(ENDPOINT, data={"query": query}, headers=headers)
        async with httpx.AsyncClient(timeout=QUERY_TIMEOUT) as http:
            return await http.post(ENDPOINT, data={"query": query}, headers=headers)

    async def lookup(self, domains: list[str]) -> tuple[dict[str, WikidataSize], set[str], list]:
        """Matches per domain, the domains whose query failed (not stamped),
        and one `HubObservation` per request for the caller to store — no
        database session is held while the endpoint answers."""
        from app.domain.hub.models import HubObservation

        found: dict[str, WikidataSize] = {}
        failed: set[str] = set()
        observations: list = []
        for i in range(0, len(domains), BATCH):
            batch = domains[i : i + BATCH]
            if failed:  # the endpoint refused once: stop, retry next week
                failed.update(batch)
                continue
            if i:
                await asyncio.sleep(self._pause)
            now = dt.datetime.now(dt.UTC)
            status: int | None
            try:
                response = await self._post(build_query(batch))
                status = response.status_code
                payload = response.json() if status == 200 else {}
            except (httpx.HTTPError, ValueError):
                status, payload = None, {}
            matches = parse_bindings(payload, batch) if status == 200 else {}
            observations.append(
                HubObservation(
                    source=SOURCE_NAME,
                    request_url=ENDPOINT,
                    http_status=status,
                    record_count=len(matches),
                    fetched_at=now,
                    note=f"P1128 for {len(batch)} domains: {len(matches)} matched"[:500],
                    content_hash=hashlib.sha256(
                        json.dumps(payload, sort_keys=True).encode("utf-8")
                    ).hexdigest() if payload else None,
                    payload={"domains": batch, "matches": {d: m.qid for d, m in matches.items()}},
                )
            )
            if status != 200:
                failed.update(batch)
                continue
            found.update(matches)
        return found, failed, observations
