"""Matching service.

STAGE 1 — deterministic hard filters (:func:`apply_hard_filters`): plain Python,
no LLM, fully reproducible. A candidate that fails ANY hard filter is excluded
(with an explicit reason).

STAGE 2 — soft ranking (:func:`rerank_and_explain`): the LLM boundary. In the
scaffold it is a transparent heuristic returning mock ``MatchReason`` objects.
An LLM would replace ONLY the body of ``rerank_and_explain`` — the hard-filter
gate above it is never delegated to a model.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.candidates.models import Candidate
from app.domain.common.enums import MatchStrength, ReceiptAction, WorkPermitStatus
from app.domain.jobs.models import Job
from app.domain.matching.models import MatchReceipt
from app.domain.matching.schemas import MatchReason, MatchResult
from app.domain.verification import service as verification_service

# Work-permit statuses that satisfy a job requiring right-to-work.
_ELIGIBLE_PERMITS = {
    WorkPermitStatus.CITIZEN,
    WorkPermitStatus.PERMANENT,
    WorkPermitStatus.WORK_VISA,
}


def _norm(value: str) -> str:
    return value.strip().lower()


def apply_hard_filters(candidate: Candidate, job: Job) -> list[str]:
    """Return a list of hard-filter failure reasons (empty == candidate passes).

    Deterministic and side-effect free. These are non-negotiable constraints:
    a candidate failing any of them is legally/commercially unplaceable, so no
    amount of soft similarity can override them.
    """
    failures: list[str] = []

    # 1. Right to work.
    if job.requires_work_permit and candidate.work_permit not in _ELIGIBLE_PERMITS:
        failures.append(
            f"work permit '{candidate.work_permit.value}' does not satisfy "
            f"right-to-work requirement"
        )

    # 2. Location radius (simplified: same-city match unless radius is open).
    #    A real implementation geocodes both and compares distance <= radius.
    if job.location and candidate.location:
        same_place = _norm(job.location) in _norm(candidate.location) or _norm(
            candidate.location
        ) in _norm(job.location)
        if job.location_radius_km is not None and not same_place:
            failures.append(
                f"location '{candidate.location}' outside "
                f"{job.location_radius_km}km of '{job.location}'"
            )

    # 3. Salary cap — candidate expectation must fit the band ceiling.
    if job.salary_max is not None and candidate.salary_expectation is not None:
        if candidate.salary_expectation > job.salary_max:
            failures.append(
                f"salary expectation {candidate.salary_expectation} "
                f"exceeds cap {job.salary_max}"
            )

    # 4. Required certifications — every one must be present.
    candidate_skills = {_norm(s) for s in candidate.skills}
    for cert in job.required_certifications:
        if _norm(cert) not in candidate_skills:
            failures.append(f"missing required certification '{cert}'")

    # 5. Must-have skills — every one must be present.
    for skill in job.must_have_skills:
        if _norm(skill) not in candidate_skills:
            failures.append(f"missing must-have skill '{skill}'")

    return failures


def rerank_and_explain(candidate: Candidate, job: Job) -> tuple[
    float, MatchStrength, list[MatchReason]
]:
    """SOFT ranking + explanation — THE LLM BOUNDARY.

    Returns ``(score, strength, reasons)``. Today this is a deterministic
    heuristic that produces mock, evidence-backed ``MatchReason`` objects so the
    frontend has realistic data.

    An LLM integration replaces ONLY this function's body: it would receive the
    candidate profile + job and return the same typed tuple. It must NEVER be
    given authority to override :func:`apply_hard_filters`, and its output stays
    a *recommendation* surfaced to a human — never an automated decision
    (GDPR Art. 22).
    """
    reasons: list[MatchReason] = []
    candidate_skills = {_norm(s) for s in candidate.skills}

    # Skill overlap beyond the must-haves.
    job_skills = {_norm(s) for s in job.must_have_skills}
    overlap = candidate_skills & job_skills
    if overlap:
        reasons.append(
            MatchReason(
                title="Core skills align",
                strength=MatchStrength.STRONG,
                evidence=f"matches {len(overlap)} required skill(s): "
                + ", ".join(sorted(overlap)),
            )
        )

    extra = candidate_skills - job_skills
    if extra:
        reasons.append(
            MatchReason(
                title="Additional relevant skills",
                strength=MatchStrength.MODERATE,
                evidence="also brings: " + ", ".join(sorted(extra)[:5]),
            )
        )

    # Seniority / title signal.
    if candidate.current_title:
        reasons.append(
            MatchReason(
                title="Relevant current role",
                strength=MatchStrength.MODERATE,
                evidence=f"currently {candidate.current_title}"
                + (f" at {candidate.current_company}" if candidate.current_company else ""),
            )
        )

    # Availability signal.
    if candidate.availability_weeks is not None and candidate.availability_weeks <= 8:
        reasons.append(
            MatchReason(
                title="Available soon",
                strength=MatchStrength.MODERATE,
                evidence=f"available in {candidate.availability_weeks} week(s)",
            )
        )

    # Simple transparent score: skill coverage weighted, capped at 1.0.
    coverage = (len(overlap) / len(job_skills)) if job_skills else 0.5
    verification_bonus = 0.2 * candidate.verification_score
    score = min(1.0, round(0.7 * coverage + 0.1 + verification_bonus, 3))

    if score >= 0.75:
        strength = MatchStrength.STRONG
    elif score >= 0.45:
        strength = MatchStrength.MODERATE
    else:
        strength = MatchStrength.WEAK

    if not reasons:
        reasons.append(
            MatchReason(
                title="Baseline eligibility",
                strength=MatchStrength.WEAK,
                evidence="passes hard filters; limited soft signal available",
            )
        )

    return score, strength, reasons


async def match_candidate(
    candidate: Candidate, job: Job
) -> MatchResult:
    """Full pipeline for one candidate<->job pair: hard filters, then soft rank."""
    failures = apply_hard_filters(candidate, job)
    if failures:
        return MatchResult(
            candidate_id=candidate.id,
            job_id=job.id,
            passed_hard_filters=False,
            hard_filter_failures=failures,
            score=0.0,
            strength=MatchStrength.WEAK,
            reasons=[],
            ranker="deterministic-stub",
        )

    score, strength, reasons = rerank_and_explain(candidate, job)
    return MatchResult(
        candidate_id=candidate.id,
        job_id=job.id,
        passed_hard_filters=True,
        hard_filter_failures=[],
        score=score,
        strength=strength,
        reasons=reasons,
        ranker="deterministic-stub",
    )


async def match_job(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    tenant_id: uuid.UUID,
    include_rejected: bool = False,
    persist: bool = False,
) -> list[MatchResult]:
    """Match the tenant's candidate pool against one job, ranked best-first.

    Records an ``ASSERT`` receipt for the matching run (agents/services that
    surface candidates leave a trace in the append-only ledger).
    """
    job = (
        await session.execute(
            select(Job).where(Job.tenant_id == tenant_id, Job.id == job_id)
        )
    ).scalar_one_or_none()
    if job is None:
        return []

    candidates = (
        (
            await session.execute(
                select(Candidate).where(Candidate.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )

    results: list[MatchResult] = []
    for candidate in candidates:
        result = await match_candidate(candidate, job)
        if result.passed_hard_filters or include_rejected:
            results.append(result)

    results.sort(key=lambda r: (r.passed_hard_filters, r.score), reverse=True)

    if persist:
        for result in results:
            session.add(
                MatchReceipt(
                    tenant_id=tenant_id,
                    candidate_id=result.candidate_id,
                    job_id=result.job_id,
                    passed_hard_filters=result.passed_hard_filters,
                    hard_filter_failures=result.hard_filter_failures,
                    score=result.score,
                    strength=result.strength,
                    reasons=[r.model_dump() for r in result.reasons],
                    ranker=result.ranker,
                )
            )

    await verification_service.append_receipt(
        session,
        tenant_id=tenant_id,
        agent="matching_service",
        action=ReceiptAction.ASSERT,
        subject_type="job",
        subject_id=str(job_id),
        verified=True,
        summary=f"matched {len(results)} candidate(s) against job {job.title}",
        payload={
            "candidates_evaluated": len(candidates),
            "surfaced": len(results),
            "persisted": persist,
        },
    )
    await session.commit()
    return results


async def match_pair(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    job_id: uuid.UUID,
) -> MatchResult | None:
    """Match a single specified candidate against a single job."""
    candidate = (
        await session.execute(
            select(Candidate).where(
                Candidate.tenant_id == tenant_id, Candidate.id == candidate_id
            )
        )
    ).scalar_one_or_none()
    job = (
        await session.execute(
            select(Job).where(Job.tenant_id == tenant_id, Job.id == job_id)
        )
    ).scalar_one_or_none()
    if candidate is None or job is None:
        return None
    return await match_candidate(candidate, job)


# Re-exported for convenience / discoverability.
DEFAULT_TENANT = settings.default_tenant_id