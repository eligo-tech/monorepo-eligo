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
    tenant_id = data.tenant_id or settings.default_tenant_id
    candidate = Candidate(
        tenant_id=tenant_id,
        full_name=data.full_name,
        email=data.email,
        phone=data.phone,
        current_title=data.current_title,
        current_company=data.current_company,
        location=data.location,
        merged_identities=data.merged_identities,
        skills=data.skills,
        work_history=data.work_history,
        salary_expectation=data.salary_expectation,
        salary_currency=data.salary_currency,
        availability_weeks=data.availability_weeks,
        work_permit=data.work_permit,
        # Extended profile (aiFind field set) — persisted so the dossier fills in.
        first_name=data.first_name,
        last_name=data.last_name,
        sex=data.sex,
        name_prefix=data.name_prefix,
        date_of_birth=data.date_of_birth,
        street=data.street,
        postal_code=data.postal_code,
        city=data.city,
        country=data.country,
        linkedin_url=data.linkedin_url,
        xing_url=data.xing_url,
        industry=data.industry,
        employment_type=data.employment_type,
        willing_to_relocate=data.willing_to_relocate,
        notice_period=data.notice_period,
        availability=data.availability,
        total_years_experience=data.total_years_experience,
        current_salary=data.current_salary,
        languages=data.languages,
        education=data.education,
        working_experience=data.working_experience,
        motivation=data.motivation,
        source=data.source,
    )
    session.add(candidate)
    await session.flush()
    await session.commit()
    await session.refresh(candidate)
    return candidate


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
        await session.flush()

    await session.commit()
    await session.refresh(candidate)
    return candidate