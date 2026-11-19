"""Employer headcount — "Mitarbeitende" on Markt (ELI-54).

The corpus had no headcount: ELI-27's size filter counts open ADS. This module
gives `hub_companies` a real one from three free, public sources — no paid or
licensed data:

* **The employer's own ad texts** (`backfill`). "Mit rund 250 Mitarbeitenden
  sind wir …" is a public company fact the employer published. Read by
  deterministic rules (`extract_statements`), never a model. Measured on
  samples (2026-11-19): such a statement is in ~2.5% of BA ads and ~13% of
  EURES AT/CH ads.
* **Wikidata P1128** (`wikidata_backfill`, `adapters/wikidata.py`), matched
  ONLY by exact identity — the item's official website (P856) has the
  company's registrable domain. Never by name.
* **EURES `organisationSizeCode`** (`eures_size`), at ingest, when the source
  fills it. Measured: empty in 600/600 sampled ads; mapped only when the code
  spells a band ("10-49", "250+"), never guessed.

Which value wins (`replaces`): the source that set it may always refresh it;
otherwise the NEWEST DATED claim wins — an ad statement is dated by when the
ad text was fetched, a Wikidata figure by its point-in-time qualifier (P585),
an undated one counts as oldest. So a 2021 Wikidata figure never replaces
this month's ad statement, and a newer one replaces an older ad statement.

Machine-only like every corpus write (ARCHITECTURE.md RULE 1): the weekly
chain calls the passes through operator routes; nothing a user does reads,
fetches or writes a headcount. The values are company facts — no person —
and carry their provenance on the row: source kind, source ref (`<source>:
<ad id>` or the Wikidata QID), the quoted sentence, the rules version, when.

The rules are CONSERVATIVE. Skipped: a team, department, site or ward; a
leadership span ("führen 8 Mitarbeiter"); people served or the customers'
staff ("Lohnabrechnung für 200 Mitarbeiter unserer Kunden"); hiring counts
and thresholds ("ab 10 Mitarbeitern"); a parent group's total ("Teil der
XY-Gruppe mit 50.000"); and a number with no employer context at all. A
worldwide total ("weltweit 3.500") is kept but used only when the employer's
ads say nothing else. When a clause is unclear it is skipped: a missing size
costs one row in a filter, a wrong one misleads.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, bindparam, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.hub import suppression
from app.domain.hub.models import EMPLOYER, HubCompany, HubJobPosting, HubPostingPayload

#: Bump when the extraction rules change: every company is then re-read, and a
#: value the new rules no longer find is cleared.
HEADCOUNT_RULES = 1

#: Sources, as stored in `hub_companies.employees_source`.
AD_TEXT = "ad_text"
WIKIDATA = "wikidata"
EURES = "eures"
#: Tie-break on an equal date only: the employer's structured field, then its
#: own words, then a third party's.
_PRECEDENCE = {EURES: 3, AD_TEXT: 2, WIKIDATA: 1}

#: The Markt filter's buckets (ELI-54), inclusive; None = open-ended.
BUCKETS: dict[str, tuple[int, int | None]] = {
    "1-3": (1, 3),
    "4-10": (4, 10),
    "11-50": (11, 50),
    "51-150": (51, 150),
    "151-300": (151, 300),
    "301-650": (301, 650),
    "651-1000": (651, 1000),
    "1001-5000": (1001, 5000),
    "5001-10000": (5001, 10000),
    "10001+": (10001, None),
}

#: The filter is offered once this share of hiring employers has a size.
FILTER_MIN_COVERAGE = 0.30

#: Ads read per company: the newest texts. A chain's statement repeats in
#: every ad; reading its 2,000 adds IO, not evidence.
ADS_PER_COMPANY = 20

_MAX_QUOTE = 300
_PLAUSIBLE = range(1, 1_000_001)


@dataclass(frozen=True)
class Statement:
    """One headcount statement in one ad: inclusive bounds, max None = open."""

    min: int
    max: int | None
    #: "local" — the employer's own; "worldwide" — a worldwide total.
    scope: str
    quote: str


@dataclass(frozen=True)
class Choice:
    """The value one company's ads support, with its evidence."""

    min: int
    max: int | None
    scope: str
    quote: str
    ref: str
    as_of: dt.datetime | None


