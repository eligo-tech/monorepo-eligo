"""Candidate business logic. Tenant isolation is enforced on every query."""

from __future__ import annotations

import datetime as dt
import enum
import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.candidates.models import Candidate
from app.domain.candidates.schemas import CandidateCreate, CandidateUpdate
from app.domain.common.enums import ConfidenceSource, WorkPermitStatus, is_evidence
from app.domain.verification import service as verification
from app.domain.verification.models import EnrichmentRecord
from app.domain.verification.schemas import ProposedChange


async def list_candidates(
    session: AsyncSession, *, tenant_id: uuid.UUID, limit: int = 100
) -> list[Candidate]:
    result = await session.execute(
        select(Candidate)
        .where(Candidate.tenant_id == tenant_id)
        .order_by(Candidate.full_name)
        .limit(limit)
    )
    return list(result.scalars().all())


async def filter_candidates(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    skill: str | None = None,
    city: str | None = None,
    available_within_weeks: int | None = None,
    limit: int = 50,
) -> tuple[list[Candidate], int]:
    """Candidates matching every filter given, and how many matched in total.

    Filters run over the WHOLE pool before the limit — filtering a capped page
    answers "the Berlin ones among the first hundred" (the ELI-7 mistake).
    In Python, because `skills` is a JSON list and a portable JSON-contains
    does not exist across SQLite and Postgres; a workspace pool is thousands
    of rows, not millions. An unknown availability never passes that filter.
    """
    rows = (
        await session.execute(
            select(Candidate).where(Candidate.tenant_id == tenant_id).order_by(Candidate.full_name)
        )
    ).scalars()
    want_skill = skill.strip().lower() if skill else None
    want_city = city.strip().lower() if city else None
    hits = [
        c
        for c in rows
        if (not want_skill or want_skill in {str(s).strip().lower() for s in c.skills or []})
        and (not want_city or want_city in {(c.city or "").lower(), (c.location or "").lower()})
        and (
            available_within_weeks is None
            or (c.availability_weeks is not None and c.availability_weeks <= available_within_weeks)
        )
    ]
    return hits[:limit], len(hits)


async def count_candidates(session: AsyncSession, *, tenant_id: uuid.UUID) -> int:
    """How many the tenant has, independent of any page."""
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Candidate)
            .where(Candidate.tenant_id == tenant_id)
        )
        or 0
    )


async def get_candidate(
    session: AsyncSession, *, tenant_id: uuid.UUID, candidate_id: uuid.UUID
) -> Candidate | None:
    result = await session.execute(
        select(Candidate).where(
            Candidate.tenant_id == tenant_id,
            Candidate.id == candidate_id,
        )
    )
    return result.scalar_one_or_none()


async def create_candidate(
    session: AsyncSession, *, data: CandidateCreate
) -> Candidate:
    """Write a new candidate from the whole payload.

    Built from `model_dump` rather than a hand-written field list. The list
    version had to be extended for every new column and silently dropped the
    ones nobody remembered — `salary_minimum`, `profile_summary`,
    `interview_availability` and `other_processes` all arrived on the schema
    and were discarded here on the way to the row.
    """
    tenant_id = data.tenant_id or settings.default_tenant_id
    # Somebody this workspace erased (GDPR Art. 17) is not re-created by
    # hand without the recruiter saying they came back. Covers the CV upload
    # too, which creates through here.
    from app.domain.erasure import service as erasure

    await erasure.guard_readd(
        session, tenant_id=tenant_id, email=data.email, override=data.override_suppression
    )
    values = data.model_dump(exclude_none=True)
    values.pop("tenant_id", None)
    # The schema carries a few fields the row does not; dropping them here
    # beats an unexpected-keyword TypeError at runtime.
    values = {k: v for k, v in values.items() if hasattr(Candidate, k)}
    candidate = Candidate(tenant_id=tenant_id, **values)
    session.add(candidate)
    await session.flush()
    await session.commit()
    await session.refresh(candidate)
    return candidate


# Columns declared NOT NULL — a manual edit must not blank these out.
_NON_NULLABLE = frozenset(
    {"full_name", "salary_currency", "work_permit", "focus_areas", "skills"}
)

# The fields both scores are measured over. One list, so "70% vollständig"
# and "40% verifiziert" are shares of the same thing and can be compared.
_KEY_FIELDS = (
    "full_name",
    "email",
    "phone",
    "current_title",
    "current_company",
    "location",
    "date_of_birth",
    "city",
    "country",
    "linkedin_url",
    "salary_expectation",
    "work_permit",
    "skills",
)


def _norm(value: object) -> object:
    """Normalise an enum to its value so DB strings and enums compare equal."""
    return value.value if isinstance(value, enum.Enum) else value


