"""Reading a partner's filled cover sheet — proposals, grounded in the sheet.

ELI-19: a profile that comes from a partner recruiter arrives with OUR cover
sheet ("Kandidatenprofil") already filled in. What the partner wrote there —
Zusammenfassung, Technologie Stack, Gehaltsvorstellung, Kündigungsfrist,
Qualifikationen, Sprachkenntnisse, Wechselmotivation — is read back as
PROPOSALS a person confirms. Same asymmetry as Zeugnis and transcript:
nothing is written.

The template is labelled ("Label: value"), so a deterministic label parser
reads it without a model. The fixture is the real pypdf output of a partner's
sheet — one word per line, which is what the parser has to survive — with the
candidate's and the partner's names and contact data replaced by invented ones.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.document_extraction import HUMAN_REVIEW_THRESHOLD
from app.core.database import SessionLocal
from app.domain.candidates.models import Candidate
from app.domain.documents import service
from app.domain.documents.coversheet import parse_coversheet
from app.domain.documents.extraction.base import ReferenceField
from app.domain.documents.gate import is_grounded

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
API = "/api/v1/documents"
SHEET = (Path(__file__).parent / "fixtures" / "coversheet_partner.txt").read_text()


class _Reader:
    """A provider stub — records whether the model was asked at all."""

    name = "stub"

    def __init__(self, fields: list[ReferenceField] | None = None) -> None:
        self.fields = fields or []
        self.calls: list[tuple[str, str]] = []

    def extract(self, text: str):  # pragma: no cover — protocol conformance
        return []

    def extract_reference(self, text: str, kind: str) -> list[ReferenceField]:
        self.calls.append((text, kind))
        return self.fields


@pytest.fixture
async def candidate() -> uuid.UUID:
    async with SessionLocal() as s:
        row = Candidate(tenant_id=TENANT, full_name="Jonas Beispiel")
        s.add(row)
        await s.commit()
        return row.id


async def _attach(candidate_id: uuid.UUID, text: str = SHEET) -> uuid.UUID:
    async with SessionLocal() as s:
        doc = await service.store_document(
            s,
            tenant_id=TENANT,
            candidate_id=candidate_id,
            filename="Kandidatenprofil.txt",
            content=text.encode(),
            content_type="text/plain",
            kind="coversheet",
        )
        return doc.id


async def _read(document_id: uuid.UUID):
    async with SessionLocal() as s:
        return await service.read_reference(s, tenant_id=TENANT, document_id=document_id)


def test_the_label_parser_reads_every_labelled_row_of_the_template() -> None:
    by = {f.field: f for f in parse_coversheet(SHEET)}

    assert by["desired_position"].value == "IT-Administrator (m/w/d)"
    assert by["profile_summary"].value.startswith("Der Kandidat ist Fachinformatiker")
    assert by["profile_summary"].value.endswith("zum Standort.")
    assert by["technical_profile"].value.startswith("Produktionsnahe IT / IT/OT-Systeme")
    assert by["technical_profile"].value.endswith("Active Directory, Netzwerk)")
    assert by["expected_salary"].value == "Ca. 70.000 €"
    assert by["notice_period"].value == "3 Monate"
    assert by["qualifications"].value == "Fachinformatiker für Systemintegration"
    assert by["languages"].value == "deutsch: Muttersprache (C2); englisch: fließend (C1)"
    assert by["motivation"].value.startswith("Er möchte Zertifizierungen")
    assert by["motivation"].value.endswith("belastet wird.")
    # Skills split on top-level commas only: a parenthesis stays with its item.
    skills = by["skills"].value.split("; ")
    assert "Patchmanagement" in skills and "Remote Maintenance" in skills
    assert "IT-Infrastruktur (Windows Server, Active Directory, Netzwerk)" in skills
    # Every value is quoted from the sheet, and the quote is in the sheet.
    for f in by.values():
        assert is_grounded(f.evidence, SHEET), f.field


def test_the_partners_own_contact_block_is_never_read_as_the_candidates() -> None:
    values = " ".join(f.value + " " + f.evidence for f in parse_coversheet(SHEET))
    for leaked in ("Erika", "Muster ", "e.muster", "0151", "Beispiel Partners", "AGB"):
        assert leaked not in values, leaked


def test_a_salary_range_is_left_to_a_person() -> None:
    text = SHEET.replace("Ca.\n \n70.000", "70.000\n \n-\n \n80.000")
    salary = next(f for f in parse_coversheet(text) if f.field == "expected_salary")
    assert salary.value == "70.000 - 80.000 €"
    assert salary.confidence < HUMAN_REVIEW_THRESHOLD  # never pre-ticked


async def test_a_cover_sheet_is_read_without_a_model_and_writes_nothing(
    candidate, monkeypatch
) -> None:
    reader = _Reader()
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)
    doc_id = await _attach(candidate)

    result = await _read(doc_id)

    assert reader.calls == []  # labelled → deterministic, no model round-trip
    fields = {f.field: f for f in result.fields}
    assert set(fields) == {
        "desired_position", "profile_summary", "technical_profile", "skills",
        "expected_salary", "notice_period", "qualifications", "languages",
        "motivation",
    }
    assert all(f.evidence for f in result.fields)
    # Plain labelled rows are pre-ticked; shredding prose into the skills
    # inventory (which feeds the hard filters) is a person's decision.
    assert not fields["notice_period"].needs_review
    assert fields["skills"].needs_review
    assert fields["profile_summary"].label == "Zusammenfassung"
    assert any("nichts wurde" in n for n in result.notes)
    async with SessionLocal() as s:
        row = await s.get(Candidate, candidate)
    assert row.profile_summary is None and row.notice_period is None
    assert row.motivation is None and row.skills in (None, [])


async def test_an_unlabelled_cover_sheet_falls_back_to_the_model_and_is_grounded(
    candidate, monkeypatch
) -> None:
    text = "Profil Jonas Beispiel. Er kann 3 Monate nach Kündigung wechseln.\n"
    reader = _Reader(
        [
            ReferenceField("notice_period", "3 Monate", "Er kann 3 Monate nach Kündigung", 0.9),
            ReferenceField("motivation", "mehr Geld", "Er will mehr Geld", 0.9),  # not in text
            ReferenceField("employer", "Muster GmbH", "Profil Jonas", 0.9),  # Zeugnis field
        ]
    )
    monkeypatch.setattr(service, "get_cv_extractor", lambda: reader)
    doc_id = await _attach(candidate, text)

    result = await _read(doc_id)

    assert reader.calls and reader.calls[0][1] == "coversheet"
    assert [f.field for f in result.fields] == ["notice_period"]
    assert any("Zitat nicht im Dokument" in r for r in result.review_items)


async def test_coversheet_is_an_upload_kind(candidate) -> None:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"{API}/upload",
            data={"candidate_id": str(candidate), "kind": "coversheet"},
            files={"file": ("Kandidatenprofil.txt", SHEET.encode(), "text/plain")},
        )
        assert r.status_code == 201, r.text
        assert r.json()["kind"] == "coversheet"
        read = await c.post(f"{API}/{r.json()['id']}/read")
    assert read.status_code == 200, read.text
    assert any(f["field"] == "notice_period" for f in read.json()["fields"])
