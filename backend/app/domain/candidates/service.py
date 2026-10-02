"""Candidate business logic. Tenant isolation is enforced on every query."""

from __future__ import annotations

import enum
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.candidates.models import Candidate
from app.domain.candidates.schemas import CandidateCreate, CandidateUpdate
from app.domain.common.enums import ConfidenceSource, WorkPermitStatus
from app.domain.verification import service as verification
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
    values = data.model_dump(exclude_none=True)
    values.pop("tenant_id", None)
    # The schema carries a few fields the row does not; dropping them here
    # beats an unexpected-keyword TypeError at runtime.
    values = {k: v for k, v in values.items() if hasattr(Candidate, k)}
    candidate = Candidate(tenant_id=tenant_id, **values)
    _sync_industry(candidate)
    session.add(candidate)
    await session.flush()
    await session.commit()
    await session.refresh(candidate)
    return candidate


def _sync_industry(candidate: Candidate) -> None:
    """Keep the legacy single `industry` in step with `industries`.

    The expand half of expand/contract (migration 0030): `industries` is the
    field of record, `industry` still exists so a deploy does not break the
    running container mid-rollout, and it is dropped in a follow-up. Without
    this the legacy column would quietly drift away from the truth.
    """
    if candidate.industries:
        candidate.industry = candidate.industries[0]
    elif candidate.industry and not candidate.industries:
        candidate.industries = [candidate.industry]


# Columns declared NOT NULL — a manual edit must not blank these out.
_NON_NULLABLE = frozenset({"full_name", "salary_currency", "work_permit"})

# Fields that count toward the "verified share" surfaced to recruiters. A manual
# edit human-verifies a field, so completing these raises verification_score.
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


def _verification_score(candidate: Candidate) -> float:
    filled = sum(1 for f in _KEY_FIELDS if _is_filled(getattr(candidate, f, None)))
    return round(filled / len(_KEY_FIELDS), 4)


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
    applied: list[str] = []

    for field, new_value in changes.items():
        # Never NULL a non-nullable column (would raise IntegrityError). The UI
        # never does this; it guards against a raw-API null.
        if field in _NON_NULLABLE and (
            new_value is None or (isinstance(new_value, str) and not new_value.strip())
        ):
            continue
        if _norm(getattr(candidate, field, None)) == _norm(new_value):
            continue

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
        # A human-entered field is verified; reflect that in the score, but never
        # lower a score an agent already established.
        candidate.verification_score = max(
            candidate.verification_score, _verification_score(candidate)
        )
        if "industries" in applied or "industry" in applied:
            _sync_industry(candidate)
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