# --- the rules -------------------------------------------------------------------

_NUM = r"\d{1,3}(?:[.,’'   ]\d{3})+(?!\d)|\d+"
_QUAL = (
    r"weit über|mehr als|more than|ca\.|ca|circa|rund|etwa|ungefähr|knapp|fast|nahezu|"
    r"annähernd|über|gut|insgesamt|aktuell|derzeit|inzwischen|mittlerweile|around|about|"
    r"approximately|over|nearly|almost"
)
_OPEN_QUALS = {"weit über", "mehr als", "more than", "über", "gut", "over"}
_NOUN = (
    r"Mitarbeitern|Mitarbeitende[nr]?|"
    r"Mitarbeiter(?:\*innen|:innen|_innen|/-innen|/innen|Innen|innen|in)?|"
    r"Beschäftigte[nr]?|Angestellte[nr]?|Kolleginnen und Kollegen|Kolleg(?:inn)?en|"
    r"employees|staff members"
)
#: Up to two lowercase adjectives: "250 engagierte Mitarbeitende".
_ADJ = r"(?-i:(?:[a-zäöüß]+(?:e|en|er)\s+){0,2})"
_AMOUNT = (
    rf"(?:zwischen\s+(?P<a1>{_NUM})\s+und\s+(?P<b1>{_NUM})"
    rf"|(?P<a2>{_NUM})\s*(?:-|–|—|bis)\s*(?P<b2>{_NUM})"
    rf"|(?P<n>{_NUM})\s*(?P<plus>\+)?)"
)
_STATEMENT = re.compile(
    rf"(?<![\w.])(?:(?P<qual>{_QUAL})\s+)?{_AMOUNT}\s*{_ADJ}(?P<noun>{_NOUN})\b",
    re.IGNORECASE,
)
#: "Mitarbeiterzahl: 51-200" — a labelled field; the label is the context.
_LABELLED = re.compile(
    r"\b(?:Mitarbeiterzahl|Mitarbeiteranzahl|Anzahl (?:der )?Mitarbeiter(?:innen|enden)?|"
    r"Unternehmensgröße|Firmengröße|Betriebsgröße|Company size|Number of employees)"
    rf"\s*:?\s*(?:(?P<a2>{_NUM})\s*(?:-|–|—|bis)\s*(?P<b2>{_NUM})|(?P<n>{_NUM})\s*(?P<plus>\+)?)",
    re.IGNORECASE,
)

