""""Nicht mehr kontaktieren" — and the confirmation to the person (ELI-32).

The lighter sibling of an erasure, for the person who says on a call "please
do not contact me again" (GDPR Art. 21 in spirit; Art. 17 is the erase
dialog). The record stays; `do_not_contact_at` takes them off the call list,
the Wiedervorlage and Markt, refuses an Art. 14 notice, and shows as a red
mark on their card — until a person undoes it.

Every change is a person's act, never an agent's: it happens from a note a
recruiter saves, from the undo button, or from the candidate's own "Nein"
in the opt-in mail. Each one appends a receipt that names ids and a code —
never an address, never the note's words (backend/CLAUDE.md §2.1).

The confirmation mail goes through the Art. 14 notice's sender
(`notices.delivery`), so it leaves from the same address. It is sent on a
click only. For an erasure the address is read BEFORE the person is wiped,
held in memory for the one request, and named nowhere afterwards: the
receipt points at the erasure request, not at the person.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.core.logging import get_logger
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ReceiptAction
from app.domain.managers.models import Manager
from app.domain.notices.delivery.base import EmailNotConfigured, EmailRejected
from app.domain.notices.delivery.factory import email_is_configured, get_email_sender
from app.domain.verification import service as verification

logger = get_logger(__name__)

Subject = Literal["manager", "candidate"]
#: Why the mark is set — a code, so a receipt never quotes the person.
REASONS = ("requested", "opt_out_link")
#: What became of a confirmation the erasure was asked to send.
Confirmation = Literal["sent", "failed", "not_configured", "no_email"]

_MODELS: dict[str, type] = {"manager": Manager, "candidate": Candidate}


class NotMarked(ValueError):
    """A confirmation for someone not marked do-not-contact."""


class NoAddress(ValueError):
    """Nobody to confirm to: the record holds no e-mail address."""


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def get_person(
    session: AsyncSession, *, tenant_id: uuid.UUID, subject: Subject, person_id: uuid.UUID
) -> Manager | Candidate | None:
    model = _MODELS[subject]
    return await session.scalar(select(model).where(model.tenant_id == tenant_id, model.id == person_id))


async def mark(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    subject: Subject,
    person: Manager | Candidate,
    reason: str = "requested",
    interaction_id: uuid.UUID | None = None,
    agent: str = "recruiter",
    actor: str | None = None,
) -> None:
    """Set the mark and append its receipt. The caller commits.

    Marking someone already marked keeps the first date — the day they first
    asked is the one that counts — and appends no second receipt.
    """
    if reason not in REASONS:
        raise ValueError(f"reason must be one of {REASONS}")
    if person.do_not_contact_at is not None:
        return
    person.do_not_contact_at = _now()
    person.do_not_contact_reason = reason
    payload: dict[str, object] = {"reason": reason}
    if interaction_id is not None:
        payload["interaction_id"] = str(interaction_id)
    if actor is not None:
        # Only when the subject acted (the opt-in link): a recruiter is the
        # receipt's own actor, taken from the request.
        payload["actor"] = actor
    await verification.append_receipt(
        session, tenant_id=tenant_id, agent=agent,
        action=ReceiptAction.WRITE, subject_type=subject, subject_id=str(person.id), verified=True,
        summary="Nicht mehr kontaktieren vermerkt", payload=payload,
    )


async def lift(
    session: AsyncSession, *, tenant_id: uuid.UUID, subject: Subject, person: Manager | Candidate
) -> None:
    """"Wieder kontaktierbar". The caller commits."""
    if person.do_not_contact_at is None:
        return
    person.do_not_contact_at = None
    person.do_not_contact_reason = None
    await verification.append_receipt(
        session, tenant_id=tenant_id, agent="recruiter", action=ReceiptAction.WRITE,
        subject_type=subject, subject_id=str(person.id), verified=True,
        summary="Wieder kontaktierbar", payload={},
    )


# --- the confirmation mail ------------------------------------------------


def _greeting(name: str | None) -> str:
    return f"Guten Tag {name}," if name else "Guten Tag,"


def confirmation_text(kind: Literal["do_not_contact", "erased"], name: str | None,
                      cfg: Settings | None = None) -> tuple[str, str]:
    """(subject, body). Short, German, plain text like the Art. 14 notice.

    ⚠️ Not reviewed by a lawyer, like `notices/templates.py`. It states only
    what the code did: the mark, or the erasure in this workspace.
    """
    cfg = cfg or settings
    controller = cfg.notice_controller_name
    contact = cfg.notice_contact_email or cfg.email_reply_to or cfg.email_from or ""
    if kind == "erased":
        subject = f"Ihre Daten bei {controller} wurden gelöscht"
        middle = (
            "wie von Ihnen gewünscht haben wir Ihre personenbezogenen Daten in unserem\n"
            "System gelöscht. Damit Sie nicht erneut aufgenommen werden, behalten wir\n"
            "nur einen verschlüsselten Vermerk, der Ihre Daten nicht enthält."
        )
    else:
        subject = f"Wir werden Sie nicht mehr kontaktieren — {controller}"
        middle = (
            "wie besprochen werden wir Sie nicht mehr kontaktieren. Wenn Sie darüber\n"
            "hinaus möchten, dass wir Ihre Daten löschen, genügt eine kurze Nachricht."
        )
    body = f"""{_greeting(name)}

