"""ELI-28 (1): the CV parser did not recognise PLZ, Land, Job-Titel or the
current employer.

Every CV below is synthetic. The checks are on what reaches the preview and
the record: a value read from the document, grounded in its text, and the
one default the product asked for (Land = Deutschland when the CV names none).
"""

from __future__ import annotations

import uuid

from app.agents.document_extraction import HUMAN_REVIEW_THRESHOLD, ExtractedField
from app.core.database import SessionLocal
from app.domain.candidates.models import Candidate
from app.domain.common.enums import WorkPermitStatus
from app.domain.documents import parser
from app.domain.documents import service as documents
from app.domain.documents.extraction.base import CVSections, WorkRole

STACKED_CV = """Erika Beispiel
Musterstraße 12
10115 Berlin
erika.beispiel@example.org
+49 30 1234567

Berufserfahrung
03/2021 – heute
Senior Backend Engineer
Beispiel Software GmbH, Berlin
01/2017 – 02/2021
Backend Developer
Alte Firma AG, Hamburg
"""

ONE_LINE_CV = """Max Muster
Am Hang 3, D-80331 München, Deutschland
max.muster@example.org

Werdegang
Data Analyst | Früher AG | 2015 – 2019
Senior Data Analyst | Gegenwart SE | seit 01/2020
"""


def _by_field(fields: list[ExtractedField]) -> dict[str, ExtractedField]:
    return {f.field: f for f in fields}


# ── Heuristic parser ────────────────────────────────────────────────────────


def test_heuristic_reads_postcode_and_city_from_the_address_block() -> None:
    got = _by_field(parser.extract_cv_fields(STACKED_CV))
    assert got["postal_code"].value == "10115"
    assert got["city"].value == "Berlin"
    assert got["postal_code"].confidence >= HUMAN_REVIEW_THRESHOLD


def test_heuristic_reads_a_postcode_inline_with_street_and_country() -> None:
    got = _by_field(parser.extract_cv_fields(ONE_LINE_CV))
    assert got["postal_code"].value == "80331"
    assert got["city"].value == "München"
    assert got["country"].value == "Deutschland"


def test_heuristic_does_not_take_a_phone_number_or_a_year_for_a_postcode() -> None:
    text = "Erika Beispiel\n+49 30 12345 6789\n2019 – 2021 Berater\n"
    assert "postal_code" not in _by_field(parser.extract_cv_fields(text))


def test_heuristic_names_no_country_the_cv_does_not_state() -> None:
    assert "country" not in _by_field(parser.extract_cv_fields(STACKED_CV))


def test_heuristic_takes_the_open_ended_position_as_current_role() -> None:
    got = _by_field(parser.extract_cv_fields(STACKED_CV))
    assert got["current_title"].value == "Senior Backend Engineer"
    assert got["current_company"].value == "Beispiel Software GmbH"
    assert got["current_company"].confidence >= HUMAN_REVIEW_THRESHOLD


def test_heuristic_current_role_on_one_line_skips_the_closed_one() -> None:
    got = _by_field(parser.extract_cv_fields(ONE_LINE_CV))
    assert got["current_title"].value == "Senior Data Analyst"
    assert got["current_company"].value == "Gegenwart SE"


def test_heuristic_has_no_current_company_when_every_role_has_ended() -> None:
    text = "Erika Beispiel\n2015 – 2019\nBerater\nAlte Firma AG\n"
    assert "current_company" not in _by_field(parser.extract_cv_fields(text))


# ── Service: what reaches the preview and the record ────────────────────────


def _fake_extractor(monkeypatch, text: str, fields, sections=None) -> None:
    monkeypatch.setattr(parser, "pdf_to_text", lambda content: text)
    monkeypatch.setattr(
        documents, "_run_extractor", lambda t: (fields, sections or CVSections(), "fake")
    )


async def test_current_role_is_derived_from_the_open_work_history_entry(monkeypatch) -> None:
    """The LLM returned the history but left the flat fields empty."""
    sections = CVSections(work_history=[
        WorkRole(title="Senior Backend Engineer", company="Beispiel Software GmbH",
                 start_date="03/2021", end_date="heute"),
        WorkRole(title="Backend Developer", company="Alte Firma AG",
                 start_date="01/2017", end_date="02/2021"),
    ])
    _fake_extractor(monkeypatch, STACKED_CV, [
        ExtractedField(field="full_name", value="Erika Beispiel", confidence=0.95),
    ], sections)
    async with SessionLocal() as s:
        result = await documents.extract_cv(
            s, filename="cv.pdf", content=b"%PDF", tenant_id=uuid.uuid4(), persist=False
        )
    got = {f.field: f for f in result.fields}
    assert got["current_title"].value == "Senior Backend Engineer"
    assert got["current_company"].value == "Beispiel Software GmbH"
    assert not got["current_company"].needs_review