#: In the clause BEFORE the number: not the employer's headcount.
_SKIP_BEFORE = re.compile(
    r"\b(?:teams?|abteilung\w*|bereich\w*|ressort|referat|fachbereich\w*|standort\w*|"
    r"niederlassung\w*|filiale\w*|zweigstelle\w*|werk|werks|station\w*|schicht\w*|büro\w*|"
    r"führen|führe|führst|führt|führung\w*|leiten|leitet|leitung\w*|geleitet|"
    r"verantwortung\w*|verantwortlich\w*|verantworten|disziplinarisch\w*|unterstellt\w*|"
    r"für|betreu\w*|unterstütz\w*|berat\w*|versorg\w*|\w*abrechnung\w*|"
    r"such\w*|gesucht|einstell\w*|verstärk\w*|ab|bis zu|pro|je|jeweils|durchschnittlich|"
    r"kunde\w*|kundin\w*|mandant\w*|auftraggeber\w*|klient\w*|patient\w*|bewohner\w*|"
    r"schüler\w*|kinder\w*|gäste\w*|mitglied\w*)\b",
    re.IGNORECASE,
)
#: Right AFTER the noun: a hiring tag or someone else's staff.
_SKIP_AFTER = re.compile(
    r"^\s*\((?:[mwdxi]\s*/\s*){1,3}[mwdxi]\)|^\s*\(gn\)|^\s*\(all genders?\)|"
    r"\b(?:unserer|unseren|der|ihrer|seiner) (?:kunden|mandanten|auftraggeber|klienten)\b|"
    r"\b(?:pro|je)\b|\bim team\b|\bin (?:unserem|ihrem|einem) team\b|\bin der abteilung\b|"
    r"\bam standort\b|\bim bereich\b|\bgesucht\b",
    re.IGNORECASE,
)
#: Anywhere in the sentence: a parent group's total.
_GROUP = re.compile(
    r"\b(?:teil (?:der|des|einer|eines)|gehör\w*|tochter\w*|\w*gruppe\w*|group|konzern\w*|"
    r"holding|verbund\w*|muttergesellschaft|mutterkonzern)\b",
    re.IGNORECASE,
)
_WORLDWIDE = re.compile(
    r"\b(?:weltweit\w*|global\w*|worldwide|international\w*|europaweit|countries|"
    r"in (?:über |mehr als )?\d+ ländern)\b",
    re.IGNORECASE,
)
#: Some employer context before the number, or the clause is not about one.
_CONTEXT = re.compile(
    r"\b(?:wir|uns|unser\w*|mit|beschäftig\w*|zähl\w*|sind|ist|arbeiten|arbeitet|"
    r"engagier\w*|als|insgesamt|hat|haben|heute|we|our|with|employ\w*|has|have)\b",
    re.IGNORECASE,
)
_SENTENCES = re.compile(r"\n+|[•·▪]|(?<=[!?;])\s+|(?<=\.)\s+(?=[A-ZÄÖÜ„\"])")
_BEFORE_WINDOW = 80
_AFTER_WINDOW = 50


def _number(raw: str) -> int:
    return int(re.sub(r"[.,’'   ]", "", raw))


def _bounds(m: re.Match) -> tuple[int, int | None] | None:
    groups = m.groupdict()
    a = groups.get("a1") or groups.get("a2")
    b = groups.get("b1") or groups.get("b2")
    if a and b:
        lo, hi = _number(a), _number(b)
        if lo > hi or lo not in _PLAUSIBLE or hi not in _PLAUSIBLE:
            return None
        return lo, hi
    n = _number(groups["n"])
    if n not in _PLAUSIBLE:
        return None
    qual = (groups.get("qual") or "").lower()
    if groups.get("plus") or qual in _OPEN_QUALS:
        return n, None
    return n, n


def _quote(sentence: str, start: int, end: int) -> str:
    if len(sentence) <= _MAX_QUOTE:
        return sentence
    lo = max(0, start - 150)
    return ("…" if lo else "") + sentence[lo : lo + _MAX_QUOTE].strip() + "…"


def extract_statements(text: str | None) -> list[Statement]:
    """Every employer headcount statement in an ad text, conservatively."""
    if not text:
        return []
    found: list[Statement] = []
    for raw in _SENTENCES.split(text):
        sentence = " ".join(raw.split())
        if not sentence or not re.search(r"\d", sentence):
            continue
        if _GROUP.search(sentence):
            continue
        scope = "worldwide" if _WORLDWIDE.search(sentence) else "local"
        taken: list[tuple[int, int]] = []
        for m in _LABELLED.finditer(sentence):
            bounds = _bounds(m)
            if bounds:
                taken.append(m.span())
                found.append(Statement(*bounds, scope, _quote(sentence, *m.span())))
        for m in _STATEMENT.finditer(sentence):
            if any(s < m.end() and m.start() < e for s, e in taken):
                continue
            before = sentence[max(0, m.start() - _BEFORE_WINDOW) : m.start()]
            after = sentence[m.end() : m.end() + _AFTER_WINDOW]
            if _SKIP_BEFORE.search(before) or _SKIP_AFTER.search(after):
                continue
            if not _CONTEXT.search(before):
                continue
            bounds = _bounds(m)
            if bounds:
                found.append(Statement(*bounds, scope, _quote(sentence, *m.span())))
    return found


