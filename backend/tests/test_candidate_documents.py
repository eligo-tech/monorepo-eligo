"""Attachments: a candidate's files, and what each one IS.

`data/examples/metadata_quailfication.txt` asks for two things the store could
not hold: the Zeugnisse and Zertifikate, and the Gesprächstranskript the
post-interview data is read from. Both are "a file on a candidate", and the
table had no way to tell them apart from the CV — which matters the moment
something asks for *the CV*.

The transcript tests pin the deliberate asymmetry with the CV path: a CV
creates a record, a transcript only PROPOSES changes to one that exists.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import SessionLocal
from app.domain.candidates.models import Candidate
from app.domain.common.enums import DocumentKind
from app.domain.documents import service
from app.domain.documents.models import CandidateDocument

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.uuid4()
API = "/api/v1/documents"


@pytest.fixture
async def candidate() -> uuid.UUID:
    async with SessionLocal() as s:
        row = Candidate(tenant_id=TENANT, full_name="Beispiel Kandidat")
        s.add(row)
        await s.commit()
        return row.id


async def _stamp(session, doc_id: uuid.UUID, minutes: int) -> None:
    """Give a stored file an explicit upload time.

    SQLite's `CURRENT_TIMESTAMP` has second resolution, so two files written
    in the same test tick share a timestamp and "newest first" has nothing to
    sort on. Postgres does not have that problem; the test must not depend on
    which backend it runs against.
    """
    row = await session.get(CandidateDocument, doc_id)
    row.created_at = dt.datetime(2026, 9, 18, 10, minutes, tzinfo=dt.UTC)
    await session.commit()


async def test_the_cv_is_still_the_cv_after_a_zeugnis_arrives(candidate) -> None:
    """THE regression this column exists for.

    `get_latest_document` meant "the newest file", which was the CV only while
    CVs were all there was. `/candidates/{id}/cv` reads it, so the first
    Zeugnis uploaded would have been served to the client as the CV.
    """
    async with SessionLocal() as s:
        cv_doc = await service.store_document(
            s,
            tenant_id=TENANT,
            candidate_id=candidate,
            filename="lebenslauf.pdf",
            content=b"%PDF-cv",
            kind=DocumentKind.CV.value,
        )
        await _stamp(s, cv_doc.id, 0)
        zeugnis = await service.store_document(
            s,
            tenant_id=TENANT,
            candidate_id=candidate,
            filename="zeugnis-2021.pdf",
            content=b"%PDF-zeugnis",
            kind=DocumentKind.ZEUGNIS.value,
        )
        await _stamp(s, zeugnis.id, 5)
        cv = await service.get_latest_document(
            s, tenant_id=TENANT, candidate_id=candidate
        )
        newest = await service.get_latest_document(
            s, tenant_id=TENANT, candidate_id=candidate, kind=None
        )

    assert cv is not None and cv.filename == "lebenslauf.pdf"
    assert newest is not None and newest.filename == "zeugnis-2021.pdf"


async def test_a_file_stored_before_kinds_existed_reads_as_a_cv(candidate) -> None:
    """The default is a fact, not an assumption: nothing but a CV could be
    uploaded before this column, so the backfill cannot be wrong."""
    async with SessionLocal() as s:
        doc = await service.store_document(
            s,
            tenant_id=TENANT,
            candidate_id=candidate,
            filename="alt.pdf",
            content=b"%PDF",
        )
    assert doc.kind == DocumentKind.CV.value


async def test_documents_are_listed_newest_first_and_stay_in_their_tenant(
    candidate,
) -> None:
    async with SessionLocal() as s:
        for minute, (name, kind) in enumerate(
            (
                ("lebenslauf.pdf", DocumentKind.CV),
                ("zertifikat.pdf", DocumentKind.ZERTIFIKAT),
                ("transkript.txt", DocumentKind.TRANSKRIPT),
            )
        ):
            doc = await service.store_document(
                s,
                tenant_id=TENANT,
                candidate_id=candidate,
                filename=name,
                content=b"x",
                kind=kind.value,
            )
            await _stamp(s, doc.id, minute)
        mine = await service.list_documents(
            s, tenant_id=TENANT, candidate_id=candidate
        )
        theirs = await service.list_documents(
            s, tenant_id=OTHER, candidate_id=candidate
        )

    assert [d.filename for d in mine][0] == "transkript.txt"
    assert len(mine) == 3
    assert theirs == []


async def test_routes_upload_list_and_download(candidate) -> None:
    from app.main import app as fastapi_app

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://t"
    ) as client:
        created = await client.post(
            f"{API}/upload",
            data={"candidate_id": str(candidate), "kind": "zeugnis"},
            files={"file": ("zeugnis.pdf", b"%PDF-1.4 zeugnis", "application/pdf")},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["kind"] == "zeugnis" and body["byte_size"] == 16
        # Metadata only — the bytes must not ride along in the list.
        assert "content" not in body

        listed = (await client.get(f"{API}/candidate/{candidate}")).json()
        assert [d["filename"] for d in listed] == ["zeugnis.pdf"]

        content = await client.get(f"{API}/{body['id']}/content")
        assert content.status_code == 200
        assert content.content == b"%PDF-1.4 zeugnis"

        missing = await client.get(f"{API}/{uuid.uuid4()}/content")
        assert missing.status_code == 404


async def test_an_unsupported_type_is_refused(candidate) -> None:
    from app.main import app as fastapi_app

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://t"
    ) as client:
        refused = await client.post(
            f"{API}/upload",
            data={"candidate_id": str(candidate), "kind": "sonstiges"},
            files={"file": ("tabelle.xlsx", b"PK\x03\x04", "application/vnd.ms-excel")},
        )
    assert refused.status_code == 415


# ---------------------------------------------------------------------------
# The Gesprächstranskript
# ---------------------------------------------------------------------------

TRANSCRIPT = (
    "Recruiter: Wie ist Ihre Kündigungsfrist?\n"
    "Kandidat: Drei Monate zum Monatsende.\n"
    "Recruiter: Und das Gehalt?\n"
    "Kandidat: Aktuell über 105.000. Minimum 92.000, wünschen würde ich mir 100.000.\n"
)


class _Reader:
    """A provider that can read transcripts, with a confidence we control."""

    name = "stub"

    def __init__(self, confidence: float = 0.9) -> None:
        self.confidence = confidence
        self.seen: list[str] = []

    def extract(self, text: str):  # pragma: no cover — protocol conformance
        return []

    def extract_qualification(self, text: str):
        from app.agents.document_extraction import ExtractedField

        self.seen.append(text)
        return [
            ExtractedField(
                field="notice_period",
                value="3 Monate zum Monatsende",
                confidence=self.confidence,
            ),
            ExtractedField(
                field="salary_minimum", value="92000", confidence=self.confidence
            ),
        ]


async def test_a_transcript_proposes_and_writes_nothing(
    candidate, monkeypatch
) -> None:
    """THE invariant for this path.

    The model is reading hedged speech. Writing its numbers through
    `update_candidate` would stamp them HUMAN_VERIFIED at confidence 1.0 — a
    receipt claiming a person asserted a figure nobody checked.
    """
    reader = _Reader()
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)

    async with SessionLocal() as s:
        result = await service.extract_transcript(
            s,
            tenant_id=TENANT,
            candidate_id=candidate,
            filename="gespraech.txt",
            content=TRANSCRIPT.encode(),
            content_type="text/plain",
        )

    assert [f.field for f in result.fields] == ["notice_period", "salary_minimum"]
    assert any("nichts wurde" in n for n in result.notes)

    async with SessionLocal() as s:
        row = await s.get(Candidate, candidate)
        docs = await service.list_documents(
            s, tenant_id=TENANT, candidate_id=candidate
        )
    # The record is untouched …
    assert row.notice_period is None and row.salary_minimum is None
    # … but the evidence is kept: storing a file asserts nothing.
    assert [(d.kind, d.filename) for d in docs] == [("transkript", "gespraech.txt")]


async def test_a_hedged_value_is_flagged_rather_than_offered_as_fact(
    candidate, monkeypatch
) -> None:
    monkeypatch.setattr(service, "get_cv_extractor", lambda: _Reader(confidence=0.3))

    async with SessionLocal() as s:
        result = await service.extract_transcript(
            s,
            tenant_id=TENANT,
            candidate_id=candidate,
            filename="gespraech.txt",
            content=TRANSCRIPT.encode(),
            content_type="text/plain",
        )

    assert all(f.needs_review for f in result.fields)
    assert any("Mindestgehalt" in item for item in result.review_items)


async def test_a_provider_that_cannot_read_transcripts_guesses_nothing(
    candidate, monkeypatch
) -> None:
    """The heuristic CV regexes would read a year or a phone number as a
    salary floor. An empty form is honest; a wrong number is not."""

    class _CvOnly:
        name = "heuristic"

        def extract(self, text: str):
            return []

    monkeypatch.setattr(service, "get_cv_extractor", lambda: _CvOnly())

    async with SessionLocal() as s:
        result = await service.extract_transcript(
            s,
            tenant_id=TENANT,
            candidate_id=candidate,
            filename="gespraech.txt",
            content=TRANSCRIPT.encode(),
            content_type="text/plain",
        )

    assert result.fields == []
    assert any("manuell" in item for item in result.review_items)
    assert any("kann keine Transkripte lesen" in n for n in result.notes)


async def test_a_transcript_needs_a_candidate_it_belongs_to(monkeypatch) -> None:
    """A CV can arrive before the person is in the system; a transcript cannot
    — the conversation happened with someone already on the record."""
    from app.domain.documents.gate import PreconditionFailed

    monkeypatch.setattr(service, "get_cv_extractor", lambda: _Reader())
    async with SessionLocal() as s:
        with pytest.raises(PreconditionFailed):
            await service.extract_transcript(
                s,
                tenant_id=TENANT,
                candidate_id=uuid.uuid4(),
                filename="gespraech.txt",
                content=TRANSCRIPT.encode(),
                content_type="text/plain",
            )


async def test_an_empty_transcript_is_refused_at_the_route(candidate) -> None:
    from app.main import app as fastapi_app

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://t"
    ) as client:
        empty = await client.post(
            f"{API}/extract-transcript",
            data={"candidate_id": str(candidate)},
            files={"file": ("leer.txt", b"", "text/plain")},
        )
    assert empty.status_code == 400
