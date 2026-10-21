"""Preparing, sending and settling a candidate notice.

The order is deliberate and is the whole safety property: a notice is written
as `pending`, handed to a provider, and only moved to `sent` once the provider
accepted it. Nothing here marks somebody as informed on the strength of having
meant to inform them.

Sending is also never implicit. `backend/CLAUDE.md` §2.4 says nothing is sent
without explicit human approval, and this is the first outbound the system
has: every send traces to a recruiter who asked for it, by name and by Clerk
id, and leaves a receipt in the append-only ledger.
"""

from __future__ import annotations

import datetime as dt
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.core.logging import get_logger
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ReceiptAction
from app.domain.notices import templates
from app.domain.notices.delivery.base import EmailRejected
from app.domain.notices.delivery.factory import get_email_sender
from app.domain.notices.models import SETTLED_STATUSES, CandidateNotice, NoticeStatus
from app.domain.verification import service as verification

logger = get_logger(__name__)


class NoticeRefused(ValueError):
    """The notice must not be created or sent, and why."""


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _source_sentence(candidate: Candidate) -> str:
    """Art. 14(2)(f) wants the actual origin, so say what the record knows.

    `candidates.source` holds the source's own words ("aiFind", "LinkedIn",
    a file name), not a `ConfidenceSource`, so it cannot be mapped to a
    category — it is quoted instead. A candidate with no recorded source gets
    a sentence that says exactly that rather than a confident guess, which is
    the same rule the rest of the product follows about unverifiable claims.
    """
    origin = (candidate.external_source or candidate.source or "").strip()
    if origin:
        return (
            f"Wir haben Ihre Daten aus folgender Quelle erhalten: {origin}. "
            "Gerne nennen wir Ihnen auf Anfrage weitere Einzelheiten."
        )
    return (
        "Ihre Daten stammen nicht aus einer direkten Erhebung bei Ihnen. "
        "Die genaue Quelle nennen wir Ihnen gerne auf Anfrage."
    )


def opt_in_links(tenant_id: uuid.UUID, token: str, cfg: Settings | None = None) -> tuple[str, str]:
    """The two URLs in the email.

    They carry the workspace id as well as the token. The token is what
    authorises — it is 43 random characters and the row is found by it alone —
    but the endpoint is unauthenticated, so there is no session to pin
    Postgres RLS from, and an unpinned query returns zero rows (fail-closed).
    Resolving the workspace from the link keeps RLS switched on for a public
    request instead of reaching for the admin connection, which
    `core/database.py` reserves for DDL and scripts.
    """
    cfg = cfg or settings
    base = cfg.public_base_url.rstrip("/")
    return (
        f"{base}/api/v1/notices/{tenant_id}/{token}/zustimmen",
        f"{base}/api/v1/notices/{tenant_id}/{token}/ablehnen",
    )


async def get_candidate(
    session: AsyncSession, *, tenant_id: uuid.UUID, candidate_id: uuid.UUID
) -> Candidate | None:
    result = await session.execute(
        select(Candidate).where(
            Candidate.id == candidate_id, Candidate.tenant_id == tenant_id
        )
    )
    return result.scalar_one_or_none()


#: What a recruiter sees in place of the token.
REDACTED = "…"


def redacted_body(notice: CandidateNotice) -> str:
    """The notice as sent, with the token taken out.

    The body is stored verbatim because it is the evidence of what the person
    was told — but it contains both opt-in links, and those links are the
    candidate's credential. Handed to a recruiter unchanged, they are a way
    to answer on the candidate's behalf, and the receipt would then read
    "Kandidat:in hat der Speicherung zugestimmt" about a click the candidate
    never made. That is the one claim this whole record exists to make
    truthfully, so the token does not travel to the recruiter-facing API.

    The stored row keeps the real text; only the representation is redacted,
    and the difference is a visible ellipsis rather than a silent edit.
    """
    return notice.body.replace(notice.token, REDACTED)


async def list_for_candidate(
    session: AsyncSession, *, tenant_id: uuid.UUID, candidate_id: uuid.UUID
) -> list[CandidateNotice]:
    result = await session.execute(
        select(CandidateNotice)
        .where(
            CandidateNotice.tenant_id == tenant_id,
            CandidateNotice.candidate_id == candidate_id,
        )
        .order_by(CandidateNotice.created_at.desc())
    )
    return list(result.scalars().all())


async def _latest(
    session: AsyncSession, *, tenant_id: uuid.UUID, candidate_id: uuid.UUID
) -> CandidateNotice | None:
    rows = await list_for_candidate(
        session, tenant_id=tenant_id, candidate_id=candidate_id
    )
    return rows[0] if rows else None