OLDEST = dt.datetime.min.replace(tzinfo=dt.UTC)


def as_utc(value: dt.datetime | None) -> dt.datetime | None:
    """SQLite returns naive datetimes; they are UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def aggregate(items: list[tuple[Statement, str, dt.datetime | None]]) -> Choice | None:
    """One company's value from its ads' statements: the employer's own over a
    worldwide total; the most frequent value; on a tie the newest. Evidence is
    the newest ad that carries the chosen value."""
    local = [i for i in items if i[0].scope == "local"]
    pool = local or items
    if not pool:
        return None
    counts = Counter((s.min, s.max) for s, _, _ in pool)
    newest: dict[tuple[int, int | None], tuple[Statement, str, dt.datetime | None]] = {}
    for item in pool:
        key = (item[0].min, item[0].max)
        best = newest.get(key)
        if best is None or (as_utc(item[2]) or OLDEST) > (as_utc(best[2]) or OLDEST):
            newest[key] = item
    key = max(counts, key=lambda k: (counts[k], as_utc(newest[k][2]) or OLDEST))
    statement, ref, when = newest[key]
    return Choice(statement.min, statement.max, statement.scope, statement.quote, ref, as_utc(when))


def overlaps(lo: int, hi: int | None, bucket: str) -> bool:
    """A value (range) matches every bucket it overlaps."""
    b_lo, b_hi = BUCKETS[bucket]
    return (b_hi is None or lo <= b_hi) and (hi is None or hi >= b_lo)


def replaces(
    *,
    new_source: str,
    new_as_of: dt.datetime | None,
    cur_source: str | None,
    cur_as_of: dt.datetime | None,
) -> bool:
    """Whether a new claim replaces the stored one (see the module doc)."""
    if cur_source is None or cur_source == new_source:
        return True
    new, cur = as_utc(new_as_of), as_utc(cur_as_of)
    if new is None:
        return False
    if cur is None or new > cur:
        return True
    return new == cur and _PRECEDENCE.get(new_source, 0) > _PRECEDENCE.get(cur_source, 0)


_EURES_BAND = re.compile(r"^\s*(\d+)\s*[-–]\s*(\d+)\s*$")
_EURES_OPEN = re.compile(r"^\s*(\d+)\s*\+\s*$")


def eures_size(code: str | None) -> tuple[int, int | None] | None:
    """EURES `organisationSizeCode` → bounds, only when the code spells a band.

    No non-empty value was observed (600/600 sampled ads, 2026-11-19), so the
    code list is unverified: anything not shaped "10-49" or "250+" is ignored
    rather than guessed at.
    """
    if not code:
        return None
    if m := _EURES_BAND.match(code):
        lo, hi = int(m.group(1)), int(m.group(2))
        return (lo, hi) if 0 < lo < hi else None
    if m := _EURES_OPEN.match(code):
        lo = int(m.group(1))
        return (lo, None) if lo > 0 else None
    return None


# --- SQL helpers -------------------------------------------------------------------


def bucket_predicate(buckets: list[str]):
    """Rows whose stored value overlaps any of these buckets."""
    clauses = []
    for bucket in buckets:
        lo, hi = BUCKETS[bucket]
        upper = HubCompany.employees_min <= hi if hi is not None else HubCompany.employees_min.is_not(None)
        clauses.append(
            and_(upper, or_(HubCompany.employees_max.is_(None), HubCompany.employees_max >= lo))
        )
    return and_(HubCompany.employees_min.is_not(None), or_(*clauses))


def sized_names(buckets: list[str] | None = None) -> Select:
    """Employer names (`normalized_name`) with a known size — in a bucket, when
    given. An employer is sized when ANY of its sites is."""
    where = bucket_predicate(buckets) if buckets else HubCompany.employees_min.is_not(None)
    return select(HubCompany.normalized_name).where(HubCompany.kind == EMPLOYER, where)


async def coverage(session: AsyncSession) -> dict[str, Any]:
    """Hiring employers with a known size, per bucket and overall. The weekly
    snapshot stores it (`service._corpus_facets`), so Markt never counts this."""
    hiring = and_(HubCompany.kind == EMPLOYER, HubCompany.open_postings_count > 0)
    employers = int(
        await session.scalar(select(func.count(func.distinct(HubCompany.normalized_name))).where(hiring))
        or 0
    )
    known = int(
        await session.scalar(
            select(func.count(func.distinct(HubCompany.normalized_name))).where(
                hiring, HubCompany.normalized_name.in_(sized_names())
            )
        )
        or 0
    )
    buckets = []
    for bucket in BUCKETS:
        count = await session.scalar(
            select(func.count(func.distinct(HubCompany.normalized_name))).where(
                hiring, HubCompany.normalized_name.in_(sized_names([bucket]))
            )
        )
        buckets.append({"value": bucket, "count": int(count or 0)})
    share = known / employers if employers else 0.0
    return {
        "employers": employers,
        "known": known,
        "coverage": round(share, 4),
        "filter_available": share >= FILTER_MIN_COVERAGE,
        "buckets": buckets,
    }


# --- the ad-text pass -----------------------------------------------------------------

#: The stamp of a read that saw no text: any later fetch is newer.
_NOTHING_READ = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)


def _due():
    """Hiring employers never read, read under older rules, or with an ad text
    fetched since the last read."""
    newer_text = exists(
        select(HubJobPosting.id).where(
            HubJobPosting.hub_company_id == HubCompany.id,
            HubJobPosting.is_active.is_(True),
            HubJobPosting.description_fetched_at > HubCompany.employees_read_at,
        )
    )
    return and_(
        HubCompany.kind == EMPLOYER,
        HubCompany.open_postings_count > 0,
        or_(
            HubCompany.employees_rules.is_(None),
            HubCompany.employees_rules < HEADCOUNT_RULES,
            HubCompany.employees_read_at.is_(None),
            newer_text,
        ),
    )


def _read(rows: list, rules: suppression.Suppressions) -> dict[uuid.UUID, tuple[Choice | None, set[str], dt.datetime]]:
    """CPU part: per company, its choice, the refs read, the newest fetch seen."""
    found: dict[uuid.UUID, list[tuple[Statement, str, dt.datetime | None]]] = {}
    refs: dict[uuid.UUID, set[str]] = {}
    seen: dict[uuid.UUID, dt.datetime] = {}
    for r in rows:
        ref = f"{r.source}:{r.external_id}"[:200]
        refs.setdefault(r.hub_company_id, set()).add(ref)
        fetched = as_utc(r.description_fetched_at) or _NOTHING_READ
        seen[r.hub_company_id] = max(seen.get(r.hub_company_id, _NOTHING_READ), fetched)
        body = r.description
        if body and rules.may_name_someone(body):
            body = rules.redact(body)
        for statement in extract_statements(body):
            found.setdefault(r.hub_company_id, []).append(
                (statement, ref, as_utc(r.description_fetched_at) or as_utc(r.posted_at))
            )
    return {
        cid: (aggregate(found.get(cid, [])), refs[cid], seen[cid]) for cid in refs
    }


async def backfill(
    session: AsyncSession, *, limit: int, after: uuid.UUID | None = None
) -> dict[str, Any]:
    """Read up to `limit` due companies' newest ad texts and store their size.

    Keyset-paged by id (`after` = the previous batch's `last_id`), so a run
    walks the queue once instead of rescanning it per batch. Writes only the
    batch's rows: unchanged values get the stamp alone (no indexed column, so
    a HOT update).
    """
    stmt = select(
        HubCompany.id,
        HubCompany.employees_source,
        HubCompany.employees_source_ref,
        HubCompany.employees_rules,
        HubCompany.employees_as_of,
        HubCompany.employees_min,
        HubCompany.employees_max,
    ).where(_due())
    if after is not None:
        stmt = stmt.where(HubCompany.id > after)
    companies = (await session.execute(stmt.order_by(HubCompany.id).limit(limit))).all()
    if not companies:
        await session.commit()
        return {"read": 0, "sized": 0, "cleared": 0, "last_id": None, "done": True}

    ids = [c.id for c in companies]
    newest = (
        select(
            HubJobPosting.id,
            func.row_number()
            .over(
                partition_by=HubJobPosting.hub_company_id,
                order_by=(HubJobPosting.description_fetched_at.desc(), HubJobPosting.id),
            )
            .label("rn"),
        )
        .where(
            HubJobPosting.hub_company_id.in_(ids),
            HubJobPosting.is_active.is_(True),
            HubJobPosting.description_fetched_at.is_not(None),
        )
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                HubJobPosting.hub_company_id,
                HubJobPosting.source,
                HubJobPosting.external_id,
                HubJobPosting.posted_at,
                HubJobPosting.description_fetched_at,
                HubPostingPayload.description,
            )
            .join(newest, newest.c.id == HubJobPosting.id)
            .join(HubPostingPayload, HubPostingPayload.hub_job_posting_id == HubJobPosting.id)
            .where(newest.c.rn <= ADS_PER_COMPANY)
        )
    ).all()
    rules = await suppression.load(session)
    read = await asyncio.to_thread(_read, rows, rules)

    now = dt.datetime.now(dt.UTC)
    stamps: list[dict[str, Any]] = []
    values: list[dict[str, Any]] = []
    sized = cleared = 0
    for c in companies:
        choice, refs, seen = read.get(c.id, (None, set(), _NOTHING_READ))
        stamp = {"b_id": c.id, "b_read_at": seen}
        if choice is not None and replaces(
            new_source=AD_TEXT, new_as_of=choice.as_of,
            cur_source=c.employees_source, cur_as_of=c.employees_as_of,
        ):
            unchanged = (
                c.employees_source == AD_TEXT
                and (c.employees_min, c.employees_max, c.employees_source_ref) == (choice.min, choice.max, choice.ref)
                and c.employees_rules == HEADCOUNT_RULES
            )
            if unchanged:
                stamps.append(stamp)
                continue
            sized += 1
            values.append(
                {
                    **stamp,
                    "b_min": choice.min, "b_max": choice.max, "b_source": AD_TEXT,
                    "b_ref": choice.ref, "b_evidence": choice.quote[:500],
                    "b_as_of": choice.as_of,
                }
            )
            continue
        # Nothing found. An ad-text value goes when the new rules no longer
        # find it, or its own ad was re-read and no longer says it.
        if c.employees_source == AD_TEXT and choice is None and (
            (c.employees_rules or 0) < HEADCOUNT_RULES or c.employees_source_ref in refs
        ):
            cleared += 1
            values.append(
                {**stamp, "b_min": None, "b_max": None, "b_source": None, "b_ref": None,
                 "b_evidence": None, "b_as_of": None}
            )
            continue
        stamps.append(stamp)

    table = HubCompany.__table__
    connection = await session.connection()
    if stamps:
        await connection.execute(
            update(table)
            .where(table.c.id == bindparam("b_id"))
            .values(employees_read_at=bindparam("b_read_at"), employees_rules=HEADCOUNT_RULES),
            stamps,
        )
    if values:
        await connection.execute(
            update(table)
            .where(table.c.id == bindparam("b_id"))
            .values(
                employees_read_at=bindparam("b_read_at"),
                employees_rules=HEADCOUNT_RULES,
                employees_min=bindparam("b_min"),
                employees_max=bindparam("b_max"),
                employees_source=bindparam("b_source"),
                employees_source_ref=bindparam("b_ref"),
                employees_evidence=bindparam("b_evidence"),
                employees_as_of=bindparam("b_as_of"),
                employees_updated_at=now,
            ),
            values,
        )
    await session.commit()
    return {
        "read": len(companies),
        "sized": sized,
        "cleared": cleared,
        "last_id": str(ids[-1]),
        "done": len(companies) < limit,
    }


# --- the Wikidata pass ------------------------------------------------------------------

#: How long a Wikidata answer stands before the domain is asked again.
WIKIDATA_RECHECK = dt.timedelta(days=28)


async def wikidata_backfill(
    session: AsyncSession, *, limit: int, client, after: str | None = None
) -> dict[str, Any]:
    """Ask Wikidata about up to `limit` hiring employers' domains that are due.

    `client` is an `adapters.wikidata.WikidataClient` (a fake in tests). Its
    matches are exact registrable-domain equality on P856; this pass applies
    `replaces` per row and stamps every row of the asked domains, so a domain
    is asked once per `WIKIDATA_RECHECK`. Each request leaves a
    `hub_observations` row (the client records it).
    """
    now = dt.datetime.now(dt.UTC)
    due = select(HubCompany.website_domain).where(
        HubCompany.kind == EMPLOYER,
        HubCompany.open_postings_count > 0,
        HubCompany.website_domain.is_not(None),
        or_(
            HubCompany.employees_wikidata_at.is_(None),
            HubCompany.employees_wikidata_at < now - WIKIDATA_RECHECK,
        ),
    )
    if after:
        due = due.where(HubCompany.website_domain > after)
    domains = list(
        (await session.execute(due.distinct().order_by(HubCompany.website_domain).limit(limit))).scalars()
    )
    if not domains:
        await session.commit()
        return {"asked": 0, "matched": 0, "sized": 0, "failed": 0, "last_domain": None, "done": True}

    answers, failed = await client.lookup(session, domains)
    asked = [d for d in domains if d not in failed]

    sized = 0
    if answers:
        rows = (
            await session.execute(
                select(
                    HubCompany.id, HubCompany.website_domain, HubCompany.employees_source,
                    HubCompany.employees_as_of, HubCompany.employees_source_ref,
                    HubCompany.employees_min, HubCompany.employees_max,
                ).where(HubCompany.website_domain.in_(list(answers)), HubCompany.kind == EMPLOYER)
            )
        ).all()
        values = []
        for r in rows:
            hit = answers[r.website_domain]
            if not replaces(
                new_source=WIKIDATA, new_as_of=hit.as_of,
                cur_source=r.employees_source, cur_as_of=r.employees_as_of,
            ):
                continue
            if (r.employees_source, r.employees_source_ref, r.employees_min, r.employees_max) == (
                WIKIDATA, hit.qid, hit.employees, hit.employees
            ):
                continue
            values.append(
                {
                    "b_id": r.id, "b_min": hit.employees, "b_max": hit.employees,
                    "b_ref": hit.qid, "b_evidence": hit.evidence[:500], "b_as_of": hit.as_of,
                }
            )
        if values:
            table = HubCompany.__table__
            connection = await session.connection()
            await connection.execute(
                update(table)
                .where(table.c.id == bindparam("b_id"))
                .values(
                    employees_min=bindparam("b_min"),
                    employees_max=bindparam("b_max"),
                    employees_source=WIKIDATA,
                    employees_source_ref=bindparam("b_ref"),
                    employees_evidence=bindparam("b_evidence"),
                    employees_as_of=bindparam("b_as_of"),
                    employees_updated_at=now,
                ),
                values,
            )
            sized = len(values)
    if asked:
        await session.execute(
            update(HubCompany)
            .where(HubCompany.website_domain.in_(asked))
            .values(employees_wikidata_at=now)
            .execution_options(synchronize_session=False)
        )
    await session.commit()
    return {
        "asked": len(asked),
        "matched": len(answers),
        "sized": sized,
        "failed": len(failed),
        "last_domain": domains[-1],
        "done": len(domains) < limit,
    }
