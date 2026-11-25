"""ELI-73: fill the "+ Lead" form from a job ad — a PROPOSAL, nothing saved.

Two ways in, and no fetch in either (ARCHITECTURE.md RULE 1):

  * a link to an ad Markt holds (`hub.posting_links.posting_ref` → the
    indexed `(source, external_id)`): the ad title, the employer, and the
    people the ad names — the deterministic rules (`hub.contacts`) run on the
    stored text, plus the contacts the nightly model pass found AND the
    deterministic checks found word for word in the ad (`hub_ad_contacts`,
    `found_by="model"`). Exactly as the corpus holds them, the same reading
    Markt's "Ansprechpartner" shows;
  * the ad text, pasted: the same deterministic rules — no model is called
    here. The title only when a line plainly is one (it carries a gender tag
    such as "(m/w/d)" and is not a sentence).

Filtered like Markt: a person the shared corpus suppresses (`hub_suppressions`)
is redacted from the text and never proposed; a person THIS workspace erased
(`erasure.person_guard`, by surname at the employer, number or address) is
dropped — and when the workspace has erasures but cannot check them (no key),
nobody is proposed (fail closed). An agency's ad is marked, not hidden, as in
Markt. The recruiter reviews every field; saving goes through
`create_manual_lead` with all of its checks.
"""

from __future__ import annotations

import asyncio
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

#: Longest pasted ad read. A real ad is a few thousand characters. The rules
#: are NOT linear (measured: 5k chars 0.09 s, 20k chars up to 2.8 s), so the
#: cap is tight and the reading runs off the event loop.
MAX_TEXT = 8_000

#: A line that is a job title: short, carries a gender tag, is not a sentence.
_TITLE_MAX = 120


def title_from_text(text: str) -> str | None:
    """The ad's title when one line plainly is it — "Senior Java Entwickler
    (m/w/d)" — else None. Never cut out of a sentence."""
    from app.domain.hub.vacancy import _BARE_TAG, _PAREN_TAG

    for raw in text.splitlines():
        line = " ".join(raw.split()).strip(" -–—•*|")
        if not line or len(line) > _TITLE_MAX or not (_PAREN_TAG.search(line) or _BARE_TAG.search(line)):
            continue
        # A sentence, or a board's list of other ads, is not this ad's title.
        if line.endswith((".", "?", ":")) or re.search(
            r"\b(wir|suchen|sie|ihr|ihre|ähnlich|ähnliche|weitere|stellenangebote)\b", line, re.I
        ):
            continue
        return line
    return None


def _person(m, found_by: str) -> dict:
    return {
        "full_name": m.full_name,
        "first_name": m.first_name,
        "last_name": m.last_name,
        "role_title": m.role_title,
        "email": m.email,
        # The form has one number: the line, else the mobile (as Markt adopts).
        "phone": m.phone or m.mobile,
        # Kept for the erasure check: a person erased by their mobile is
        # still that person when the ad also gives a landline.
        "mobile": m.mobile,
        "found_by": found_by,
        "quote": m.quote,
    }


def _merge(found: list[dict]) -> list[dict]:
    """One proposal per person (folded surname + first name); the first
    reading wins, later ones only fill what it left empty."""
    from app.domain.hub.contacts import person_key

    people: dict[str, dict] = {}
    for p in found:
        key = person_key(p["first_name"], p["last_name"])
        held = people.get(key)
        if held is None:
            people[key] = dict(p)
            continue
        for field in ("first_name", "role_title", "email", "phone", "mobile"):
            if not held[field] and p[field]:
                held[field] = p[field]
        if held["first_name"] and len(p["full_name"]) > len(held["full_name"]):
            held["full_name"] = p["full_name"]
    return list(people.values())


async def _filtered(
    session: AsyncSession, tenant_id: uuid.UUID, people: list[dict], company_name: str | None
) -> tuple[list[dict], bool]:
    """Drop who this workspace erased — by surname at the employer, by
    address, and by EVERY number the ad gives (line and mobile). When the
    workspace has erasures it cannot check (no key), nobody is proposed and
    the second value says so: fail closed, but not silently."""
    from app.domain.erasure import service as erasure

    if not people:
        return [], False
    try:
        guard = await erasure.person_guard(session, tenant_id)
    except erasure.NotConfigured:
        return [], True

    def erased(p: dict) -> bool:
        numbers = [n for n in (p["phone"], p["mobile"]) if n] or [None]
        return any(
            guard.erased_on(company_name=company_name, surname=p["last_name"], phone=n, email=p["email"]) is not None
            for n in numbers
        )

    return [p for p in people if not erased(p)], False


def _public(p: dict) -> dict:
    return {k: p[k] for k in ("full_name", "role_title", "email", "phone", "found_by", "quote")}


async def prefill(
    session: AsyncSession, *, tenant_id: uuid.UUID, url: str | None = None, text: str | None = None
) -> dict:
    """The proposal for the form. `found`: `corpus` (the ad is in Markt),
    `not_in_corpus` (a link Markt does not hold — paste the text), `text`
    (read from the pasted text). Writes nothing."""
    from app.domain.hub import posting_links, suppression
    from app.domain.hub.models import HubAdContact, HubCompany, HubJobPosting, HubPostingPayload
    from app.domain.hub.schemas import source_detail_url

    rules = await suppression.load(session)
    empty = {"job_title": None, "company_name": None, "posting_id": None, "source_url": None,
             "is_agency": False, "contacts": [], "contacts_withheld": False}

    if url and url.strip():
        ref = posting_links.posting_ref(url)
        row = None
        if ref is not None:
            row = (
                await session.execute(
                    select(HubJobPosting, HubCompany, HubPostingPayload.description, HubPostingPayload.source_page_text)
                    .join(HubCompany, HubCompany.id == HubJobPosting.hub_company_id)
                    .outerjoin(HubPostingPayload, HubPostingPayload.hub_job_posting_id == HubJobPosting.id)
                    .where(HubJobPosting.source == ref[0], HubJobPosting.external_id == ref[1])
                )
            ).first()
        if row is None:
            return {"found": "not_in_corpus", **empty}
        posting, company, description, page_text = row
        texts = [rules.redact(t) for t in (description, page_text) if t]
        found = [_person(m, "rules") for m in await asyncio.to_thread(_read, texts)]
        stored = (
            await session.scalars(
                select(HubAdContact).where(
                    HubAdContact.hub_job_posting_id == posting.id, HubAdContact.found_by == "model"
                )
            )
        ).all()
        found += [_person(c, "model") for c in stored if not rules.names(c.first_name, c.last_name)]
        people, withheld = await _filtered(session, tenant_id, _merge(found), company.name)
        return {
            "found": "corpus",
            "job_title": posting.title,
            "company_name": company.name,
            "posting_id": posting.id,
            "source_url": source_detail_url(posting.source, posting.external_id) or posting.source_url,
            "is_agency": bool(company.staffing_name),
            "contacts": [_public(p) for p in people],
            "contacts_withheld": withheld,
        }

    body = rules.redact((text or "")[:MAX_TEXT]) or ""
    found = [_person(m, "rules") for m in await asyncio.to_thread(_read, [body])]
    people, withheld = await _filtered(session, tenant_id, _merge(found), None)
    return {
        "found": "text", **empty, "job_title": title_from_text(body),
        "contacts": [_public(p) for p in people], "contacts_withheld": withheld,
    }


def _read(texts: list[str]) -> list:
    """The deterministic contact rules over each text — CPU work, run in a
    thread so one long paste does not stall every other request."""
    from app.domain.hub.contacts import extract_contacts

    return [m for t in texts for m in extract_contacts(t)]
