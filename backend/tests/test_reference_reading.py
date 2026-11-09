"""Reading a Zeugnis or a Zertifikat — proposals, grounded in the document.

A Zeugnis already attached to a candidate can be READ: employer, period, role,
tasks, skills, the leaving formula and the assessment come back as proposals
the recruiter ticks. Same asymmetry as the transcript: nothing is written.

What these tests pin, because it is what makes the reading "verified":

- every proposal carries a verbatim quote, and a proposal whose quote is not
  in the document is DROPPED — a deterministic check, not the model's word;
- factual values (employer, dates, certificate name …) must themselves appear
  in the text; each skill is checked on its own;
- the decoded grade is an interpretation of coded Zeugnissprache. It must be
  one of the German grades, is always flagged for review, and never arrives
  with a confidence that would let it pass as fact.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import SessionLocal
from app.domain.candidates.models import Candidate
from app.domain.documents import service
from app.domain.documents.extraction.base import ReferenceField
from app.domain.documents.gate import PreconditionFailed

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.uuid4()
API = "/api/v1/documents"

ZEUGNIS = (
    "Arbeitszeugnis\n"
    "Herr Fabian Brain, geboren am 11.01.1993, war vom 01.03.2019 bis zum "
    "31.12.2023 in unserem Unternehmen, der Muster Software GmbH, als "
    "Full-Stack-Entwickler tätig.\n"
    "Zu seinen Aufgaben gehörten die Entwicklung von Microservices in Java "
    "sowie der Betrieb unserer Plattform auf Kubernetes.\n"
    "Er erledigte die ihm übertragenen Aufgaben stets zu unserer vollsten "
    "Zufriedenheit.\n"
    "Herr Brain verlässt uns auf eigenen Wunsch.\n"
)

ASSESSMENT = (
    "Er erledigte die ihm übertragenen Aufgaben stets zu unserer vollsten "
    "Zufriedenheit."
)


def _f(field: str, value: str, evidence: str, confidence: float = 0.9):
    return ReferenceField(
        field=field, value=value, evidence=evidence, confidence=confidence
    )


class _Reader:
    """A provider that reads references; what it 'reads' is set per test."""

    name = "stub"

    def __init__(self, fields: list[ReferenceField]) -> None:
        self.fields = fields
        self.calls: list[tuple[str, str]] = []

    def extract(self, text: str):  # pragma: no cover — protocol conformance
        return []

    def extract_reference(self, text: str, kind: str) -> list[ReferenceField]:
        self.calls.append((text, kind))
        return self.fields


@pytest.fixture
async def candidate() -> uuid.UUID:
    async with SessionLocal() as s:
        row = Candidate(tenant_id=TENANT, full_name="Fabian Brain")
        s.add(row)
        await s.commit()
        return row.id


async def _attach(
    candidate_id: uuid.UUID,
    *,
    kind: str = "zeugnis",
    content: bytes = ZEUGNIS.encode(),
    content_type: str = "text/plain",
    tenant_id: uuid.UUID = TENANT,
) -> uuid.UUID:
    async with SessionLocal() as s:
        doc = await service.store_document(
            s,
            tenant_id=tenant_id,
            candidate_id=candidate_id,
            filename=f"{kind}.txt",
            content=content,
            content_type=content_type,
            kind=kind,
        )
        return doc.id


async def _read(document_id: uuid.UUID, tenant_id: uuid.UUID = TENANT):
    async with SessionLocal() as s:
        return await service.read_reference(
            s, tenant_id=tenant_id, document_id=document_id
        )


async def test_a_zeugnis_proposes_and_writes_nothing(candidate, monkeypatch) -> None:
    reader = _Reader(
        [
            _f("employer", "Muster Software GmbH", "der Muster Software GmbH"),
            _f("period", "01.03.2019 – 31.12.2023", "vom 01.03.2019 bis zum 31.12.2023"),
            _f("leaving_reason", "auf eigenen Wunsch", "verlässt uns auf eigenen Wunsch"),
        ]
    )
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)
    doc_id = await _attach(candidate)

    result = await _read(doc_id)

    assert [f.field for f in result.fields] == ["employer", "period", "leaving_reason"]
    assert result.fields[0].evidence == "der Muster Software GmbH"
    assert reader.calls[0][1] == "zeugnis"
    assert any("nichts wurde" in n for n in result.notes)
    async with SessionLocal() as s:
        row = await s.get(Candidate, candidate)
        docs = await service.list_documents(s, tenant_id=TENANT, candidate_id=candidate)
    # The record is untouched, and reading does not store a second copy.
    assert row.other_notes is None and row.focus_areas in (None, [])
    assert len(docs) == 1


async def test_a_proposal_whose_quote_is_not_in_the_document_is_dropped(
    candidate, monkeypatch
) -> None:
    """THE invariant: the model's quote is checked against the real text."""
    reader = _Reader(
        [
            _f("employer", "Muster Software GmbH", "der Muster Software GmbH"),
            _f("tasks", "Teamleitung von 12 Personen", "leitete ein Team von 12 Personen"),
        ]
    )
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)

    result = await _read(await _attach(candidate))

    assert [f.field for f in result.fields] == ["employer"]
    assert any("Aufgaben" in item and "nicht im Dokument" in item for item in result.review_items)