async def test_no_current_role_when_the_newest_entry_has_ended(monkeypatch) -> None:
    sections = CVSections(work_history=[
        WorkRole(title="Backend Developer", company="Alte Firma AG",
                 start_date="01/2017", end_date="02/2021"),
    ])
    _fake_extractor(monkeypatch, STACKED_CV, [
        ExtractedField(field="full_name", value="Erika Beispiel", confidence=0.95),
    ], sections)
    async with SessionLocal() as s:
        result = await documents.extract_cv(
            s, filename="cv.pdf", content=b"%PDF", tenant_id=uuid.uuid4(), persist=False
        )
    assert "current_company" not in {f.field for f in result.fields}


async def test_an_ungrounded_postcode_or_employer_goes_to_review(monkeypatch) -> None:
    """A value the document does not contain is a proposal nobody can check."""
    _fake_extractor(monkeypatch, STACKED_CV, [
        ExtractedField(field="full_name", value="Erika Beispiel", confidence=0.95),
        ExtractedField(field="postal_code", value="20095", confidence=0.95),
        ExtractedField(field="current_company", value="Erfundene AG", confidence=0.95),
        ExtractedField(field="current_title", value="Senior Backend Engineer", confidence=0.9),
    ])
    async with SessionLocal() as s:
        result = await documents.extract_cv(
            s, filename="cv.pdf", content=b"%PDF", tenant_id=uuid.uuid4(), persist=False
        )
    got = {f.field: f for f in result.fields}
    assert got["postal_code"].needs_review
    assert got["current_company"].needs_review
    assert not got["current_title"].needs_review


async def _persist(monkeypatch, text: str, fields, **kw) -> Candidate:
    _fake_extractor(monkeypatch, text, fields)
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        result = await documents.extract_cv(
            s, filename="cv.pdf", content=b"%PDF", tenant_id=tenant, persist=True, **kw
        )
        await s.commit()
        cand = await s.get(Candidate, result.candidate_id)
        assert cand is not None
        return cand


async def test_country_defaults_to_deutschland_when_the_cv_names_none(monkeypatch) -> None:
    cand = await _persist(monkeypatch, STACKED_CV, [
        ExtractedField(field="full_name", value="Erika Beispiel", confidence=0.95),
        ExtractedField(field="postal_code", value="10115", confidence=0.9),
    ])
    assert cand.postal_code == "10115"
    assert cand.country == "Deutschland"


async def test_a_stated_country_wins_over_the_default(monkeypatch) -> None:
    text = STACKED_CV + "\nWien, Österreich\n"
    cand = await _persist(monkeypatch, text, [
        ExtractedField(field="full_name", value="Erika Beispiel", confidence=0.95),
        ExtractedField(field="country", value="Österreich", confidence=0.9),
    ])
    assert cand.country == "Österreich"


async def test_no_german_default_for_a_four_digit_postcode(monkeypatch) -> None:
    """1010 is Vienna; a German default there would be a wrong fact."""
    text = "Erika Beispiel\nRingstraße 1\n1010 Wien\n"
    cand = await _persist(monkeypatch, text, [
        ExtractedField(field="full_name", value="Erika Beispiel", confidence=0.95),
        ExtractedField(field="postal_code", value="1010", confidence=0.9),
    ])
    assert cand.country is None


# ── Work permit chosen at upload (ELI-28 item 2) ────────────────────────────


async def test_cv_upload_stores_the_work_permit_the_recruiter_chose(monkeypatch) -> None:
    cand = await _persist(monkeypatch, STACKED_CV, [
        ExtractedField(field="full_name", value="Erika Beispiel", confidence=0.95),
    ], work_permit=WorkPermitStatus.CITIZEN)
    assert cand.work_permit == WorkPermitStatus.CITIZEN.value


async def test_cv_upload_without_a_choice_keeps_unknown(monkeypatch) -> None:
    """The backend default is unchanged: a CV says nothing about a permit,
    and 'unknown' is what keeps the matcher's hard filter honest."""
    cand = await _persist(monkeypatch, STACKED_CV, [
        ExtractedField(field="full_name", value="Erika Beispiel", confidence=0.95),
    ])
    assert cand.work_permit == WorkPermitStatus.UNKNOWN.value
