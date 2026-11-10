"""The opt-out list — erasure in a corpus that re-ingests every night.

A DELETE is not erasure here: the next crawl asks the same source, the source
still publishes the record, and the row comes back. So an objection (GDPR
Art. 21) or an erasure request (Art. 17) is recorded as a `HubSuppression`, and
every write into the corpus consults it (ARCHITECTURE.md §3):

  * a suppressed **company** is refused at ingest — counted in the summary,
    never stored, not echoed back by name;
  * a suppressed **person's** name is cut out of every ad text before it is
    stored (ingest, the description pass, the partner-page pass), and once
    from the texts already there when the suppression is added;
  * the contacts read redacts again, as a backstop for any text a writer
    missed.

Deterministic on purpose, like `contacts.py`: either the name is in the text
or it is not. The redaction errs towards removing too much — "Frau Wolter"
is cut wherever it appears, even at an employer the person never worked for,
because a missed erasure is the failure that matters.

Only the owner connection writes the list (`scripts/hub_suppress.py`). The
app role can read it and nothing else — the migration's policy enforces that.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import re
from typing import Any

from sqlalchemy import Text, cast, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.hub.contacts import _fold
from app.domain.hub.models import (
    SUPPRESS_COMPANY,
    SUPPRESS_PERSON,
    SUPPRESSION_REASONS,
    HubCompany,
    HubCompanyLink,
    HubJobPosting,
    HubPostingPayload,
    HubSuppression,
)
from app.domain.hub.resolution import normalize_company_name

#: What a removed name is replaced with, visible in the ad so a reader sees
#: that something was taken out rather than wondering at a broken sentence.
REDACTED = "[entfernt]"

_SALUTATIONS = {"frau", "herr", "herrn"}
_TITLE = re.compile(r"^(?:dr|prof|mag|di|ing|mba)\.?$|^dipl\.", re.IGNORECASE)

#: A folded name matches its written forms: "gruembel" ↔ "Grümbel".
_FOLDED_PAIRS = {"ae": "(?:ae|ä)", "oe": "(?:oe|ö)", "ue": "(?:ue|ü)", "ss": "(?:ss|ß)"}
_ACCENTED = {
    "a": "[aáàâ]",
    "e": "[eéèê]",
    "i": "[iíìî]",
    "o": "[oóòô]",
    "u": "[uúùû]",
    "c": "[cç]",
    "n": "[nñ]",
}
_EMAIL_TAIL = r"@[\w-]+(?:\.[\w-]+)+"


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


def company_key(name: str) -> str:
    """The blocking key: the normalized name — every site, every legal form.

    Agency branches are covered at match time (`blocks_company`,
    `_remove_company`), never by widening this key: widening it for employers
    would reach separate legal entities that share a prefix.
    """
    key = normalize_company_name(name)
    if not key:
        raise ValueError(f"{name!r} normalizes to nothing — not a company name")
    return key


def person_key(name: str) -> str:
    """Folded full name without salutation or titles: "katrin wolter".

    At least first and last name. A surname alone would cut every "Müller"
    out of every ad in the corpus.
    """
    if "," in name:
        # "Wolter, Katrin" — as on a letter. Kept in written order, the key
        # would take "katrin" for the surname and suppress nobody.
        last, _, first = name.partition(",")
        name = f"{first} {last}"
    tokens = [
        t
        for t in name.split()
        if t.lower() not in _SALUTATIONS and not _TITLE.match(t)
    ]
    folded = [re.sub(r"[^a-z-]", "", _fold(t)) for t in tokens]
    folded = [t for t in folded if t.strip("-")]
    if len(folded) < 2:
        raise ValueError(f"{name!r}: a person needs first and last name")
    return " ".join(folded)


# ---------------------------------------------------------------------------
# The rules, loaded once per pass
# ---------------------------------------------------------------------------


def _token(folded: str) -> str:
    out, i = [], 0
    while i < len(folded):
        pair = folded[i : i + 2]
        if pair in _FOLDED_PAIRS:
            out.append(_FOLDED_PAIRS[pair])
            i += 2
            continue
        if folded[i] == "-":
            out.append(r"[-\s]+")  # "Marie-Luise" is also written "Marie Luise"
        else:
            out.append(_ACCENTED.get(folded[i], re.escape(folded[i])))
        i += 1
    return "".join(out)


#: Any markup or line break between two parts of a name: "**Katrin**
#: Wolter", "Katrin\nWolter".
_GAP = r"[\s*_]+"
#: "Dr.", "Prof. Dr. med.", "Dipl.-Ing." between a salutation and the surname.
_TITLES = r"(?:(?:Dr|Prof|med|rer|nat|dent|Dipl|Ing|Mag)\.[-\w.]*\s*)*"


def _person_patterns(key: str) -> list[str]:
    tokens = key.split()
    firsts, surname = tokens[:-1], tokens[-1]
    # A double surname belongs to the name: "Wolter-Schmidt" goes whole.
    last = _token(surname) + r"(?:-\w+)*"
    first = _GAP.join(_token(t) for t in firsts)
    return [
        # "Katrin Wolter", any case, umlauts either way.
        rf"(?<![\w-]){first}{_GAP}{last}(?!\w)",
        # "Wolter, Katrin" / "Wolter Katrin" — lists and signature blocks.
        rf"(?<![\w-]){last},?{_GAP}{first}(?!\w)",
        # "K. Wolter".
        rf"(?<![\w-]){_token(firsts[0][0])}\.\s*{last}(?!\w)",
        # "Frau Wolter", "Hr. Wolter", "Frau Dr. med. Wolter" — the formal form.
        rf"(?<!\w)(?:Frau|Herrn?|Fr\.|Hr\.)\s*{_TITLES}{last}(?!\w)",
        # "k.wolter@…", "a.grümbel@…" — a personal address names the person.
        rf"[\w.+-]*{_token(surname)}[\w.+-]*{_EMAIL_TAIL}",
    ]


@dataclasses.dataclass(frozen=True)
class Suppressions:
    """The opt-out list as one pass needs it. Empty = every method a no-op."""

    companies: frozenset[str] = frozenset()
    persons: tuple[str, ...] = ()

    @functools.cached_property
    def _pattern(self) -> re.Pattern[str] | None:
        if not self.persons:
            return None
        parts = [p for key in self.persons for p in _person_patterns(key)]
        return re.compile("|".join(f"(?:{p})" for p in parts), re.IGNORECASE)

    @functools.cached_property
    def _agency_roots(self) -> frozenset[str]:
        from app.domain.hub.agency_rank import group_key

        return frozenset(group_key(k) for k in self.companies)

    def blocks_company(self, name: str | None, *, kind: str = "employer") -> bool:
        """The exact firm, at every site. For a private recruiter also every
        branch of it: an objection from "Brunel GmbH NL Essen" is Brunel's."""
        if not self.companies:
            return False
        if normalize_company_name(name) in self.companies:
            return True
        if kind == "private_recruiter":
            from app.domain.hub.agency_rank import group_key

            return group_key(name) in self._agency_roots
        return False

    def redact(self, text: str | None) -> str | None:
        if not text or self._pattern is None:
            return text
        return self._pattern.sub(REDACTED, text)

    def redact_json(self, value: Any) -> Any:
        """The archived source record, every string in it."""
        if self._pattern is None:
            return value
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            return {k: self.redact_json(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact_json(v) for v in value]
        return value


async def load(session: AsyncSession) -> Suppressions:
    rows = (await session.execute(select(HubSuppression.scope, HubSuppression.key))).all()
    return Suppressions(
        companies=frozenset(k for s, k in rows if s == SUPPRESS_COMPANY),
        persons=tuple(sorted(k for s, k in rows if s == SUPPRESS_PERSON)),
    )


# ---------------------------------------------------------------------------
# Adding one — owner connection only (scripts/hub_suppress.py)
# ---------------------------------------------------------------------------

_BATCH = 500


async def suppress(
    session: AsyncSession, *, scope: str, name: str, reason: str
) -> dict[str, Any]:
    """Record the suppression, then remove what the corpus already holds.

    Idempotent: suppressing the same key twice keeps one entry and re-runs the
    clean-up, which is also how a missed text is caught later.

    A company: every corpus row of that name — every site, employer and agency
    rows alike — with its postings, ad texts and the tenant links and project
    memberships that pointed at them. A tenant's own `companies` and
    `managers` rows are its record, not the corpus, and are not touched here.

    A person: their name is cut from every stored ad text.
    """
    if reason not in SUPPRESSION_REASONS:
        raise ValueError(f"reason must be one of {SUPPRESSION_REASONS}")
    if scope == SUPPRESS_COMPANY:
        key = company_key(name)
    elif scope == SUPPRESS_PERSON:
        key = person_key(name)
    else:
        raise ValueError(f"scope must be {SUPPRESS_COMPANY!r} or {SUPPRESS_PERSON!r}")

    existing = await session.scalar(
        select(HubSuppression).where(HubSuppression.scope == scope, HubSuppression.key == key)
    )
    if existing is None:
        session.add(HubSuppression(scope=scope, key=key, reason=reason))
        await session.flush()

    outcome: dict[str, Any] = {"scope": scope, "key": key, "already_listed": existing is not None}
    if scope == SUPPRESS_COMPANY:
        outcome.update(await _remove_company(session, key))
    else:
        outcome.update(await _redact_person(session, key, written=name))
    await session.commit()
    return outcome


async def _remove_company(session: AsyncSession, key: str) -> dict[str, int]:
    from app.domain.projects.models import ProjectCompany

    from app.domain.hub.agency_rank import group_key
    from app.domain.hub.models import PRIVATE_RECRUITER

    # The firm at every site, any kind — and, for private recruiters only,
    # every branch that folds onto the same agency ("brunel nl essen",
    # "brunel nl braunschweig"). Employers are never folded.
    root = group_key(key)
    rows = await session.execute(
        select(HubCompany.id, HubCompany.name, HubCompany.normalized_name, HubCompany.kind).where(
            or_(HubCompany.normalized_name == key, HubCompany.normalized_name.like(f"{root}%"))
        )
    )
    ids = [
        row.id
        for row in rows
        if row.normalized_name == key
        or (row.kind == PRIVATE_RECRUITER and group_key(row.name) == root)
    ]
    company_ids = select(HubCompany.id).where(HubCompany.id.in_(ids))
    posting_ids = select(HubJobPosting.id).where(HubJobPosting.hub_company_id.in_(company_ids))
    # Children first: SQLite enforces no cascades, and the order is the same
    # one Postgres would need without them.
    await session.execute(
        delete(HubPostingPayload).where(HubPostingPayload.hub_job_posting_id.in_(posting_ids))
    )
    from app.domain.hub import ad_contacts

    await ad_contacts.forget(session, posting_ids)
    postings = await session.execute(
        delete(HubJobPosting).where(HubJobPosting.hub_company_id.in_(company_ids))
    )
    links = await session.execute(
        delete(HubCompanyLink).where(HubCompanyLink.hub_company_id.in_(company_ids))
    )
    memberships = await session.execute(
        delete(ProjectCompany).where(ProjectCompany.hub_company_id.in_(company_ids))
    )
    companies = await session.execute(delete(HubCompany).where(HubCompany.id.in_(ids)))
    # The agency finder's derived profile goes with it, not at the next
    # nightly rebuild.
    from app.domain.hub.models import HubAgencyProfile

    await session.execute(
        delete(HubAgencyProfile).where(HubAgencyProfile.group_key.in_({key, root}))
    )
    return {
        "companies_deleted": companies.rowcount or 0,
        "postings_deleted": postings.rowcount or 0,
        "tenant_links_deleted": links.rowcount or 0,
        "project_entries_deleted": memberships.rowcount or 0,
    }


async def _redact_person(session: AsyncSession, key: str, *, written: str) -> dict[str, int]:
    rules = Suppressions(persons=(key,))
    # Narrow by surname first — the payload table is the largest in the
    # corpus. Both spellings: the text may say "Grümbel" or "Gruembel".
    surnames = {key.split()[-1], written.replace(",", " ").split()[0 if "," in written else -1].lower()}
    # `raw` is serialised with non-ASCII escaped: "Grümbel" is stored as
    # "Gr\\u00fcmbel", which neither spelling above matches.
    surnames |= {json.dumps(s)[1:-1] for s in surnames}
    columns = (
        HubPostingPayload.description,
        HubPostingPayload.source_page_text,
        cast(HubPostingPayload.raw, Text),
    )
    candidates = select(HubPostingPayload.hub_job_posting_id).where(
        or_(*[func.lower(c).like(f"%{s}%") for c in columns for s in surnames])
    )
    ids = list((await session.execute(candidates)).scalars().all())

    redacted = 0
    for start in range(0, len(ids), _BATCH):
        rows = (
            await session.execute(
                select(HubPostingPayload).where(
                    HubPostingPayload.hub_job_posting_id.in_(ids[start : start + _BATCH])
                )
            )
        ).scalars().all()
        for row in rows:
            before = (row.description, row.source_page_text, row.raw)
            row.description = rules.redact(row.description)
            row.source_page_text = rules.redact(row.source_page_text)
            row.raw = rules.redact_json(row.raw)
            if (row.description, row.source_page_text, row.raw) != before:
                redacted += 1
        await session.flush()
    if ids:
        # Stored contacts were read from the unredacted text: drop them, and
        # the next pass re-reads the redacted one.
        from app.domain.hub import ad_contacts

        for start in range(0, len(ids), _BATCH):
            await ad_contacts.forget(session, ids[start : start + _BATCH])

    # A sole trader trades under their own name — the company row is theirs
    # too, and needs its own `company` suppression. Counted, so the operator
    # is told.
    companies_named = await session.scalar(
        select(func.count(HubCompany.id)).where(
            HubCompany.normalized_name.like(f"%{normalize_company_name(key)}%")
        )
    )
    return {"texts_redacted": redacted, "companies_named": companies_named or 0}