async def test_a_factual_value_must_appear_in_the_text_not_only_its_quote(
    candidate, monkeypatch
) -> None:
    """A real quote with an invented employer is still an invented employer."""
    reader = _Reader(
        [_f("employer", "Beispiel AG", "der Muster Software GmbH")]
    )
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)

    result = await _read(await _attach(candidate))

    assert result.fields == []


async def test_each_skill_is_checked_on_its_own(candidate, monkeypatch) -> None:
    reader = _Reader(
        [
            _f(
                "skills",
                "Java; Kubernetes; Rust",
                "Microservices in Java sowie der Betrieb unserer Plattform auf Kubernetes",
            )
        ]
    )
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)

    result = await _read(await _attach(candidate))

    assert [(f.field, f.value) for f in result.fields] == [("skills", "Java; Kubernetes")]
    assert any("Rust" in item for item in result.review_items)


async def test_the_decoded_grade_is_an_interpretation_never_a_fact(
    candidate, monkeypatch
) -> None:
    """Coded Zeugnissprache read as a grade is a judgement about a person.
    It must look like one: flagged, low confidence, marked as interpretation —
    however sure the model claims to be."""
    reader = _Reader(
        [
            _f("assessment_quote", ASSESSMENT, ASSESSMENT, 0.95),
            _f("assessment_grade", "sehr gut", ASSESSMENT, 0.99),
        ]
    )
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)

    result = await _read(await _attach(candidate))
    grade = next(f for f in result.fields if f.field == "assessment_grade")
    quote = next(f for f in result.fields if f.field == "assessment_quote")

    assert grade.value == "sehr gut"
    assert grade.interpretation is True and grade.needs_review is True
    assert grade.confidence < 0.6
    assert quote.interpretation is False and quote.needs_review is False


async def test_a_grade_outside_the_german_scale_is_dropped(candidate, monkeypatch) -> None:
    reader = _Reader([_f("assessment_grade", "excellent (A+)", ASSESSMENT)])
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)

    result = await _read(await _attach(candidate))

    assert result.fields == []


async def test_a_zertifikat_is_read_for_its_own_fields(candidate, monkeypatch) -> None:
    text = "Zertifikat\nCertified Kubernetes Administrator (CKA)\nThe Linux Foundation\n15.06.2022\n"
    reader = _Reader(
        [
            _f("certificate_name", "Certified Kubernetes Administrator (CKA)",
               "Certified Kubernetes Administrator (CKA)"),
            _f("issuer", "The Linux Foundation", "The Linux Foundation"),
            _f("issued_on", "15.06.2022", "15.06.2022"),
            # Not a Zertifikat field — a model reading a Zeugnis vocabulary
            # into a certificate must not get it through.
            _f("employer", "The Linux Foundation", "The Linux Foundation"),
        ]
    )
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)

    result = await _read(await _attach(candidate, kind="zertifikat", content=text.encode()))

    assert reader.calls[0][1] == "zertifikat"
    assert [f.field for f in result.fields] == ["certificate_name", "issuer", "issued_on"]


