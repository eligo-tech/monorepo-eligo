---
name: add-hub-source
description: Add a new public job/company source to the information hub (a SourceAdapter), or debug an existing one. Use when integrating a job board, ATS feed, employment-service API or aggregator (Personio, Greenhouse, Lever, Adzuna, AMS, schema.org JSON-LD), when ingestion returns wrong counts, or when a crawl looks complete but is silently truncated.
tools: Read, Glob, Grep, Bash, Edit, Write
---

# Adding a hub source — eligo-tech

Sources sit behind the `SourceAdapter` protocol in
`backend/app/domain/hub/adapters/`. Adding one is a new module plus one line in
`factory.py`. Read `adapters/base.py` and `adapters/bundesagentur.py` first —
the latter is the reference implementation.

Before writing anything, read the `architecture-review` skill's RULE 1 and
RULE 2. A source adapter must never be reachable from the UI, and must never
put a natural person into the shared corpus.

---

## The shape

Every adapter splits in two, and the split is not stylistic:

```python
def parse_response(payload, *, request_url, fetched_at, http_status) -> FetchResult:
    """PURE. No I/O, no DB. This is what CI exercises."""

class MySourceAdapter:
    name = "mysource"
    async def fetch(self, query: SourceQuery) -> FetchResult:
        """Thin HTTP wrapper. Calls parse_response."""
```

Why: CI runs the real parser against a captured payload with **no network**, and
stored evidence can be re-parsed later without re-fetching it. Capture a real
response into `backend/tests/fixtures/` and test against that.

A failed fetch is **returned, not raised** — `FetchResult(http_status=503, …)`.
A failure is still evidence and must land as an observation.

## Steps

1. `adapters/<source>.py` — `parse_response` + adapter class.
2. One line in `adapters/factory.py`.
3. Capture a real payload into `tests/fixtures/<source>.json`.
4. Tests against the fixture: field mapping, timezone-aware dates, records that
   must be **dropped** (no employer, no external id), and the query builder.
5. Config in `core/config.py` if it needs a base URL or key (prefix `ELIGO_`).

## Non-negotiables

- **Normalize to `SourcedPosting` / `SourcedCompany`.** Never leak source-shaped
  dicts past the adapter.
- **`external_id` must be stable across crawls** — it is half of the
  `(source, external_id)` uniqueness constraint. If the source has no stable id,
  derive one deterministically and say so in a comment.
- **Timezone-aware datetimes**, always UTC. A naive datetime compares falsely
  against everything else in the schema.
- **Drop what cannot be attributed or deduplicated** (no employer name, no
  reference) inside `parse_response`, and let the count difference show up in
  the ingest summary. A silent drop is a bug.
- **Exclude staffing agencies by default** where the source can. They are
  competitors, not leads. `SourceQuery.include_staffing` defaults False.
- **Respect robots.txt / ToS.** `FetchResult.robots_allowed=False` is a blocking
  precondition. Never add a source that requires authentication to read — see
  `agents/market_map.py`.

---

## Gotchas learned the hard way — measure, do not trust the docs

Each of these was a real defect in this repo, found by querying the source
rather than reading about it. Assume a new source has its own versions.

**1. Documented parameters may be enums, silently.**
The Bundesagentur's `veroeffentlichtseit` is documented as "days, 0–100". It
honours only `{0, 1, 7, 14, 28}` and returns the **unfiltered set** for anything
else — a default of `2` fetched all 709,734 postings nightly instead of one
day's. Measure every filter parameter:

```bash
for v in 0 1 2 3 7 14 28 30; do
  echo -n "  $v: "
  curl -s -H "X-API-Key: …" "…?veroeffentlichtseit=$v&size=1" \
    | python3 -c "import json,sys;print(json.load(sys.stdin).get('maxErgebnisse'))"
done
```
If a value does not change the total, the filter is being ignored.

**2. There is usually a hard result ceiling, and it is not the page size.**
This API returns HTTP 400 past `page=100`, so no query reaches more than 10,000
results — against 709,734 open postings. Find the ceiling before designing the
crawl, then shard beneath it.

**3. Page on the SOURCE's total, never on the count you parsed.**
`fetched` is post-parse. A page holding one unattributable record returns 99,
and treating that as a short page silently truncates the whole shard. Use
`total_available`:

```python
if summary["fetched"] == 0 or (total is not None and page * size >= total):
    break
```

**4. A shard key that is a place NAME is not a region selector.**
`wo=Hessen` returns 82 postings for an entire German state, because a village
shares the name. Verify a shard set is exhaustive by summing it against the
unsharded total:

```
sum(shards) / unsharded_total   # ours is 83% — known, printed on every run
```
If it is under 100%, print the coverage on every run. Never let a bounded crawl
read as complete coverage.

**5. Facets are truncated.** `arbeitsort_plz` returns only its top 200 entries
(17% of postings), so it cannot supply a shard plan. Check `sum(counts)` against
the total before believing a facet.

**6. A wider time window does not buy coverage** once a shard exceeds the
ceiling — it just discards more. Widen shards, not windows.

**7. Rate-limit.** Being a considerate client of a free public service is a
design constraint. `--delay` between requests, and identify the crawler in the
User-Agent (`settings.hub_user_agent`).

---

## Verify a new adapter end to end

```bash
cd backend
.venv/bin/python -m pytest tests/test_hub_ingest.py -q        # offline, fixture-based
# then against a scratch DB and the real source
rm -f /tmp/src.db
ELIGO_DATABASE_URL="sqlite+aiosqlite:////tmp/src.db" \
ELIGO_ADMIN_DATABASE_URL="sqlite+aiosqlite:////tmp/src.db" \
ELIGO_AUTH_ENABLED=false ELIGO_DB_SSL=false \
  .venv/bin/python -m alembic upgrade head
# run the backfill for one small shard, then run it AGAIN:
# a second pass must report +0 created / ~N updated. If it creates rows twice,
# `external_id` is not stable or the dedupe ladder is wrong.
```