def _as_text(value: object) -> str | None:
    """Serialise a proposed value for the provenance record (Text column)."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _is_filled(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != "" and value != WorkPermitStatus.UNKNOWN.value
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def completeness(candidate: Candidate) -> float:
    """Share of the key fields that have a value. Says nothing about truth.

    This is what `verification_score` used to compute, and the mismatch
    mattered: the pool is 447 records of which 446 scored 0, because the only
    path that recomputed it was a manual edit — so a column labelled
    "Verifizierung" showed neither verification nor completeness.
    """
    filled = sum(1 for f in _KEY_FIELDS if _is_filled(getattr(candidate, f, None)))
    return round(filled / len(_KEY_FIELDS), 4)


async def verified_share(
    session: AsyncSession, *, tenant_id: uuid.UUID, candidate_id: uuid.UUID
) -> float:
    """Share of the key fields that have EVIDENCE behind them.

    A field counts when a committed `EnrichmentRecord` says where the value
    came from and that source is one a reader could check — a CV we hold, a
    page we can cite, a person who confirmed it (`EVIDENCE_SOURCES`). An
    imported value has no such record and therefore does not count: the ATS
    said so, which is a claim, not a check.

    So an imported record scores 0, and that is the honest answer rather than
    a bug. The number only moves when something is actually established.
    """
    rows = await session.execute(
        select(EnrichmentRecord.field, EnrichmentRecord.source).where(
            EnrichmentRecord.tenant_id == tenant_id,
            EnrichmentRecord.entity_type == "candidate",
            EnrichmentRecord.entity_id == candidate_id,
            EnrichmentRecord.committed.is_(True),
        )
    )
    evidenced = {
        field for field, source in rows if field in _KEY_FIELDS and is_evidence(source)
    }
    return round(len(evidenced) / len(_KEY_FIELDS), 4)


async def recompute_scores(
    session: AsyncSession, *, tenant_id: uuid.UUID, candidate: Candidate
) -> Candidate:
    """Bring both numbers in line with the record as it now stands.

    Called from every path that writes a candidate — the manual edit, the ATS
    import, and `verify_and_commit` — because a score maintained by exactly
    one of three writers is a score that is wrong for the other two.
    """
    candidate.completeness_score = completeness(candidate)
    candidate.verification_score = await verified_share(
        session, tenant_id=tenant_id, candidate_id=candidate.id
    )
    return candidate


class ConcurrentEdit(Exception):
    """Somebody else wrote one of these fields while this editor was open.

    Carries the field names rather than a bare "conflict": the recruiter's
    next question is always *which* value is in dispute, and the names come
    straight off the `EnrichmentRecord`s so nothing has to be guessed.
    """

    def __init__(self, fields: list[str]) -> None:
        self.fields = fields
        super().__init__(
            "changed by someone else since this record was opened: "
            + ", ".join(fields)
        )


async def _fields_changed_since(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    since: dt.datetime,
    among: set[str],
) -> list[str]:
    """Which of `among` a committed change has touched since `since`.

    Reads `enrichment_records`, not `candidates.updated_at`, and the
    difference is the whole point. `updated_at` moves for reasons that are
    not an edit — `recompute_scores` writes `verification_score` on every
    save, so a row-level timestamp check would refuse a perfectly safe write
    and teach people to click past the warning. The enrichment ledger is
    per field, already indexed on `entity_id`, and is written by
    `verify_and_commit` on the one path anything reaches a candidate column.

    The failure mode is therefore a *missed* conflict, never a false one: a
    write that somehow bypassed the gate is invisible here. That is exactly
    today's behaviour, so this can only improve on it — whereas a false
    conflict would be a new way to lose work.
    """
    if not among:
        return []
    # The client sends whatever offset its clock is in, and SQLAlchemy's
    # SQLite dialect binds a datetime by its *wall-clock* fields with the
    # tzinfo dropped — so a Berlin-offset baseline would be compared two
    # hours adrift of a column that stores UTC. Postgres would have got this
    # right on its own; normalising here keeps the two dialects answering the
    # same question. A naive value is taken as UTC, which is what every
    # timestamp this codebase stores already is (see `pipeline.as_utc`).
    since = (
        since.astimezone(dt.UTC) if since.tzinfo is not None
        else since.replace(tzinfo=dt.UTC)
    )
    rows = await session.execute(
        select(EnrichmentRecord.field)
        .where(
            EnrichmentRecord.tenant_id == tenant_id,
            EnrichmentRecord.entity_type == "candidate",
            EnrichmentRecord.entity_id == candidate_id,
            EnrichmentRecord.committed.is_(True),
            EnrichmentRecord.created_at > since,
            EnrichmentRecord.field.in_(among),
        )
        .distinct()
    )
    return sorted(rows.scalars().all())


async def update_candidate(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    patch: CandidateUpdate,
    editor: str | None = None,
) -> Candidate | None:
    """Apply a manual recruiter edit, one verified change per field.

    Each field that actually changes is routed through
    ``verification.verify_and_commit`` as a ``HUMAN_VERIFIED`` proposal
    (confidence 1.0). Because a human is the authoritative source, there is no
    external state to re-check — the value passes and is written via the
    ``apply_hook``, leaving a VERIFY + WRITE receipt and an ``EnrichmentRecord``.
    Returns ``None`` if the candidate does not exist for this tenant.

    Raises `ConcurrentEdit` when `patch.base_updated_at` is given and another
    user has committed one of the same fields since — see
    `_fields_changed_since`. A patch that leaves that baseline unset is
    written unconditionally, which is what every non-cockpit caller does.
    """
    candidate = await get_candidate(
        session, tenant_id=tenant_id, candidate_id=candidate_id
    )
    if candidate is None:
        return None

    detail = f"manual edit via recruiter UI ({editor})" if editor else (
        "manual edit via recruiter UI"
    )
    changes = patch.model_dump(exclude_unset=True, mode="json")
    # Control, not content: it names the version this edit was composed
    # against and must never be looked up as a column.
    changes.pop("base_updated_at", None)

    # Settle what would really change BEFORE asking whether anyone else
    # touched it. Re-typing the value that is already stored is not an edit
    # and must not collide with somebody who typed the same thing first —
    # agreeing is not a conflict.
    effective: dict[str, object] = {}
    for field, new_value in changes.items():
        # Never NULL a non-nullable column (would raise IntegrityError). The UI
        # never does this; it guards against a raw-API null.
        if field in _NON_NULLABLE and (
            new_value is None or (isinstance(new_value, str) and not new_value.strip())
        ):
            continue
        if _norm(getattr(candidate, field, None)) == _norm(new_value):
            continue
        effective[field] = new_value

    if patch.base_updated_at is not None:
        clash = await _fields_changed_since(
            session,
            tenant_id=tenant_id,
            candidate_id=candidate_id,
            since=patch.base_updated_at,
            among=set(effective),
        )
        if clash:
            # Nothing has been written yet — the loop below has not run — so
            # refusing here leaves the record exactly as the other person left
            # it. The caller decides whether to reload or to overwrite.
            raise ConcurrentEdit(clash)

    applied: list[str] = []

    for field, new_value in effective.items():
        change = ProposedChange(
            tenant_id=tenant_id,
            entity_type="candidate",
            entity_id=candidate_id,
            field=field,
            proposed_value=_as_text(new_value),
            source=ConfidenceSource.HUMAN_VERIFIED,
            source_detail=detail,
            confidence=1.0,
        )

        async def _apply(
            _session: AsyncSession,
            _change: ProposedChange,
            _field: str = field,
            _value: object = new_value,
        ) -> None:
            setattr(candidate, _field, _value)

        await verification.verify_and_commit(
            session,
            change=change,
            agent="recruiter_manual_edit",
            apply_hook=_apply,
            actor=editor,
        )
        applied.append(field)

    if applied:
        # The edit went through `verify_and_commit`, so each field now has a
        # `human_verified` record behind it — the score is read back off those
        # records rather than assumed from the fact that someone typed.
        await session.flush()
        await recompute_scores(session, tenant_id=tenant_id, candidate=candidate)
        await session.flush()

    await session.commit()
    await session.refresh(candidate)
    return candidate


def _norm_company(name: str) -> str:
    """Fold the spellings a recruiter types into one key.

    "Trade Republic", "trade republic" and "Trade Republic GmbH" are one
    company for the purpose of counting who is hiring. Legal suffixes are
    dropped and case is ignored; anything subtler (abbreviations, umlaut
    spellings) belongs in the hub's `resolution.py`, not in a count.
    """
    cleaned = name.strip().lower()
    for suffix in (" gmbh & co. kg", " gmbh", " ag", " se", " kg", " ug", " e.k."):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    return " ".join(cleaned.split())


async def competing_employers(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[dict]:
    """Who else is interviewing this tenant's candidates — a sales signal.

    `data/examples/metadata_quailfication.txt` asks where a candidate's other
    processes are running, and says why: whoever is looking at the same
    profiles is a potential client. One name is an anecdote; the same name
    across three candidates is a company with a hiring need in this niche.

    Returns the companies with the candidates who named them, busiest first.
    Names come from recruiters, so the display name is the most recent
    spelling and the grouping key is the normalized one.
    """
    rows = (
        await session.execute(
            select(Candidate)
            .where(Candidate.tenant_id == tenant_id)
            .order_by(Candidate.updated_at.desc())
        )
    ).scalars()

    grouped: dict[str, dict] = {}
    for candidate in rows:
        for raw in candidate.other_process_companies or []:
            name = (raw or "").strip()
            if not name:
                continue
            key = _norm_company(name)
            entry = grouped.setdefault(
                key, {"company": name, "candidate_count": 0, "candidates": []}
            )
            if candidate.full_name not in entry["candidates"]:
                entry["candidates"].append(candidate.full_name)
                entry["candidate_count"] += 1

    return sorted(
        grouped.values(),
        key=lambda e: (-e["candidate_count"], e["company"].lower()),
    )