async def test_only_zeugnisse_and_zertifikate_are_read(candidate, monkeypatch) -> None:
    monkeypatch.setattr(service, "get_cv_extractor", lambda: _Reader([]))
    doc_id = await _attach(candidate, kind="sonstiges")

    with pytest.raises(PreconditionFailed):
        await _read(doc_id)


async def test_a_scan_is_refused_with_a_reason_the_recruiter_can_act_on(
    candidate, monkeypatch
) -> None:
    reader = _Reader([])
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)
    doc_id = await _attach(candidate, content=b"\x89PNG\r\n\x1a\n...", content_type="image/png")

    with pytest.raises(PreconditionFailed, match="OCR"):
        await _read(doc_id)
    # Nothing was sent to the model for a document with no text.
    assert reader.calls == []


async def test_another_workspaces_document_is_not_found(candidate, monkeypatch) -> None:
    monkeypatch.setattr(service, "get_cv_extractor", lambda: _Reader([]))
    doc_id = await _attach(candidate)

    with pytest.raises(LookupError):
        await _read(doc_id, tenant_id=OTHER)


async def test_a_provider_that_cannot_read_references_guesses_nothing(
    candidate, monkeypatch
) -> None:
    class _CvOnly:
        name = "heuristic"

        def extract(self, text: str):
            return []

    monkeypatch.setattr(service, "get_cv_extractor", lambda: _CvOnly())

    result = await _read(await _attach(candidate))

    assert result.fields == []
    assert any("manuell" in item for item in result.review_items)


# ── The route ───────────────────────────────────────────────────────────────


async def test_the_route_reads_an_attached_zeugnis(candidate, monkeypatch) -> None:
    from app.main import app as fastapi_app

    reader = _Reader([_f("employer", "Muster Software GmbH", "der Muster Software GmbH")])
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)
    doc_id = await _attach(candidate)

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://t"
    ) as client:
        ok = await client.post(f"{API}/{doc_id}/read")
        missing = await client.post(f"{API}/{uuid.uuid4()}/read")
        cv = await client.post(f"{API}/{await _attach(candidate, kind='cv')}/read")

    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["fields"][0]["field"] == "employer"
    assert body["fields"][0]["evidence"] == "der Muster Software GmbH"
    assert body["candidate_id"] == str(candidate)
    assert missing.status_code == 404
    assert cv.status_code == 422


async def test_the_route_is_metered_like_every_other_model_call(
    candidate, monkeypatch
) -> None:
    """Reading pays a model call; past the quota it is refused BEFORE the call."""
    from app.core.config import settings
    from app.main import app as fastapi_app

    monkeypatch.setattr(settings, "ai_rate_limit_per_minute", 2)
    reader = _Reader([])
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)
    doc_id = await _attach(candidate)

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://t"
    ) as client:
        answers = [(await client.post(f"{API}/{doc_id}/read")).status_code for _ in range(3)]

    assert answers == [200, 200, 429]
    assert len(reader.calls) == 2, "the refused call must not reach the paid model"


# ── The OpenAI reader's contract ────────────────────────────────────────────


def test_the_openai_reader_only_accepts_the_fields_the_service_knows() -> None:
    from app.domain.documents.extraction import openai_extractor as oe
    from app.domain.documents.extraction.base import REFERENCE_FIELD_ORDER

    item = oe._REFERENCE_SCHEMA["schema"]["properties"]["fields"]["items"]
    assert item["properties"]["name"]["enum"] == REFERENCE_FIELD_ORDER
    assert set(item["required"]) == {"name", "value", "evidence", "confidence"}


