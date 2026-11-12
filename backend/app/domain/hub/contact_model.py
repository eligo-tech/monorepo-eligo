"""ELI-25 layer 2 — a model reads the ads the rules could not name a person in.

Layer 1 is `hub/contacts.py` (deterministic rules). It misses names it has no
evidence for — an unknown first name, an unusual sentence. Layer 3 is the
safety net (`contacts.unnamed_reach`): the phone or e-mail is shown even when
nobody is named. This layer sits between them: for every ad the rules named
nobody in but which gives a phone number or e-mail (`contacts_model_due`,
set by the contacts pass), a cheap model is asked who the contact is.

**The model proposes; deterministic checks decide** (backend/CLAUDE.md
§2.5). `ground` keeps a person only if

  * the name stands in the ad word for word ("Hussien Bader"), or a
    salutation plus surname does ("Frau Okonkwo") — a bare surname is not
    enough;
  * it is close to a phone number or e-mail the ad gives;
  * it is shaped like a name (no unit, department or company words);
  * every phone and e-mail the model attaches is in the ad too — a model that
    invents contact data is not trusted on the name either.

What is sent: only the lines around the ad's contact data (`excerpt`), never
the whole ad. Public ad text, the same corpus RULE 2 allows; nothing tenant-
owned. The rows are stored with `found_by = "model"` and shown as such.

Machine-only (ARCHITECTURE.md RULE 1): the nightly job calls the operator
route. A model failure leaves the ad queued for the next night and costs
nothing else — the rule results are already stored.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import json
import re
from typing import Any, Protocol

from sqlalchemy import bindparam, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.hub import contacts as C
from app.domain.hub import suppression
from app.domain.hub.models import HubAdContact, HubJobPosting, HubPostingPayload

logger = get_logger(__name__)

#: The most of an ad sent to the model, and how much text around each phone
#: number / e-mail it is cut from.
EXCERPT_MAX = 1500
_AROUND = 300
#: How close a name must stand to the ad's contact data (characters).
_NEAR = 250
#: "[at]", "(at)", " at " — an address written so robots miss it.
_OBFUSCATED_AT = re.compile(r"\s*(?:\[at\]|\(at\)|\{at\})\s*", re.IGNORECASE)
#: Model calls in flight at once, and the time one may take.
_CONCURRENCY = 8
_TIMEOUT = 45.0


@dataclasses.dataclass(frozen=True)
class ModelPerson:
    """One person as the model returned them — unchecked."""

    first_name: str | None
    last_name: str
    salutation: str | None
    role_title: str | None
    phone: str | None
    email: str | None


class ContactReader(Protocol):
    """Vendor-neutral, like `documents.extraction.CVExtractor`."""

    async def read(self, excerpt: str) -> list[ModelPerson]: ...


# --------------------------------------------------------------------------
# What is sent
# --------------------------------------------------------------------------


#: Web pages lose the spaces between blocks when their markup goes:
#: "VöcklabruckSandra WagenederGeschäftsführerin", "KontaktdatenNiclas
#: StrzelskiTel.-Nr.". A lower-case letter right before a capital, or a
#: letter right before "+49", is a block boundary — outside e-mail addresses.
_GLUE_CASE = re.compile(r"(?<=[a-zäöüß])(?=[A-ZÄÖÜ])")
_GLUE_PHONE = re.compile(r"(?<=[A-Za-zäöüß.:])(?=\+\d)")


def _deglue(part: str) -> str:
    return _GLUE_PHONE.sub(" ", _GLUE_CASE.sub(" ", part))


def _flat(text: str) -> str:
    """One line, dashes as hyphens ("0781 800 – 3122"), glued blocks apart."""
    flat = re.sub(r"\s+", " ", C._clean(text)).replace("–", "-").replace("—", "-").strip()
    out, last = [], 0
    for m in C._EMAIL.finditer(flat):
        out += [_deglue(flat[last : m.start()]), m.group(0)]
        last = m.end()
    out.append(_deglue(flat[last:]))
    return "".join(out)


def _reach_spans(flat: str) -> list[tuple[int, int]]:
    spans = [(m.start(), m.end()) for m in C._EMAIL.finditer(flat)]
    spans += [
        (m.start(), m.end())
        for m in C._PHONE.finditer(flat)
        if C._phone_in(flat[m.start() : m.end() + 1])
    ]
    return sorted(spans)


def excerpt(text: str | None) -> str | None:
    """The lines around the ad's phone numbers and e-mails, at most
    `EXCERPT_MAX` characters; None when the ad gives none."""
    if not text:
        return None
    flat = _flat(text)
    spans = _reach_spans(flat)
    if not spans:
        return None
    windows: list[list[int]] = []
    for start, end in spans:
        lo, hi = max(0, start - _AROUND), min(len(flat), end + _AROUND)
        if windows and lo <= windows[-1][1]:
            windows[-1][1] = max(windows[-1][1], hi)
        else:
            windows.append([lo, hi])
    return " … ".join(flat[lo:hi] for lo, hi in windows)[:EXCERPT_MAX]


# --------------------------------------------------------------------------
# The checks
# --------------------------------------------------------------------------


def _phone_digits(phone: str) -> str:
    """National digits: "+49 711 123456", "0049 711 …" and "0711 123456" agree."""
    digits = re.sub(r"\D", "", phone)
    for prefix in ("0049", "0043", "0041", "49", "43", "41"):
        if digits.startswith(prefix) and len(digits) - len(prefix) >= 6:
            return digits[len(prefix) :].lstrip("0")
    return digits.lstrip("0")


#: An initial as a first or middle name: "P. Ruckdeschel", "Eve J. Koncewicz",
#: "Franz-J. Kappes".
_INITIAL = re.compile(rf"[{C._UPPER}]\.|{C._TOKEN}-[{C._UPPER}]\.")


def _name_shaped(tokens: list[str]) -> bool:
    for t in tokens:
        if _INITIAL.fullmatch(t):
            continue
        if t in C._NOT_NAMES or (t.isupper() and t in C._CAPS_NOT_NAMES):
            return False
        if C._UNIT_WORD.search(t) or C._BUSINESS.match(t) or C._ROLE_HINT.search(t):
            return False
        if C._STREET.search(t):  # "Daniel Gran-Straße 12" is an address
            return False
        if not (
            re.fullmatch(C._TOKEN, t) or re.fullmatch(C._PARTICLE, t) or re.fullmatch(C._CAPS, t)
        ):
            return False
    return bool(tokens) and not re.fullmatch(C._PARTICLE, tokens[0])


def ground(text: str | None, people: list[ModelPerson]) -> list[C.ContactMention]:
    """The people the model returned that the ad itself bears out (see the
    module docstring); the rest are dropped."""
    if not text or not people:
        return []
    flat = _flat(text)
    spans = _reach_spans(flat)
    phones: dict[str, str] = {}
    for m in C._PHONE.finditer(flat):
        if phone := C._phone_in(flat[m.start() : m.end() + 1]):
            phones.setdefault(_phone_digits(phone), phone)
    emails = {e.lower().rstrip("."): e.rstrip(".") for e in C._EMAIL.findall(flat)}

    found: dict[str, C.ContactMention] = {}
    for p in people:
        last = " ".join((p.last_name or "").split())
        first = " ".join((p.first_name or "").split()) or None
        salutation = p.salutation if p.salutation in ("Frau", "Herr") else None
        if not last or not _name_shaped((first.split() if first else []) + last.split()):
            continue
        if first:
            name = f"{first} {last}"
            # As written, or surname first: "Nortmeier Susanne", "Kasek, Helene".
            m = None
            for written in (name, f"{last} {first}", f"{last}, {first}"):
                m = re.search(rf"(?<![\w-]){re.escape(written)}(?![\w-])", flat)
                if m:
                    break
        elif salutation:
            name = last
            m = re.search(rf"\b(?:Frau|Herrn?) +{re.escape(last)}(?![\w-])", flat)
        else:
            continue  # a bare surname names nobody
        if m is None or C._LEGAL_FORM_AFTER.match(flat[m.end() :]):
            continue
        phone = None
        if p.phone:
            phone = phones.get(_phone_digits(p.phone.replace("–", "-")))
            if phone is None:
                continue  # invented number: distrust the whole answer for this person
        email = None
        if p.email:
            given = p.email.strip().rstrip(".")
            email = emails.get(given.lower())
            if email is None and _OBFUSCATED_AT.search(given) and given.lower() in flat.lower():
                email = _OBFUSCATED_AT.sub("@", given)  # "x[at]y.de", as the ad writes it
            if email is None:
                continue
        near = any(s - _NEAR <= m.end() and m.start() <= e + _NEAR for s, e in spans)
        # Far from the contact block, but the person's own address spells them.
        if not near and not (email and first and C._email_spells(email, name)):
            continue
        tail = flat[m.end() : m.end() + C._WINDOW_AFTER]
        phone = phone or C._phone_in(tail)
        window = flat[max(0, m.start() - C._WINDOW_BEFORE) : m.end() + C._WINDOW_AFTER]
        email = email or C._email_for(window, first, last)
        if email and C._GENERIC_LOCAL.match(email.split("@")[0]):
            email = None  # bewerbung@ is the company's inbox, not this person's
        role = p.role_title.strip() if p.role_title else None
        if role and role.lower() not in flat.lower():
            role = None
        mention = C.ContactMention(
            full_name=name,
            salutation=salutation,
            first_name=first,
            last_name=last,
            role_title=role,
            email=email,
            phone=phone,
            quote=C._quote(flat, m.start(), m.end()),
            phone_kind=C.phone_kind(phone),
            mobile=C._mobile_after(flat, m.end(), phone),
        )
        found.setdefault(C.person_key(first, last), mention)
    return list(found.values())


# --------------------------------------------------------------------------
# The model
# --------------------------------------------------------------------------

_SYSTEM = (
    "You read an excerpt of a German, Austrian or Swiss job advertisement and list the "
    "PEOPLE it names as contacts for applicants (recruiter, HR, hiring manager). Rules:\n"
    "1. Only people explicitly named in the text. Never invent or complete a name.\n"
    "2. Copy first_name and last_name EXACTLY as written, with the same spelling and "
    "accents. Use an empty string for a first name the text does not give.\n"
    "3. salutation: 'Frau' or 'Herr' if the text uses one for that person, else ''.\n"
    "4. phone / email: only a number or address written next to that person, copied "
    "exactly; else ''. role_title: their function as written, else ''.\n"
    "5. Departments, teams, companies and generic mailboxes are not people. If nobody "
    "is named, return an empty list."
)

_SCHEMA = {
    "name": "ad_contacts",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "people": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        k: {"type": "string"}
                        for k in ("first_name", "last_name", "salutation", "role_title", "phone", "email")
                    },
                    "required": ["first_name", "last_name", "salutation", "role_title", "phone", "email"],
                },
            }
        },
        "required": ["people"],
    },
}


class OpenAIContactReader:
    def __init__(self, api_key: str, model: str) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key, timeout=_TIMEOUT, max_retries=1)
        self._model = model

    async def read(self, excerpt: str) -> list[ModelPerson]:
        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": excerpt},
            ],
            response_format={"type": "json_schema", "json_schema": _SCHEMA},  # type: ignore[arg-type]
        )
        data = json.loads(response.choices[0].message.content or "{}")
        return [
            ModelPerson(
                first_name=(x.get("first_name") or None),
                last_name=x.get("last_name") or "",
                salutation=(x.get("salutation") or None),
                role_title=(x.get("role_title") or None),
                phone=(x.get("phone") or None),
                email=(x.get("email") or None),
            )
            for x in data.get("people", [])
        ]


def reader_from_settings() -> ContactReader | None:
    """The configured reader, or None — no key, the heuristic provider (CI) or
    `hub_contacts_model` set empty (the kill switch) turn the layer off."""
    if settings.llm_provider == "heuristic" or not settings.openai_api_key:
        return None
    if not settings.hub_contacts_model:
        return None
    return OpenAIContactReader(settings.openai_api_key, settings.hub_contacts_model)


# --------------------------------------------------------------------------
# The pass
# --------------------------------------------------------------------------


async def _ask(
    reader: ContactReader, sem: asyncio.Semaphore, texts: list[tuple[str, str, dt.datetime | None]]
) -> list[tuple[C.ContactMention, str, dt.datetime | None]]:
    out = []
    for origin, body, fetched_at in texts:
        sent = excerpt(body)
        if not sent:
            continue
        async with sem:
            people = await asyncio.wait_for(reader.read(sent), timeout=_TIMEOUT + 5)
        out += [(m, origin, fetched_at) for m in ground(body, people)]
    return out


async def backfill(
    session: AsyncSession, *, limit: int, reader: ContactReader | None, count: bool = True
) -> dict[str, int]:
    """Ask the model about up to `limit` queued ads; store what passes the
    checks. `remaining` is -1 when no model is configured, else (with
    `count`) the ads still queued — a count batch callers ask for once."""
    if reader is None:
        return {"read": 0, "contacts": 0, "failed": 0, "remaining": -1}
    ids = list(
        (
            await session.execute(
                select(HubJobPosting.id)
                .where(HubJobPosting.contacts_model_due.is_(True))
                .order_by(HubJobPosting.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    stored = failed = 0
    if ids:
        rows = (
            await session.execute(
                select(
                    HubJobPosting.id,
                    HubJobPosting.hub_company_id,
                    HubJobPosting.description_fetched_at,
                    HubJobPosting.source_page_fetched_at,
                    HubPostingPayload.description,
                    HubPostingPayload.source_page_text,
                )
                .outerjoin(HubPostingPayload, HubPostingPayload.hub_job_posting_id == HubJobPosting.id)
                .where(HubJobPosting.id.in_(ids))
            )
        ).all()
        rules = await suppression.load(session)
        sem = asyncio.Semaphore(_CONCURRENCY)

        def texts_of(r: Any) -> list[tuple[str, str, dt.datetime | None]]:
            out = []
            for origin, body, at in (
                ("ad", r.description, r.description_fetched_at),
                ("page", r.source_page_text, r.source_page_fetched_at),
            ):
                if body:
                    out.append((origin, rules.redact(body) if rules.may_name_someone(body) else body, at))
            return out

        answers = await asyncio.gather(
            *(_ask(reader, sem, texts_of(r)) for r in rows), return_exceptions=True
        )
        values: list[dict[str, Any]] = []
        done: list[dict[str, Any]] = []
        now = dt.datetime.now(dt.UTC)
        for r, answer in zip(rows, answers, strict=True):
            if isinstance(answer, BaseException):
                failed += 1
                logger.warning("contact model failed for posting %s: %s", r.id, type(answer).__name__)
                continue
            seen: set[str] = set()
            for m, origin, fetched_at in answer:
                key = C.person_key(m.first_name, m.last_name)
                if key in seen or rules.names(m.first_name, m.last_name):
                    continue
                seen.add(key)
                values.append(
                    {
                        "hub_job_posting_id": r.id,
                        "hub_company_id": r.hub_company_id,
                        "person_key": key,
                        "full_name": m.full_name[:200],
                        "salutation": m.salutation,
                        "first_name": m.first_name[:120] if m.first_name else None,
                        "last_name": m.last_name[:120],
                        "role_title": m.role_title[:200] if m.role_title else None,
                        "phone": m.phone[:60] if m.phone else None,
                        "phone_kind": m.phone_kind,
                        "mobile": m.mobile[:60] if m.mobile else None,
                        "email": m.email[:320] if m.email else None,
                        "quote": m.quote,
                        "text_source": origin,
                        "source_fetched_at": fetched_at,
                        "found_by": "model",
                    }
                )
            done.append({"b_id": r.id})
        if values:
            await session.execute(insert(HubAdContact), values)
        if done:
            table = HubJobPosting.__table__
            connection = await session.connection()
            await connection.execute(
                update(table)
                .where(table.c.id == bindparam("b_id"))
                .values(contacts_model_due=False, contacts_model_at=now),
                done,
            )
        stored = len(values)
    await session.commit()
    result = {"read": len(ids) - failed, "contacts": stored, "failed": failed}
    if count:
        result["remaining"] = int(
            await session.scalar(
                select(func.count(HubJobPosting.id)).where(HubJobPosting.contacts_model_due.is_(True))
            )
            or 0
        )
    return result
