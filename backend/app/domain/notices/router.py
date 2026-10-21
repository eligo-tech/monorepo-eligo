"""HTTP surface for candidate notices.

Two audiences, and they authenticate differently.

* A **recruiter** prepares and sends, under the normal session. Sending is an
  explicit act by a named person (`backend/CLAUDE.md` §2.4) — there is no
  trigger on candidate creation and no batch job.
* A **candidate** answers, with no account and no session. Those two routes
  are declared in `tests/test_no_open_endpoints.py`; the 43-character token
  in the link is the credential, and the workspace id beside it is what lets
  Postgres RLS stay switched on for a request that has no session to pin it
  from.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor
from app.core.config import settings
from app.core.database import SessionLocal, current_tenant_var, get_db
from app.domain.notices import service
from app.domain.notices.delivery.base import EmailNotConfigured
from app.domain.notices.delivery.factory import email_is_configured
from app.domain.notices.models import NoticeStatus
from app.domain.notices.schemas import NoticeCapability, NoticeRead

router = APIRouter(tags=["notices"])


async def notice_scoped_db(tenant_id: uuid.UUID) -> AsyncGenerator[AsyncSession, None]:
    """A session pinned to the workspace named in a public opt-in link.

    **Only the two public notice routes may use this**, and
    `tests/test_notices.py::test_only_the_opt_in_routes_are_scoped_by_a_url`
    fails if anything else does — the same way `test_operator_endpoints.py`
    derives its route set rather than trusting a comment.

    Why it exists: the candidate has no session, so nothing sets
    `app.current_tenant`, and an unpinned query on Postgres returns zero rows.
    The alternative was the admin connection, which `core/database.py`
    reserves for DDL and scripts because it bypasses RLS entirely. Taking the
    workspace from the URL keeps the policy enforced; the token is still what
    authorises, and a token that does not belong to the named workspace finds
    nothing.
    """
    current_tenant_var.set(str(tenant_id))
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def _read(notice) -> NoticeRead:
    """Serialise one notice for a recruiter, with the token redacted out of
    the body — see `service.redacted_body` on why that is not cosmetic."""
    read = NoticeRead.model_validate(notice)
    return read.model_copy(update={"body": service.redacted_body(notice)})


# --- recruiter side ------------------------------------------------------


@router.get("/notices/capability", response_model=NoticeCapability)
async def capability(_: Actor = Depends(get_current_actor)) -> NoticeCapability:
    """Can this deployment send? Read by the UI before offering the button."""
    return NoticeCapability(
        configured=email_is_configured(),
        provider=settings.email_provider or "",
        sender=settings.email_from,
    )


@router.get(
    "/candidates/{candidate_id}/notices", response_model=list[NoticeRead]
)
async def list_notices(
    candidate_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[NoticeRead]:
    rows = await service.list_for_candidate(
        db, tenant_id=actor.tenant_id, candidate_id=candidate_id
    )
    return [_read(row) for row in rows]


@router.post(
    "/candidates/{candidate_id}/notices",
    response_model=NoticeRead,
    status_code=status.HTTP_201_CREATED,
)
async def send_notice(
    candidate_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> NoticeRead:
    """Send one candidate the Art. 14 notice and the opt-in question.

    One candidate per call, by a named person. A "send to everyone" button is
    deliberately absent: 500 letters leaving on one click is not a thing to
    build before the first one has been read by a human.
    """
    candidate = await service.get_candidate(
        db, tenant_id=actor.tenant_id, candidate_id=candidate_id
    )
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "candidate not found")

    try:
        notice = await service.prepare(
            db,
            tenant_id=actor.tenant_id,
            candidate=candidate,
            actor=actor.name,
            actor_user_id=actor.user_id,
        )
    except service.NoticeRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    try:
        notice = await service.send(db, notice=notice)
    except EmailNotConfigured as exc:
        # The notice stays `pending` and uncommitted — the recruiter can press
        # the button again once a key is configured, and nothing in the record
        # claims this person was told anything.
        await db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    if notice.status == NoticeStatus.FAILED.value:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Der E-Mail-Dienst hat die Nachricht abgelehnt: {notice.failure_reason}",
        )
    return _read(notice)


# --- candidate side: no account, no session ------------------------------


def _page(title: str, message: str) -> HTMLResponse:
    """The page a candidate lands on. Self-contained — it is opened from an
    email client, often on a phone, and must not depend on the app loading."""
    return HTMLResponse(
        f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{title}</title>
<style>
 body{{margin:0;min-height:100vh;display:flex;align-items:center;
      justify-content:center;background:#0d0d0f;color:#e8e8ea;
      font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
      padding:24px}}
 .card{{max-width:32rem;border:1px solid #26262b;border-radius:12px;
       background:#141417;padding:32px}}
 h1{{font-size:19px;margin:0 0 12px}}
 p{{margin:0;color:#a8a8b0}}
</style></head>
<body><div class="card"><h1>{title}</h1><p>{message}</p></div></body></html>""",
        status_code=200,
    )


async def _settle(
    tenant_id: uuid.UUID, token: str, db: AsyncSession, *, opted_in: bool
) -> HTMLResponse:
    notice = await service.by_token(db, tenant_id=tenant_id, token=token)
    if notice is None:
        # Same answer for a wrong token and an unknown workspace. Which of
        # the two it was is not a candidate's question, and telling a stranger
        # that a token is "valid but for another workspace" is a free oracle.
        return _page(
            "Link nicht gültig",
            "Dieser Link ist abgelaufen oder nicht mehr gültig. "
            "Bitte antworten Sie direkt auf unsere E-Mail.",
        )

    already = notice.status in {
        NoticeStatus.OPTED_IN.value,
        NoticeStatus.OPTED_OUT.value,
    }
    notice = await service.record_response(db, notice=notice, opted_in=opted_in)

    if notice.status == NoticeStatus.OPTED_IN.value:
        return _page(
            "Danke — wir haben Sie aufgenommen" if not already else "Bereits bestätigt",
            "Ihre Daten bleiben in unserem Bewerberpool. Sie können dem "
            "jederzeit widersprechen — eine kurze E-Mail genügt.",
        )
    return _page(
        "Danke — wir haben Sie entfernt" if not already else "Bereits widersprochen",
        "Wir löschen Ihre Daten aus unserem Bewerberpool und melden uns "
        "nicht wieder.",
    )


@router.get("/notices/{tenant_id}/{token}/zustimmen", response_class=HTMLResponse)
async def opt_in(
    tenant_id: uuid.UUID,
    token: str,
    db: AsyncSession = Depends(notice_scoped_db),
) -> HTMLResponse:
    return await _settle(tenant_id, token, db, opted_in=True)


@router.get("/notices/{tenant_id}/{token}/ablehnen", response_class=HTMLResponse)
async def opt_out(
    tenant_id: uuid.UUID,
    token: str,
    db: AsyncSession = Depends(notice_scoped_db),
) -> HTMLResponse:
    return await _settle(tenant_id, token, db, opted_in=False)