async def prepare(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    candidate: Candidate,
    actor: str,
    actor_user_id: str | None,
    cfg: Settings | None = None,
) -> CandidateNotice:
    """Write the notice that is about to be sent. Nothing leaves here.

    Refuses in three cases, each of which would otherwise be a letter to a
    real person that should not have gone out.
    """
    cfg = cfg or settings
    email = (candidate.email or "").strip()
    if not email:
        raise NoticeRefused(
            "Für diese Kandidatin/diesen Kandidaten ist keine E-Mail-Adresse "
            "hinterlegt."
        )

    previous = await _latest(
        session, tenant_id=tenant_id, candidate_id=candidate.id
    )
    if previous is not None and previous.status == NoticeStatus.OPTED_OUT.value:
        # The one refusal that is not about tidiness. Someone who asked to be
        # removed and is then emailed again has been ignored, and the second
        # message is the one they complain about.
        raise NoticeRefused(
            "Diese Person hat der Speicherung widersprochen. Es darf keine "
            "weitere Anfrage gesendet werden."
        )
    if previous is not None and previous.status == NoticeStatus.SENT.value:
        raise NoticeRefused(
            "Es wurde bereits eine Anfrage gesendet und noch nicht beantwortet."
        )
    if previous is not None and previous.status == NoticeStatus.OPTED_IN.value:
        raise NoticeRefused("Diese Person hat der Speicherung bereits zugestimmt.")

    token = secrets.token_urlsafe(32)
    confirm_url, decline_url = opt_in_links(tenant_id, token, cfg)
    notice = CandidateNotice(
        tenant_id=tenant_id,
        candidate_id=candidate.id,
        email=email,
        token=token,
        status=NoticeStatus.PENDING.value,
        subject=templates.opt_in_subject(cfg.notice_controller_name),
        body=templates.opt_in_body(
            candidate_name=candidate.full_name or "",
            confirm_url=confirm_url,
            decline_url=decline_url,
            source_sentence=_source_sentence(candidate),
            cfg=cfg,
        ),
        requested_by=actor,
        requested_by_user_id=actor_user_id,
    )
    session.add(notice)
    await session.flush()
    return notice


async def send(
    session: AsyncSession,
    *,
    notice: CandidateNotice,
    cfg: Settings | None = None,
) -> CandidateNotice:
    """Hand the prepared notice to the provider and record what happened.

    `EmailNotConfigured` is left to propagate: a deployment that cannot send
    should answer 503 with the notice still `pending`, so the recruiter can
    press the button again once the key is in place. A refusal by the
    provider is different — it happened, it is attributable, and it is
    recorded as `failed` with the provider's own words.
    """
    cfg = cfg or settings
    sender = get_email_sender(cfg)  # raises EmailNotConfigured — see docstring

    try:
        result = await sender.send(
            to=notice.email,
            subject=notice.subject,
            text=notice.body,
            reply_to=cfg.email_reply_to,
        )
    except EmailRejected as exc:
        notice.status = NoticeStatus.FAILED.value
        notice.failure_reason = str(exc)[:500]
        await verification.append_receipt(
            session,
            tenant_id=notice.tenant_id,
            agent="notices",
            action=ReceiptAction.ASSERT,
            subject_type="candidate_notice",
            subject_id=str(notice.id),
            verified=False,
            summary=f"Art.-14-Benachrichtigung an {notice.email} fehlgeschlagen",
            payload={
                "candidate_id": str(notice.candidate_id),
                "actor": notice.requested_by,
                "actor_user_id": notice.requested_by_user_id,
                "error": notice.failure_reason,
            },
        )
        await session.commit()
        return notice

    notice.status = NoticeStatus.SENT.value
    notice.sent_at = _now()
    notice.provider = result.provider
    notice.provider_message_id = result.message_id
    notice.failure_reason = None

    await verification.append_receipt(
        session,
        tenant_id=notice.tenant_id,
        agent="notices",
        action=ReceiptAction.ASSERT,
        subject_type="candidate_notice",
        subject_id=str(notice.id),
        # The provider accepted it. That is what is being attested — not that
        # it was delivered, and not that it was read.
        verified=True,
        summary=f"Art.-14-Benachrichtigung an {notice.email} versandt",
        payload={
            "candidate_id": str(notice.candidate_id),
            "actor": notice.requested_by,
            "actor_user_id": notice.requested_by_user_id,
            "provider": result.provider,
            "provider_message_id": result.message_id,
            "subject": notice.subject,
        },
    )
    await session.commit()
    return notice


async def by_token(
    session: AsyncSession, *, tenant_id: uuid.UUID, token: str
) -> CandidateNotice | None:
    result = await session.execute(
        select(CandidateNotice).where(
            CandidateNotice.tenant_id == tenant_id, CandidateNotice.token == token
        )
    )
    return result.scalar_one_or_none()


async def record_response(
    session: AsyncSession, *, notice: CandidateNotice, opted_in: bool
) -> CandidateNotice:
    """The candidate's own answer. Idempotent, and never reversed by a reload.

    A mail client that prefetches links, a forwarded message, a second click —
    all of these hit this endpoint again. The first answer stands; a later one
    changes nothing and returns the same page, because a person who said no
    and whose link was then prefetched as a yes would be in the pool against
    their word.
    """
    if notice.status in SETTLED_STATUSES:
        return notice

    notice.status = (
        NoticeStatus.OPTED_IN.value if opted_in else NoticeStatus.OPTED_OUT.value
    )
    notice.responded_at = _now()

    await verification.append_receipt(
        session,
        tenant_id=notice.tenant_id,
        agent="notices",
        action=ReceiptAction.WRITE,
        subject_type="candidate_notice",
        subject_id=str(notice.id),
        verified=True,
        summary=(
            "Kandidat:in hat der Speicherung zugestimmt"
            if opted_in
            else "Kandidat:in hat der Speicherung widersprochen"
        ),
        payload={
            "candidate_id": str(notice.candidate_id),
            # The subject acted, not a user of ours. Saying "recruiter" here
            # would misattribute a decision that is the whole point of the
            # record.
            "actor": "candidate (opt-in link)",
            "status": notice.status,
        },
    )
    await session.commit()
    logger.info(
        "candidate notice %s settled as %s", notice.id, notice.status
    )
    return notice
