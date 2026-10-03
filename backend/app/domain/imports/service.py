"""Mapping a customer's file onto the record, and writing it.

Three steps, and the middle one is the product: **preview before writing.**
An import that silently creates 800 half-filled candidates is worse than one
that refuses, so `plan()` reports exactly what would happen — created,
updated, skipped and why — against the real database, and `commit()` then
does that and nothing else.

Re-runnable by construction: each entity names its identity fields, a row
that matches an existing record updates it, and a file imported twice is one
book. That matters more than it sounds — the first import of a real export
always has something wrong with it, and the fix is to correct the file and
run it again.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.imports.spec import SPECS, EntitySpec

#: A cell can hold "Python, Spark; Airflow" — all three separators appear.
_LIST_SPLIT = re.compile(r"[;,|]")
#: Salary cells arrive as "85.000 €", "85000", "85,000", "ca. 85 TEUR".
_DIGITS = re.compile(r"\d+")
#: Rows beyond this are a database dump, not an onboarding file. The cap is
#: about holding a request open, not about the data.
MAX_ROWS = 5000


class UnknownEntity(ValueError):
    pass


def normalize_header(text: str) -> str:
    """"E-Mail Adresse" → "emailadresse"; "Nachname " → "nachname"."""
    folded = unicodedata.normalize("NFKD", text.lower())
    folded = folded.replace("ß", "ss")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", folded)


def suggest_mapping(entity: str, columns: list[str]) -> dict[str, str]:
    """Column → canonical field, guessed from the header text.

    Exact synonym match first, then the field's own name, then a contains
    match for headers like "E-Mail (geschäftlich)". First column to claim a
    field wins: two columns mapped to one field would silently drop one.
    """
    spec = _spec(entity)
    by_synonym: dict[str, str] = {}
    for f in spec.fields:
        by_synonym[normalize_header(f.name)] = f.name
        by_synonym[normalize_header(f.label)] = f.name
        for synonym in f.synonyms:
            by_synonym.setdefault(normalize_header(synonym), f.name)

    mapping: dict[str, str] = {}
    taken: set[str] = set()
    for column in columns:
        key = normalize_header(column)
        target = by_synonym.get(key)
        if target is None:
            # "E-Mail (privat)" → emailprivat; look for a synonym inside it,
            # longest first so "mindestgehalt" beats "gehalt".
            for synonym in sorted(by_synonym, key=len, reverse=True):
                if len(synonym) >= 4 and synonym in key:
                    target = by_synonym[synonym]
                    break
        if target and target not in taken:
            mapping[column] = target
            taken.add(target)
    return mapping


def _satisfiable(spec: EntitySpec, name: str, mapped: set[str]) -> bool:
    """Is this required field either mapped, or buildable from what is?"""
    if name in mapped:
        return True
    for target, sources in spec.composed:
        if target == name and any(source in mapped for source in sources):
            return True
    return False


def _spec(entity: str) -> EntitySpec:
    spec = SPECS.get(entity)
    if spec is None:
        raise UnknownEntity(f"unbekannte Datenart {entity!r}")
    return spec


def coerce(value: str, kind: str) -> object:
    value = (value or "").strip()
    if not value:
        return None
    if kind == "int":
        digits = "".join(_DIGITS.findall(value.replace(".", "").replace(" ", "")))
        if not digits:
            return None
        number = int(digits)
        # "85" in a salary column means 85.000 — a yearly salary below 1000
        # is somebody writing in thousands, not a real figure.
        return number * 1000 if number < 1000 else number
    if kind == "list":
        return [part.strip() for part in _LIST_SPLIT.split(value) if part.strip()]
    return value


@dataclass
class RowPlan:
    """One row, as it would land."""

    line: int
    action: str  # "create" | "update" | "skip"
    values: dict
    reason: str | None = None
    #: Set when the row matches an existing record.
    existing_id: uuid.UUID | None = None


@dataclass
class Plan:
    entity: str
    rows: list[RowPlan] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        out = {"create": 0, "update": 0, "skip": 0}
        for row in self.rows:
            out[row.action] += 1
        return out


def build_values(spec: EntitySpec, row: dict[str, str], mapping: dict[str, str]) -> dict:
    """One sheet row → canonical values, coerced."""
    kinds = {f.name: f.kind for f in spec.fields}
    values: dict = {}
    for column, target in mapping.items():
        if target not in kinds:
            continue
        value = coerce(row.get(column, ""), kinds[target])
        if value is None or value == [] or value == "":
            continue
        values[target] = value

    # A name split across two columns is the commonest shape; compose it so
    # the required field is satisfied without the customer editing the file.
    # The reverse (full → first/last) is NOT done: splitting "Dr. Anna von
    # Weber" is guesswork, and a wrong surname is worse than none.
    for target, sources in spec.composed:
        if values.get(target):
            continue
        composed = " ".join(str(values[s]) for s in sources if values.get(s))
        if composed:
            values[target] = composed
    return values


async def plan(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    entity: str,
    rows: list[dict[str, str]],
    mapping: dict[str, str],
) -> Plan:
    """What this file would do to the record. Reads only."""
    spec = _spec(entity)
    result = Plan(entity=entity)

    mapped = set(mapping.values())
    missing = [r for r in spec.required if not _satisfiable(spec, r, mapped)]
    if missing:
        labels = {f.name: f.label for f in spec.fields}
        result.problems.append(
            "Pflichtfeld nicht zugeordnet: "
            + ", ".join(labels.get(m, m) for m in missing)
        )
        return result

    if len(rows) > MAX_ROWS:
        result.problems.append(
            f"{len(rows)} Zeilen — es werden die ersten {MAX_ROWS} geplant. "
            "Bitte die Datei teilen."
        )
        rows = rows[:MAX_ROWS]

    existing = await _existing_index(session, tenant_id=tenant_id, spec=spec)
    seen_in_file: dict[tuple[str, str], int] = {}

    for index, raw in enumerate(rows, start=2):  # line 1 is the header
        values = build_values(spec, raw, mapping)
        missing_required = [r for r in spec.required if not values.get(r)]
        if missing_required:
            labels = {f.name: f.label for f in spec.fields}
            result.rows.append(
                RowPlan(
                    line=index,
                    action="skip",
                    values=values,
                    reason=f"ohne {', '.join(labels.get(m, m) for m in missing_required)}",
                )
            )
            continue

        key = _identity_key(spec, values)
        if key and key in seen_in_file:
            result.rows.append(
                RowPlan(
                    line=index,
                    action="skip",
                    values=values,
                    reason=f"Dublette von Zeile {seen_in_file[key]}",
                )
            )
            continue
        if key:
            seen_in_file[key] = index

        match = existing.get(key) if key else None
        result.rows.append(
            RowPlan(
                line=index,
                action="update" if match else "create",
                values=values,
                existing_id=match,
            )
        )
    return result


def _identity_key(spec: EntitySpec, values: dict) -> tuple[str, str] | None:
    """The first identity field this row actually has."""
    for name in spec.identity:
        value = values.get(name)
        if isinstance(value, str) and value.strip():
            return (name, value.strip().lower())
    return None


async def _existing_index(
    session: AsyncSession, *, tenant_id: uuid.UUID, spec: EntitySpec
) -> dict[tuple[str, str], uuid.UUID]:
    """Everything already in this workspace, keyed the way rows are keyed."""
    model = _model(spec)
    rows = (
        await session.execute(select(model).where(model.tenant_id == tenant_id))
    ).scalars()
    index: dict[tuple[str, str], uuid.UUID] = {}
    for row in rows:
        for name in spec.identity:
            value = getattr(row, name, None)
            if isinstance(value, str) and value.strip():
                index.setdefault((name, value.strip().lower()), row.id)
    return index


def _model(spec: EntitySpec):
    from app.domain.candidates.models import Candidate
    from app.domain.companies.models import Company
    from app.domain.jobs.models import Job
    from app.domain.managers.models import Manager

    return {
        "Kandidaten": Candidate,
        "Firmen": Company,
        "Ansprechpartner": Manager,
        "Mandate": Job,
    }[spec.label]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


async def commit(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    entity: str,
    rows: list[dict[str, str]],
    mapping: dict[str, str],
) -> dict:
    """Perform the plan. Writes exactly what `plan()` said it would.

    Direct writes, like the ATS import and for the same reason: a customer
    moving their own book is not an agent making a claim, so it owes
    provenance (`source`) rather than a receipt per field. Anything a
    recruiter edits afterwards goes through the verification gate as usual.
    """
    spec = _spec(entity)
    prepared = await plan(
        session, tenant_id=tenant_id, entity=entity, rows=rows, mapping=mapping
    )
    if prepared.problems and not prepared.rows:
        return {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "problems": prepared.problems,
        }

    model = _model(spec)
    # Companies and managers/jobs arrive in separate files, so a row naming a
    # company we do not have yet creates a stub rather than being dropped —
    # onboarding should not depend on the order the files are uploaded.
    companies = await _company_index(session, tenant_id=tenant_id)

    created = updated = 0
    for row in prepared.rows:
        if row.action == "skip":
            continue
        values = dict(row.values)
        company_name = values.pop("company_name", None)

        # Resolve the company FIRST: `managers.company_id` is NOT NULL, so a
        # record built before its company exists cannot even be flushed.
        if company_name:
            key = company_name.strip().lower()
            company_id = companies.get(key)
            if company_id is None:
                company_id = await _create_company_stub(
                    session, tenant_id=tenant_id, name=company_name.strip()
                )
                companies[key] = company_id
            field_name = (
                "company_id" if hasattr(model, "company_id") else "client_company_id"
            )
            values[field_name] = company_id

        if row.existing_id:
            record = await session.get(model, row.existing_id)
            if record is None:  # deleted between plan and commit
                continue
            for name, value in values.items():
                if hasattr(record, name):
                    setattr(record, name, value)
            updated += 1
        else:
            payload = {k: v for k, v in values.items() if hasattr(model, k)}
            record = model(tenant_id=tenant_id, **payload)
            if hasattr(record, "source") and not getattr(record, "source", None):
                record.source = spec.source
            if hasattr(record, "external_source"):
                record.external_source = spec.source
            session.add(record)
            created += 1

    await session.commit()
    return {
        "created": created,
        "updated": updated,
        "skipped": prepared.counts["skip"],
        "problems": prepared.problems,
    }


async def _company_index(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> dict[str, uuid.UUID]:
    from app.domain.companies.models import Company

    rows = (
        await session.execute(select(Company).where(Company.tenant_id == tenant_id))
    ).scalars()
    return {row.name.strip().lower(): row.id for row in rows if row.name}


async def _create_company_stub(
    session: AsyncSession, *, tenant_id: uuid.UUID, name: str
) -> uuid.UUID:
    """A company named by a contact or a mandate but not yet imported."""
    from app.domain.companies.models import Company

    company = Company(
        tenant_id=tenant_id, name=name, is_client=True, source="datei-import"
    )
    session.add(company)
    await session.flush()
    return company.id
