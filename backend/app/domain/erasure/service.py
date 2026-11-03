"""Erase a person from one workspace, and keep them erased (GDPR Art. 17/21).

One transaction, in this order:

1. Check the name the admin typed matches — the action cannot be undone.
2. Collect every row that refers to the person, and every receipt that
   names the person or one of those rows.
3. Log the request (`erasure_requests`, naming nobody) and write the
   suppression fingerprints the import checks before it creates anyone.
4. Black out those receipts — `verification.erase_receipts` appends one
   ERASE receipt listing them, which is the only licence the trigger accepts.
5. Delete the rows, children first.

The caller commits. Nothing here sends anything anywhere: what reaches a
backup, a corpus copy or an export already made is outside this transaction
and is documented in ARCHITECTURE.md §3, not pretended away.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import uuid
from collections.abc import Iterable

from sqlalchemy import Text, cast, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.candidates.models import Candidate
from app.domain.documents.models import CandidateDocument
from app.domain.erasure.models import ErasureRequest, TenantSuppression
from app.domain.interviews.models import Interview
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager, ManagerInteraction
from app.domain.matching.models import MatchReceipt
from app.domain.notices.models import CandidateNotice
from app.domain.pipeline.models import Application, ApplicationAssessment, ProcessStep
from app.domain.proposals.models import AgentProposal
from app.domain.verification import service as verification
from app.domain.verification.models import BLACKOUT_SUMMARY, EnrichmentRecord, Receipt

REASONS = ("erasure", "objection")


class NotConfigured(RuntimeError):
    """ELIGO_SUPPRESSION_KEY is unset: an erasure could not stop the next import."""


class NotFound(LookupError):
    pass


class NameMismatch(ValueError):
    pass


# --- fingerprints --------------------------------------------------------------


def _key() -> bytes:
    if not settings.suppression_key:
        raise NotConfigured("ELIGO_SUPPRESSION_KEY is not set")
    return settings.suppression_key.encode()


def _normalise(kind: str, value: str) -> str:
    value = value.strip()
    return value.lower() if kind == "email" else value


def digest(tenant_id: uuid.UUID, kind: str, value: str) -> str:
    """HMAC-SHA256 of tenant:kind:value. Per workspace, so the same address in
    two workspaces gives two unrelated fingerprints."""
    material = f"{tenant_id}:{kind}:{_normalise(kind, value)}".encode()
    return hmac.new(_key(), material, hashlib.sha256).hexdigest()


def _import_ids(source: str | None, external_id: str | None, merged: Iterable[str] = ()) -> list[str]:
    ids = [f"{source}:{external_id}"] if source and external_id else []
    return ids + [m for m in merged if m]


def _keys(tenant_id: uuid.UUID, *, email: str | None, import_ids: list[str]) -> list[tuple[str, str]]:
    keys = [("import_id", digest(tenant_id, "import_id", i)) for i in import_ids]
    if email and email.strip():
        keys.append(("email", digest(tenant_id, "email", email)))
    return keys


def _same_name(typed: str, actual: str | None) -> bool:
    fold = lambda v: " ".join((v or "").split()).casefold()  # noqa: E731
    return bool(actual) and fold(typed) == fold(actual)


# --- the erasure ---------------------------------------------------------------


async def _receipts_naming(session: AsyncSession, tenant_id: uuid.UUID, ids: set[str]) -> list[uuid.UUID]:
    """Receipts about the person or one of their rows: by subject, or because
    the payload mentions one of the ids (old notice receipts, proposals …)."""
    if not ids:
        return []
    rows = await session.execute(
        select(Receipt.id).where(
            Receipt.tenant_id == tenant_id,
            Receipt.summary != BLACKOUT_SUMMARY,
            Receipt.action != "erase",
            or_(
                Receipt.subject_id.in_(ids),
                *[cast(Receipt.payload, Text).contains(i) for i in ids],
            ),
        )
    )
    return [r for (r,) in rows.all()]


async def _proposals_naming(session: AsyncSession, tenant_id: uuid.UUID, ids: set[str]) -> list[uuid.UUID]:
    if not ids:
        return []
    rows = await session.execute(
        select(AgentProposal.id).where(
            AgentProposal.tenant_id == tenant_id,
            or_(
                *[cast(AgentProposal.args, Text).contains(i) for i in ids],
                *[cast(AgentProposal.snapshot, Text).contains(i) for i in ids],
            ),
        )
    )
    return [r for (r,) in rows.all()]


async def _ids(session: AsyncSession, column, *where) -> list[uuid.UUID]:  # noqa: ANN001
    return [r for (r,) in (await session.execute(select(column).where(*where))).all()]


async def _finish(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    subject_type: str,
    reason: str,
    requested_on: dt.date,
    actor_user_id: str | None,
    actor_name: str | None,
    keys: list[tuple[str, str]],
    receipt_ids: list[uuid.UUID],
    deletions: list[tuple[type, list[uuid.UUID]]],
) -> ErasureRequest:
    if reason not in REASONS:
        raise ValueError(f"reason must be one of {REASONS}")
    # The log row is written ONCE, at the end, already pointing at its ERASE
    # receipt: the app role may only insert into `erasure_requests`, never
    # change or delete a row, so the log cannot be rewritten after the fact
    # and `verify_chain` can trust it as the licence's backing.
    request_id = uuid.uuid4()
    erase = await verification.erase_receipts(
        session, tenant_id=tenant_id, receipt_ids=receipt_ids, request_id=request_id,
        subject_type=subject_type, actor_user_id=actor_user_id, actor_name=actor_name,
    )
    counts: dict[str, int] = {
        "receipts_blacked_out": len((erase.payload or {}).get("redacted", {})),
        # Zero means nothing can stop this person coming back: no e-mail and
        # no import id to fingerprint. The caller must say so.
        "suppressions_written": len(keys),
    }
    for model, ids in deletions:
        if ids:
            await session.execute(
                delete(model)
                .where(model.tenant_id == tenant_id, model.id.in_(ids))
                .execution_options(synchronize_session=False)
            )
        counts[model.__tablename__] = counts.get(model.__tablename__, 0) + len(ids)
    request = ErasureRequest(
        id=request_id, tenant_id=tenant_id, subject_type=subject_type, reason=reason,
        requested_on=requested_on, executed_by_user_id=actor_user_id,
        executed_by_name=actor_name, counts=counts, erase_receipt_id=erase.id,
    )
    session.add(request)
    session.add_all(
        TenantSuppression(tenant_id=tenant_id, request_id=request_id, kind=k, digest=d)
        for k, d in keys
    )
    await session.flush()
    # Bulk deletes bypassed the identity map; drop what it still holds about
    # the person, then reload the one object handed back.
    session.expire_all()
    await session.refresh(request)
    return request


async def erase_candidate(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    confirm_name: str,
    reason: str,
    requested_on: dt.date,
    actor_user_id: str | None,
    actor_name: str | None,
) -> ErasureRequest:
    _key()  # refuse before touching anything
    cand = (
        await session.execute(
            select(Candidate).where(Candidate.tenant_id == tenant_id, Candidate.id == candidate_id)
        )
    ).scalar_one_or_none()
    if cand is None:
        raise NotFound("candidate")
    if not _same_name(confirm_name, cand.full_name):
        raise NameMismatch("the name does not match")

    t = tenant_id
    applications = await _ids(session, Application.id, Application.tenant_id == t, Application.candidate_id == cand.id)
    steps = await _ids(session, ProcessStep.id, ProcessStep.tenant_id == t, ProcessStep.application_id.in_(applications))
    assessments = await _ids(
        session, ApplicationAssessment.id, ApplicationAssessment.tenant_id == t,
        ApplicationAssessment.application_id.in_(applications),
    )
    per_candidate = {
        model: await _ids(session, model.id, model.tenant_id == t, model.candidate_id == cand.id)
        for model in (MatchReceipt, CandidateDocument, CandidateNotice, ManagerInteraction, Interview)
    }
    linked = {str(cand.id), *map(str, applications), *map(str, steps), *map(str, assessments)}
    for ids in per_candidate.values():
        linked |= set(map(str, ids))
    records = await _ids(
        session, EnrichmentRecord.id, EnrichmentRecord.tenant_id == t,
        EnrichmentRecord.entity_id.in_([uuid.UUID(i) for i in linked]),
    )
    linked |= set(map(str, records))
    proposals = await _proposals_naming(session, t, linked)
    receipts = await _receipts_naming(session, t, linked)

    return await _finish(
        session, tenant_id=t, subject_type="candidate", reason=reason,
        requested_on=requested_on, actor_user_id=actor_user_id, actor_name=actor_name,
        keys=_keys(t, email=cand.email, import_ids=_import_ids(
            cand.external_source, cand.external_id, cand.merged_identities or [])),
        receipt_ids=receipts,
        deletions=[
            (ProcessStep, steps), (ApplicationAssessment, assessments), (Application, applications),
            *per_candidate.items(), (EnrichmentRecord, records), (AgentProposal, proposals),
            (Candidate, [cand.id]),
        ],
    )


async def erase_manager(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    manager_id: uuid.UUID,
    confirm_name: str,
    reason: str,
    requested_on: dt.date,
    actor_user_id: str | None,
    actor_name: str | None,
) -> ErasureRequest:
    """A client contact. Their mandates stay — they belong to the client
    company — and lose the link to the person."""
    _key()
    boss = (
        await session.execute(
            select(Manager).where(Manager.tenant_id == tenant_id, Manager.id == manager_id)
        )
    ).scalar_one_or_none()
    if boss is None:
        raise NotFound("manager")
    if not _same_name(confirm_name, boss.full_name):
        raise NameMismatch("the name does not match")

    t = tenant_id
    notes = await _ids(session, ManagerInteraction.id, ManagerInteraction.tenant_id == t,
                       ManagerInteraction.manager_id == boss.id)
    linked = {str(boss.id), *map(str, notes)}
    records = await _ids(session, EnrichmentRecord.id, EnrichmentRecord.tenant_id == t,
                         EnrichmentRecord.entity_id.in_([boss.id, *notes]))
    linked |= set(map(str, records))
    proposals = await _proposals_naming(session, t, linked)
    receipts = await _receipts_naming(session, t, linked)
    await session.execute(
        update(Job).where(Job.tenant_id == t, Job.manager_id == boss.id).values(manager_id=None)
        .execution_options(synchronize_session=False)
    )
    return await _finish(
        session, tenant_id=t, subject_type="manager", reason=reason,
        requested_on=requested_on, actor_user_id=actor_user_id, actor_name=actor_name,
        keys=_keys(t, email=boss.email, import_ids=_import_ids(boss.external_source, boss.external_id)),
        receipt_ids=receipts,
        deletions=[(ManagerInteraction, notes), (EnrichmentRecord, records),
                   (AgentProposal, proposals), (Manager, [boss.id])],
    )


# --- the import precondition -----------------------------------------------


class ImportGuard:
    """Answers "was this person erased here?" for one import run.

    Loaded once per run. A workspace with no suppressions needs no key and
    pays nothing. A workspace WITH suppressions and no key refuses to import
    at all: "could not check" must not become "let them back in".
    """

    def __init__(self, tenant_id: uuid.UUID, digests: set[str]) -> None:
        self._tenant = tenant_id
        self._digests = digests

    def blocks(self, *, source: str, external_id: str | None, email: str | None) -> bool:
        if not self._digests:
            return False
        keys = _keys(self._tenant, email=email, import_ids=_import_ids(source, external_id))
        return any(d in self._digests for _, d in keys)


async def active_digests(session: AsyncSession, tenant_id: uuid.UUID) -> set[str]:
    rows = await session.execute(
        select(TenantSuppression.digest).where(
            TenantSuppression.tenant_id == tenant_id, TenantSuppression.lifted_at.is_(None)
        )
    )
    return {d for (d,) in rows.all()}


async def import_guard(session: AsyncSession, tenant_id: uuid.UUID) -> ImportGuard:
    digests = await active_digests(session, tenant_id)
    if digests:
        _key()  # raises NotConfigured
    return ImportGuard(tenant_id, digests)


# --- a person added again by hand -------------------------------------------


class Suppressed(Exception):
    """The address belongs to someone this workspace erased. Carries the date
    they asked — never the address."""

    def __init__(self, requested_on: dt.date) -> None:
        super().__init__(f"erased on request of {requested_on.isoformat()}")
        self.requested_on = requested_on


async def guard_readd(
    session: AsyncSession, *, tenant_id: uuid.UUID, email: str | None, override: bool
) -> bool:
    """Refuse to create, by hand, a person this workspace erased — unless the
    recruiter confirms they came back of their own accord.

    Confirming lifts ONLY the e-mail fingerprint, and logs who lifted it. The
    import-id fingerprints stay: the old ATS record is the data the person
    asked to have deleted, and a re-application does not bring that back.
    Returns True when a suppression was lifted.
    """
    rows = await _active_email_rows(session, tenant_id, email)
    if not rows:
        return False
    if not override:
        raise Suppressed(max(on for _, on in rows))
    from app.core.context import current_actor_var

    actor = current_actor_var.get()
    now = dt.datetime.now(dt.UTC)
    for row, _ in rows:
        row.lifted_at = now
        row.lifted_by_user_id = getattr(actor, "user_id", None)
        row.lifted_by_name = getattr(actor, "name", None)
    await session.flush()
    return True


async def suppressed_on(
    session: AsyncSession, *, tenant_id: uuid.UUID, email: str | None
) -> dt.date | None:
    """The day this address's owner asked to be erased here, or None. For a
    preview that must ask BEFORE anything is written; never raises."""
    try:
        rows = await _active_email_rows(session, tenant_id, email)
    except NotConfigured:
        return None  # the save itself will say so (503)
    return max(on for _, on in rows) if rows else None


async def _active_email_rows(session: AsyncSession, tenant_id: uuid.UUID, email: str | None) -> list:
    if not email or not email.strip():
        return []
    if not await active_digests(session, tenant_id):
        return []  # nothing erased here: no key needed, nothing to check
    key = digest(tenant_id, "email", email)
    return (
        await session.execute(
            select(TenantSuppression, ErasureRequest.requested_on)
            .join(ErasureRequest, ErasureRequest.id == TenantSuppression.request_id)
            .where(
                TenantSuppression.tenant_id == tenant_id,
                TenantSuppression.kind == "email",
                TenantSuppression.digest == key,
                TenantSuppression.lifted_at.is_(None),
            )
        )
    ).all()
