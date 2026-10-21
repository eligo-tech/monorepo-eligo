"""The first outbound the system has, and the rules it must not break.

The risk here is not a 500 — it is a letter arriving at a real person's
inbox that should not have gone out, or a record saying somebody was informed
when nothing was sent. Most of what follows is about those two.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal, create_all
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ReceiptAction
from app.domain.notices import service
from app.domain.notices.delivery import factory as delivery_factory
from app.domain.notices.delivery.base import (
    EmailNotConfigured,
    EmailRejected,
    SentMessage,
)
from app.domain.notices.models import CandidateNotice, NoticeStatus
from app.domain.verification.models import Receipt

TENANT = settings.default_tenant_id


def _api() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class _Recorder:
    """A sender that remembers instead of sending."""

    name = "recorder"

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, *, to, subject, text, reply_to=None) -> SentMessage:
        self.sent.append(
            {"to": to, "subject": subject, "text": text, "reply_to": reply_to}
        )
        return SentMessage(provider=self.name, message_id="msg_1")


class _Refuser:
    name = "refuser"

    async def send(self, *, to, subject, text, reply_to=None) -> SentMessage:
        raise EmailRejected("Resend 403: domain eligo-tech.de is not verified")


@pytest.fixture
def recorder(monkeypatch) -> _Recorder:
    sender = _Recorder()
    monkeypatch.setattr(service, "get_email_sender", lambda cfg=None: sender)
    return sender


async def _a_candidate(**kwargs) -> uuid.UUID:
    async with SessionLocal() as session:
        candidate = Candidate(
            tenant_id=TENANT,
            full_name=kwargs.pop("full_name", "Jana Keller"),
            email=kwargs.pop("email", "jana.keller@example.com"),
            **kwargs,
        )
        session.add(candidate)
        await session.commit()
        return candidate.id


async def _notice_row(notice_id) -> CandidateNotice:
    async with SessionLocal() as session:
        return (
            await session.execute(
                select(CandidateNotice).where(CandidateNotice.id == uuid.UUID(notice_id))
            )
        ).scalar_one()


# --- the send path -------------------------------------------------------


async def test_sending_records_what_was_sent_and_leaves_a_receipt(recorder) -> None:
    await create_all()
    candidate_id = await _a_candidate()

    async with _api() as client:
        resp = await client.post(f"{settings.api_v1_prefix}/candidates/{candidate_id}/notices")

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == NoticeStatus.SENT.value
    assert body["email"] == "jana.keller@example.com"

    # One message, to the right person, carrying both links.
    assert len(recorder.sent) == 1
    message = recorder.sent[0]
    assert message["to"] == "jana.keller@example.com"
    assert "/zustimmen" in message["text"] and "/ablehnen" in message["text"]

    # Stored verbatim: the row is the evidence, and a template edited later
    # must not change what the record claims was sent.
    stored = await _notice_row(body["id"])
    assert stored.body == message["text"]
    assert stored.subject == message["subject"]
    assert stored.provider_message_id == "msg_1"

    async with SessionLocal() as session:
        receipt = (
            await session.execute(
                select(Receipt).where(Receipt.subject_id == body["id"])
            )
        ).scalar_one()
    assert receipt.action == ReceiptAction.ASSERT.value
    assert receipt.verified is True


async def test_a_recruiter_cannot_read_the_token_and_answer_for_the_candidate(
    recorder,
) -> None:
    """The body is returned so a recruiter can see what was sent — but it
    carries both opt-in links, and those are the candidate's credential.
    Left in, they are a way to manufacture a consent receipt."""
    await create_all()
    candidate_id = await _a_candidate()

    async with _api() as client:
        created = await client.post(
            f"{settings.api_v1_prefix}/candidates/{candidate_id}/notices"
        )
        listed = await client.get(
            f"{settings.api_v1_prefix}/candidates/{candidate_id}/notices"
        )

    stored = await _notice_row(created.json()["id"])
    for resp in (created, listed):
        assert "token" not in resp.text
        assert stored.token not in resp.text, "the opt-in token reached the recruiter"

    # Redacted, not withheld: the text itself is still there to read.
    assert "Art. 14 DSGVO" in created.json()["body"]
    assert "/zustimmen" in created.json()["body"]
    # And the stored row still holds the real thing — it is the evidence.
    assert stored.token in stored.body


async def test_a_candidate_without_an_email_is_refused(recorder) -> None:
    await create_all()
    candidate_id = await _a_candidate(email=None)

    async with _api() as client:
        resp = await client.post(f"{settings.api_v1_prefix}/candidates/{candidate_id}/notices")

    assert resp.status_code == 409
    assert recorder.sent == []


async def test_nothing_is_sent_and_nothing_recorded_when_email_is_unconfigured(
    monkeypatch,
) -> None:
    """503 with no row — the opposite of marking somebody as informed.

    This is the case the delivery factory refuses to paper over: a fallback
    sender would have written `status='sent'` against a candidate who was
    never told anything.
    """
    await create_all()
    candidate_id = await _a_candidate()

    def _unconfigured(cfg=None):
        raise EmailNotConfigured("no email provider is configured")

    monkeypatch.setattr(service, "get_email_sender", _unconfigured)

    async with _api() as client:
        resp = await client.post(f"{settings.api_v1_prefix}/candidates/{candidate_id}/notices")

    assert resp.status_code == 503
    async with SessionLocal() as session:
        rows = (await session.execute(select(CandidateNotice))).scalars().all()
    assert rows == [], "a notice was recorded although nothing was sent"


async def test_a_provider_refusal_is_recorded_as_failed_not_sent(monkeypatch) -> None:
    await create_all()
    candidate_id = await _a_candidate()
    monkeypatch.setattr(service, "get_email_sender", lambda cfg=None: _Refuser())

    async with _api() as client:
        resp = await client.post(f"{settings.api_v1_prefix}/candidates/{candidate_id}/notices")

    assert resp.status_code == 502
    async with SessionLocal() as session:
        row = (await session.execute(select(CandidateNotice))).scalar_one()
    assert row.status == NoticeStatus.FAILED.value
    assert row.sent_at is None
    assert "not verified" in (row.failure_reason or "")


# --- not sending twice ---------------------------------------------------


async def test_a_second_request_while_one_is_outstanding_is_refused(recorder) -> None:
    await create_all()
    candidate_id = await _a_candidate()

    async with _api() as client:
        first = await client.post(f"{settings.api_v1_prefix}/candidates/{candidate_id}/notices")
        second = await client.post(f"{settings.api_v1_prefix}/candidates/{candidate_id}/notices")

    assert first.status_code == 201
    assert second.status_code == 409
    assert len(recorder.sent) == 1


async def test_somebody_who_said_no_is_never_emailed_again(recorder) -> None:
    """The one refusal that is not about tidiness.

    A person who asked to be removed and is then written to again has been
    ignored, and the second message is the one they complain about.
    """
    await create_all()
    candidate_id = await _a_candidate()

    async with _api() as client:
        first = await client.post(f"{settings.api_v1_prefix}/candidates/{candidate_id}/notices")
        token = (await _notice_row(first.json()["id"])).token
        await client.get(f"{settings.api_v1_prefix}/notices/{TENANT}/{token}/ablehnen")
        again = await client.post(
            f"{settings.api_v1_prefix}/candidates/{candidate_id}/notices"
        )

    assert again.status_code == 409
    assert "widersprochen" in again.json()["detail"]
    assert len(recorder.sent) == 1


# --- the candidate's side ------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [("zustimmen", NoticeStatus.OPTED_IN), ("ablehnen", NoticeStatus.OPTED_OUT)],
)
async def test_the_link_settles_the_notice(recorder, path, expected) -> None:
    await create_all()
    candidate_id = await _a_candidate()

    async with _api() as client:
        created = await client.post(
            f"{settings.api_v1_prefix}/candidates/{candidate_id}/notices"
        )
        token = (await _notice_row(created.json()["id"])).token
        page = await client.get(f"{settings.api_v1_prefix}/notices/{TENANT}/{token}/{path}")

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    row = await _notice_row(created.json()["id"])
    assert row.status == expected.value
    assert row.responded_at is not None


async def test_a_prefetched_second_click_cannot_reverse_the_answer(recorder) -> None:
    """Mail clients follow links. A "no" that a prefetch turns into a "yes"
    puts somebody in the pool against their word."""
    await create_all()
    candidate_id = await _a_candidate()

    async with _api() as client:
        created = await client.post(
            f"{settings.api_v1_prefix}/candidates/{candidate_id}/notices"
        )
        token = (await _notice_row(created.json()["id"])).token
        await client.get(f"{settings.api_v1_prefix}/notices/{TENANT}/{token}/ablehnen")
        second = await client.get(
            f"{settings.api_v1_prefix}/notices/{TENANT}/{token}/zustimmen"
        )

    assert second.status_code == 200
    row = await _notice_row(created.json()["id"])
    assert row.status == NoticeStatus.OPTED_OUT.value


async def test_an_unknown_token_says_nothing_about_why() -> None:
    await create_all()
    async with _api() as client:
        page = await client.get(
            f"{settings.api_v1_prefix}/notices/{TENANT}/not-a-real-token/zustimmen"
        )
    assert page.status_code == 200
    assert "nicht gültig" in page.text


async def test_a_token_from_another_workspace_resolves_to_nothing(recorder) -> None:
    """The token authorises; the workspace in the URL only scopes.

    Pairing a real token with somebody else's workspace id must find no row,
    which is also what keeps the RLS predicate doing real work here.
    """
    await create_all()
    candidate_id = await _a_candidate()

    async with _api() as client:
        created = await client.post(
            f"{settings.api_v1_prefix}/candidates/{candidate_id}/notices"
        )
        token = (await _notice_row(created.json()["id"])).token
        page = await client.get(
            f"{settings.api_v1_prefix}/notices/{uuid.uuid4()}/{token}/zustimmen"
        )

    assert "nicht gültig" in page.text
    row = await _notice_row(created.json()["id"])
    assert row.status == NoticeStatus.SENT.value, "it was settled by the wrong workspace"


# --- the boundary around the public dependency ---------------------------


def test_only_the_opt_in_routes_are_scoped_by_a_url() -> None:
    """`notice_scoped_db` takes the workspace from an unauthenticated URL.

    That is safe for exactly two routes, where a 43-character token decides
    what is reachable. Anywhere else it would be a way to read another
    workspace without a session, so the rule is derived from the app rather
    than written in a comment — the shape `test_operator_endpoints.py` uses.
    """
    from app.domain.notices.router import notice_scoped_db
    from app.main import app

    def walk(router):
        for route in getattr(router, "routes", []):
            if isinstance(route, APIRoute):
                yield route
            else:
                inner = getattr(route, "original_router", None)
                if inner is not None:
                    yield from walk(inner)

    using = {
        route.path
        for route in walk(app)
        if any(
            getattr(d, "call", None) is notice_scoped_db
            for d in route.dependant.dependencies
        )
    }
    assert using == {
        "/notices/{tenant_id}/{token}/zustimmen",
        "/notices/{tenant_id}/{token}/ablehnen",
    }


# --- the provider seam ---------------------------------------------------


def test_an_unconfigured_deployment_refuses_rather_than_pretending() -> None:
    """No fallback sender, on purpose — see `delivery/factory.py`."""
    cfg = settings.model_copy(update={"email_provider": "", "resend_api_key": None})
    assert delivery_factory.email_is_configured(cfg) is False
    with pytest.raises(EmailNotConfigured):
        delivery_factory.get_email_sender(cfg)


def test_resend_needs_both_a_key_and_a_verified_sender() -> None:
    """A key with no From address is the commonest half-configuration, and it
    fails at the provider on every message rather than at startup."""
    key_only = settings.model_copy(
        update={"email_provider": "resend", "resend_api_key": "re_x", "email_from": None}
    )
    assert delivery_factory.email_is_configured(key_only) is False

    complete = settings.model_copy(
        update={
            "email_provider": "resend",
            "resend_api_key": "re_x",
            "email_from": "no-reply@eligo-tech.de",
        }
    )
    assert delivery_factory.email_is_configured(complete) is True
    assert delivery_factory.get_email_sender(complete).name == "resend"


def test_the_notice_says_where_the_data_came_from() -> None:
    """Art. 14(2)(f) asks for the actual origin, not a generic sentence."""
    from app.domain.notices.service import _source_sentence

    named = Candidate(tenant_id=TENANT, full_name="X", external_source="aiFind")
    assert "aiFind" in _source_sentence(named)

    unknown = Candidate(tenant_id=TENANT, full_name="X")
    sentence = _source_sentence(unknown)
    assert "auf Anfrage" in sentence
    assert "aiFind" not in sentence
