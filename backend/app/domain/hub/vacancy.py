"""One vacancy, counted once — the deterministic duplicate key for postings.

A posting is unique per SOURCE (`source`, `external_id`). A vacancy is not:
measured 2026-11-05 on 1,219 live Bundesagentur ads, 4.8% repeated an ad
already there — the same employer, the same title once the gender tag is
stripped, the same place — because job boards relay one vacancy under several
references. A second source (an employer's own Personio or SmartRecruiters
board) repeats most of them again.

The key, same discipline as company identity (`resolution.py`, ARCHITECTURE.md
RULE 5): deterministic, never fuzzy.

    vacancy_key = sha256( employer · normalized title · place )

  * employer — the company's `normalized_name`, which is what search rolls
    employers up by, so two sources resolving the firm to different site rows
    still meet;
  * title — lowercased, gender tags ("(m/w/d)", "*in", "/in", ":in") and
    punctuation removed. "Senior Developer" and "Developer" stay two;
  * place — the postcode, else the city.

Two openings with the same title at the same site collapse into one. For "who
is hiring" that undercount is the better error than counting a relay as two.
Ads without a key yet (the backfill runs over nights) count as themselves.
"""

from __future__ import annotations

import hashlib
import re

from sqlalchemy import String, cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.hub.models import HubCompany, HubJobPosting
from app.domain.hub.resolution import fold_umlauts

_PAREN_TAG = re.compile(
    r"\(\s*(?:[mwdfxi]\s*[/|,]\s*)+[mwdfxi]\s*\)"           # (m/w/d), (w/m/d), (f/m/d)
    r"|\(\s*(?:all\s+genders?|gn|divers|w\s*m\s*d|m\s*w\s*d)\s*\)",
    re.IGNORECASE,
)
_BARE_TAG = re.compile(r"(?<!\w)(?:[mwdfx]\s*/\s*){1,2}[mwdfx](?!\w)", re.IGNORECASE)
#: The German gender suffix in its spellings: Mechatroniker*in, Verkäufer/in,
#: Softwareentwickler:in, Kaufmann/-frau stays (it is two words, both kept).
_SUFFIX = re.compile(r"(?<=\w)(?:\*|:|_|/)(?:-)?in(?:nen)?\b", re.IGNORECASE)
_NON_WORD = re.compile(r"[^0-9a-z]+")


def normalize_title(title: str | None) -> str:
    text = (title or "").lower()
    text = _PAREN_TAG.sub(" ", text)
    text = _SUFFIX.sub("", text)
    text = _BARE_TAG.sub(" ", text)
    # Folded like company names: "Verkäufer" and "Verkaeufer" are one title.
    return _NON_WORD.sub(" ", fold_umlauts(text)).strip()


def _place(postal_code: str | None, city: str | None) -> str:
    code = (postal_code or "").strip()
    if code:
        return f"plz:{code}"
    return "city:" + _NON_WORD.sub(" ", fold_umlauts((city or "").lower())).strip()


def vacancy_key(employer: str | None, title: str | None, *, postal_code: str | None, city: str | None) -> str | None:
    employer = (employer or "").strip()
    normalized = normalize_title(title)
    if not employer or not normalized:
        return None
    material = "|".join((employer, normalized, _place(postal_code, city)))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:40]


def vacancy_count():
    """Open vacancies in an aggregate: distinct keys, an unkeyed ad as itself."""
    return func.count(func.distinct(func.coalesce(HubJobPosting.vacancy_key, cast(HubJobPosting.id, String))))


async def backfill(session: AsyncSession, *, limit: int) -> dict[str, int]:
    """Key up to `limit` open ads that have none; how many remain."""
    rows = (await session.execute(
        select(HubJobPosting.id, HubJobPosting.title, HubJobPosting.postal_code, HubJobPosting.city,
               HubCompany.normalized_name)
        .join(HubCompany, HubCompany.id == HubJobPosting.hub_company_id)
        .where(HubJobPosting.is_active, HubJobPosting.vacancy_key.is_(None))
        .limit(limit)
    )).all()
    if rows:
        # One bulk UPDATE by primary key, not a round trip per row. An ad that
        # cannot be keyed gets its own id, so it leaves the backlog instead of
        # being selected every night.
        await session.execute(update(HubJobPosting), [
            {
                "id": row.id,
                "vacancy_key": vacancy_key(row.normalized_name, row.title, postal_code=row.postal_code, city=row.city)
                or f"id:{row.id.hex}",
            }
            for row in rows
        ])
    await session.commit()
    keyed = len(rows)
    remaining = await session.scalar(
        select(func.count(HubJobPosting.id)).where(HubJobPosting.is_active, HubJobPosting.vacancy_key.is_(None))
    )
    return {"keyed": keyed, "remaining": int(remaining or 0)}