{middle}

Bei Fragen erreichen Sie uns unter {contact}.

Freundliche Grüße
{controller}
"""
    return subject, body


async def _send(to: str, subject: str, body: str, cfg: Settings):
    sender = get_email_sender(cfg)  # raises EmailNotConfigured
    return await sender.send(to=to, subject=subject, text=body, reply_to=cfg.email_reply_to)


async def send_do_not_contact_confirmation(
    session: AsyncSession, *, tenant_id: uuid.UUID, subject: Subject, person: Manager | Candidate,
    cfg: Settings | None = None,
) -> None:
    """"Bestätigung senden" for a marked person. Raises `NotMarked`,
    `NoAddress`, `EmailNotConfigured` (nothing recorded) or `EmailRejected`
    (recorded as failed). Commits its receipt."""
    cfg = cfg or settings
    if person.do_not_contact_at is None:
        raise NotMarked("not marked do-not-contact")
    email = (person.email or "").strip()
    if not email:
        raise NoAddress("no e-mail address")
    mail_subject, body = confirmation_text("do_not_contact", person.full_name, cfg)
    try:
        sent = await _send(email, mail_subject, body, cfg)
    except EmailRejected:
        await verification.append_receipt(
            session, tenant_id=tenant_id, agent="recruiter", action=ReceiptAction.ASSERT,
            subject_type=subject, subject_id=str(person.id), verified=False,
            summary="Bestätigung „Nicht mehr kontaktieren“ fehlgeschlagen", payload={},
        )
        await session.commit()
        raise
    await verification.append_receipt(
        session, tenant_id=tenant_id, agent="recruiter", action=ReceiptAction.ASSERT,
        subject_type=subject, subject_id=str(person.id), verified=True,
        summary="Bestätigung „Nicht mehr kontaktieren“ versandt",
        payload={"provider": sent.provider, "provider_message_id": sent.message_id},
    )
    await session.commit()


async def send_erasure_confirmation(
    session: AsyncSession, *, tenant_id: uuid.UUID, request_id: uuid.UUID,
    email: str | None, name: str | None, cfg: Settings | None = None,
) -> Confirmation:
    """After an erasure has been COMMITTED: the confirmation to the address
    read before it. Never raises — the erasure is done whatever the mail
    does, and the answer says which. The receipt names the erasure request;
    the person it was about no longer exists here."""
    cfg = cfg or settings
    to = (email or "").strip()
    if not to:
        return "no_email"
    if not email_is_configured(cfg):
        return "not_configured"
    mail_subject, body = confirmation_text("erased", name, cfg)
    try:
        sent = await _send(to, mail_subject, body, cfg)
    except EmailNotConfigured:
        return "not_configured"
    except EmailRejected as exc:
        logger.warning("erasure confirmation refused by the provider (%s)", type(exc).__name__)
        status: Confirmation = "failed"
        payload: dict[str, object] = {}
    else:
        status = "sent"
        payload = {"provider": sent.provider, "provider_message_id": sent.message_id}
    await verification.append_receipt(
        session, tenant_id=tenant_id, agent="recruiter", action=ReceiptAction.ASSERT,
        subject_type="erasure_request", subject_id=str(request_id), verified=status == "sent",
        summary="Bestätigung der Löschung versandt" if status == "sent" else "Bestätigung der Löschung fehlgeschlagen",
        payload=payload,
    )
    await session.commit()
    return status
