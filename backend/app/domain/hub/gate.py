"""Pre/postcondition gate for hub ingestion.

Same discipline as `documents/gate.py`, applied to layer 1: every check is a
pure predicate over *real state* — the fetch outcome, the parsed record, or a
re-query of the database — never over an agent's or a model's claim about it.

Runbook order:

    precondition (vs. the fetch) -> parse -> postcondition (vs. each record)
    -> persist -> postcondition (re-query the DB and prove the rows landed)

Rejections are counted and named in the ingest summary rather than logged and
forgotten, so "we ingested 2,300 postings" always comes with "and dropped 41,
for these reasons".
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from app.domain.hub.adapters.base import FetchResult, SourcedPosting
from app.domain.hub.resolution import identity_key

# A posting dated further ahead than this is a data error, not a vacancy.
_MAX_FUTURE_SKEW = dt.timedelta(days=2)


class PreconditionFailed(Exception):
    """A blocking precondition did not hold — ingestion must not proceed."""


@dataclass
class GateOutcome:
    check: str
    ok: bool
    detail: str

    def as_note(self) -> str:
        return f"{'✓' if self.ok else '✗'} {self.check} — {self.detail}"


def check_fetch(result: FetchResult) -> list[GateOutcome]:
    """Preconditions on the retrieval itself. Raises if ingestion cannot proceed.

    ``robots_allowed`` is blocking by design: a source that disallows collection
    must stop the run, not merely annotate it.
    """
    outcomes = [
        GateOutcome(
            "robots_allowed",
            result.robots_allowed,
            "source permits collection"
            if result.robots_allowed
            else f"robots.txt/ToS disallows {result.request_url}",
        ),
        GateOutcome(
            "http_ok",
            result.http_status == 200,
            f"HTTP {result.http_status}",
        ),
    ]
    for outcome in outcomes:
        if not outcome.ok:
            raise PreconditionFailed(outcome.detail)
    return outcomes


def check_posting(posting: SourcedPosting, *, now: dt.datetime | None = None) -> tuple[bool, str]:
    """Postconditions a parsed record must pass before it may be persisted.

    Returns ``(ok, reason)``; the reason is surfaced verbatim in the summary.
    """
    now = now or dt.datetime.now(dt.UTC)

    if not posting.title.strip():
        return False, "empty title"
    if not posting.external_id.strip():
        return False, "no external id — not deduplicable"
    if not posting.company.name.strip():
        return False, "no employer name — not attributable"

    # The company must be resolvable to a deterministic identity, or it would be
    # persisted as an un-mergeable duplicate of something already in the corpus.
    if identity_key(
        name=posting.company.name,
        website_domain=posting.company.website_domain,
        postal_code=posting.company.postal_code,
        city=posting.company.city,
    ) is None:
        return False, f"employer {posting.company.name!r} has no resolvable identity (no place)"

    if posting.source_url and not posting.source_url.lower().startswith(
        ("http://", "https://")
    ):
        return False, f"source_url {posting.source_url!r} is not an absolute URL"

    if posting.posted_at and posting.posted_at > now + _MAX_FUTURE_SKEW:
        return False, f"posted_at {posting.posted_at.date()} is in the future"

    return True, "record complete and attributable"


def check_persisted(*, expected: int, observed: int) -> GateOutcome:
    """Final postcondition: re-query the DB and prove the rows actually landed.

    The laufwise move — trust the database's answer, not the ORM's optimism.
    """
    ok = observed >= expected
    return GateOutcome(
        "rows_landed",
        ok,
        f"{observed}/{expected} postings present after commit"
        if ok
        else f"only {observed} of {expected} postings found after commit",
    )
