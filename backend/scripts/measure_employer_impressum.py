"""Measure, before building: can an employer's Impressum give us its phone?

ELI-30, last fallback: when no ad names a contact person, show the phone
number from the employer's Impressum (plus VAT id and register number).
Only 9 of 184k employers without a contact person have a known website, so the
website must come from the ads themselves. This script measures how often
that works, on a random sample, with the SAME code the agency check uses:

    ad texts + the BA's `externeURL` → `domains.domain_candidates` → `SiteFetcher` (robots.txt,
    identified, paced, public hosts only) → `find_impressum_link` →
    `parse_impressum` → `names_firm` (the Impressum must name the employer)

READ-ONLY. Nothing is written to any database: the DB is read in a read-only
transaction that is rolled back, and the result goes to a local JSON file.
People named in an Impressum are never written out — only company facts.

    MEASURE_DSN=postgresql://… python -m scripts.measure_employer_impressum \
        --sample 1000 --out /tmp/impressum_measure.json
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import logging
import os
import random
import sys
from urllib.parse import urljoin, urlparse

import asyncpg

from app.domain.hub.adapters.impressum import find_impressum_link, names_firm, parse_impressum
from app.domain.hub.adapters.partner_pages import page_text
from app.domain.hub.domains import domain_candidates, registrable_domain
from app.domain.hub.sites import STATUS_BLOCKED, STATUS_ERROR, SiteFetcher

#: Employers with open ads, no person named in any ad, not a suspected sole
#: trader (a sole trader's phone is a person's phone — never stored).
SAMPLE = """
select c.id, c.name
from hub_companies c
where c.suspected_natural_person is not true
  and exists (select 1 from hub_job_postings p
              where p.hub_company_id = c.id and p.is_active and p.segment = 'employer')
  and not exists (select 1 from hub_ad_contacts a where a.hub_company_id = c.id)
order by md5(c.id::text || $1)
limit $2
"""

ADS = """
select p.id, coalesce(pl.description, '') || ' ' || coalesce(pl.source_page_text, '')
       || ' ' || coalesce(pl.raw::json ->> 'externeURL', '')
from hub_job_postings p
join hub_posting_payload pl on pl.hub_job_posting_id = p.id
where p.hub_company_id = $1 and p.is_active
limit 20
"""


async def load(dsn: str, sample: int, seed: str) -> list[dict]:
    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    tr = conn.transaction(readonly=True)
    await tr.start()
    try:
        await conn.execute("set local statement_timeout = '300s'")
        rows = await conn.fetch(SAMPLE, seed, sample)
        out = []
        for r in rows:
            ads = [(str(a[0]), a[1]) for a in await conn.fetch(ADS, r["id"])]
            out.append({"id": str(r["id"]), "name": r["name"], "ads": ads})
        return out
    finally:
        await tr.rollback()
        await conn.close()


def outcome(page_status: int, is_impressum: bool, named: bool) -> str:
    """Same verdicts as `sites._check_one`."""
    if page_status in (STATUS_BLOCKED, 401, 403):
        return "blocked"
    if page_status in (STATUS_ERROR, 408, 429) or page_status >= 500:
        return "error"
    if not is_impressum:
        return "no_impressum"
    return "verified" if named else "not_named"


#: Candidates tried per employer: the best, and one more if it fails.
MAX_TRIES = 2


async def _try(fetcher: SiteFetcher, name: str, domain: str) -> dict:
    home = await fetcher.get(f"https://{domain}/")
    page, impressum_url = home, None
    if home.status == 200:
        site = registrable_domain(urlparse(home.final_url).hostname) or domain
        impressum_url = find_impressum_link(home.html, home.final_url, site) or urljoin(home.final_url, "/impressum")
        page = await fetcher.get(impressum_url)
    text = page_text(page.html) if page.status == 200 else ""
    facts = parse_impressum(text)
    row = {
        "domain": domain,
        "result": outcome(page.status, facts.is_impressum, names_firm(text, [name])),
        "impressum_url": impressum_url,
        "note": page.note,
    }
    if row["result"] == "verified":  # company facts only — never facts.people
        row.update(
            phone=facts.phone,
            vat_id=facts.vat_id,
            register=" ".join(x for x in (facts.register_type, facts.register_number) if x) or None,
            register_court=facts.register_court,
        )
    return row


async def check(fetcher: SiteFetcher, company: dict) -> dict:
    cands = domain_candidates(company["ads"], firm_names=[company["name"]])
    row = {"name": company["name"], "candidates": [c["domain"] for c in cands]}
    if not cands:
        row["result"] = "no_domain"
        return row
    row["tries"] = []
    for cand in cands[:MAX_TRIES]:
        t = await _try(fetcher, company["name"], cand["domain"])
        t["name_match"] = cand["name_match"]
        row["tries"].append({k: t[k] for k in ("domain", "result", "name_match")})
        row.update(t)
        if t["result"] == "verified":
            break
    return row


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=1000)
    ap.add_argument("--seed", default="eli30")
    ap.add_argument("--concurrency", type=int, default=24)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    logging.disable(logging.INFO)  # httpx/httpcore debug lines drown the summary
    dsn = os.environ.get("MEASURE_DSN")
    if not dsn:
        sys.exit("MEASURE_DSN is required")

    companies = await load(dsn, args.sample, args.seed)
    print(f"sample: {len(companies)} employers without a named contact", flush=True)
    random.Random(args.seed).shuffle(companies)  # spread hosts across workers
    sem = asyncio.Semaphore(args.concurrency)
    rows: list[dict] = []
    async with SiteFetcher() as fetcher:

        async def one(c: dict) -> None:
            async with sem:
                try:
                    rows.append(await check(fetcher, c))
                except Exception as exc:  # noqa: BLE001 — one site must not end the run
                    rows.append({"name": c["name"], "result": "error", "note": type(exc).__name__})
                if len(rows) % 100 == 0:
                    print(f"  {len(rows)} done", flush=True)

        await asyncio.gather(*(one(c) for c in companies))

    n = len(rows)
    results = collections.Counter(r["result"] for r in rows)
    verified = [r for r in rows if r["result"] == "verified"]
    summary = {
        "sample": n,
        "results": dict(results),
        "with_domain": n - results["no_domain"],
        "verified": len(verified),
        "verified_on_second_try": sum(1 for r in verified if len(r["tries"]) > 1),
        "blocked_notes": dict(collections.Counter(r.get("note") for r in rows if r["result"] == "blocked")),
        "verified_with_phone": sum(1 for r in verified if r.get("phone")),
        "verified_with_vat": sum(1 for r in verified if r.get("vat_id")),
        "verified_with_register": sum(1 for r in verified if r.get("register")),
    }
    print(json.dumps(summary, indent=2))
    with open(args.out, "w") as f:
        json.dump({"summary": summary, "rows": rows}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    asyncio.run(main())