def test_the_openai_reader_parses_a_response(monkeypatch) -> None:
    import json
    from types import SimpleNamespace

    from app.domain.documents.extraction.openai_extractor import OpenAIExtractor

    payload = {
        "fields": [
            {"name": "employer", "value": " Muster Software GmbH ",
             "evidence": "der Muster Software GmbH", "confidence": 1.4},
            {"name": "not_a_field", "value": "x", "evidence": "x", "confidence": 0.9},
            {"name": "period", "value": "", "evidence": "", "confidence": 0.9},
        ]
    }
    sent: list[dict] = []

    def create(**kwargs):
        sent.append(kwargs)
        msg = SimpleNamespace(content=json.dumps(payload))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    reader = OpenAIExtractor.__new__(OpenAIExtractor)
    reader._model = "test"
    reader._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    fields = reader.extract_reference(ZEUGNIS, "zeugnis")

    assert fields == [
        ReferenceField(
            field="employer", value="Muster Software GmbH",
            evidence="der Muster Software GmbH", confidence=1.0,
        )
    ]
    # The kind reaches the model, so a certificate is not read as a Zeugnis.
    assert "zeugnis" in sent[0]["messages"][1]["content"].lower()


# ── Review findings: grounding must not be satisfiable by accident ──────────


async def test_a_task_needs_its_own_words_in_the_document(candidate, monkeypatch) -> None:
    """A common word as the 'quote' proved nothing: each task is checked."""
    reader = _Reader(
        [
            _f(
                "tasks",
                "Entwicklung von Microservices in Java; Budgetverantwortung 5 Mio",
                "Herr",
            )
        ]
    )
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)

    result = await _read(await _attach(candidate))

    assert [(f.field, f.value) for f in result.fields] == [
        ("tasks", "Entwicklung von Microservices in Java")
    ]
    assert any("Budgetverantwortung" in item for item in result.review_items)


async def test_a_grade_must_cite_the_assessment_not_any_word(candidate, monkeypatch) -> None:
    reader = _Reader([_f("assessment_grade", "sehr gut", "war")])
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)

    result = await _read(await _attach(candidate))

    assert result.fields == []


async def test_a_different_umlaut_is_a_different_employer(candidate, monkeypatch) -> None:
    text = "Herr Brain war bei der Möller GmbH als Entwickler tätig."
    reader = _Reader([_f("employer", "Müller GmbH", "bei der Möller GmbH")])
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)

    result = await _read(await _attach(candidate, content=text.encode()))

    assert result.fields == []


async def test_decomposed_umlauts_in_the_document_still_match(candidate, monkeypatch) -> None:
    """Some PDFs carry 'a' + combining diaeresis; the quote is still verbatim."""
    import unicodedata

    text = unicodedata.normalize("NFD", ZEUGNIS)
    reader = _Reader(
        [_f("leaving_reason", "auf eigenen Wunsch", "Herr Brain verlässt uns auf eigenen Wunsch")]
    )
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)

    result = await _read(await _attach(candidate, content=text.encode()))

    assert [f.field for f in result.fields] == ["leaving_reason"]


async def test_an_iso_period_the_document_does_not_contain_is_dropped(
    candidate, monkeypatch
) -> None:
    """Splitting on every hyphen turned '2019-03-01' into '2019', '03', '01' —
    fragments every Zeugnis contains."""
    reader = _Reader(
        [_f("period", "2019-03-01 – 2023-12-31", "vom 01.03.2019 bis zum 31.12.2023")]
    )
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)

    result = await _read(await _attach(candidate))

    assert result.fields == []


async def test_a_skill_is_a_whole_word_not_a_substring(candidate, monkeypatch) -> None:
    """Skills feed the hard filters: 'Java' must not be read out of 'JavaScript'."""
    text = "Er entwickelte Oberflächen in JavaScript und TypeScript."
    reader = _Reader(
        [_f("skills", "Java; JavaScript", "Oberflächen in JavaScript und TypeScript")]
    )
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)

    result = await _read(await _attach(candidate, content=text.encode()))

    assert [(f.field, f.value) for f in result.fields] == [("skills", "JavaScript")]
