"""ELI-20: the cover sheet — a Kandidatenprofil in the workspace's CI.

Every test reads the PDF the endpoint returns with pypdf and asserts on its
TEXT, because "200 application/pdf" says nothing about what a client sees.
"""

from __future__ import annotations

import io
import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from sqlalchemy import select

from app.core.auth import RECRUITER, Actor, get_current_actor
from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.candidates.models import Candidate
from app.domain.common.enums import DocumentKind, ReceiptAction
from app.domain.documents.models import CandidateDocument
from app.domain.jobs.models import Job
from app.domain.pipeline.models import Application
from app.domain.presentation import render
from app.domain.verification.models import Receipt

TENANT = settings.default_tenant_id
API = "/api/v1"

SUMMARY = (
    "Herr Celik ist Fachinformatiker für Systemintegration und verbindet seit "
    "rund vier Jahren IT-Betrieb mit Produktionserfahrung."
)
MOTIVATION = "Er möchte Zertifizierungen auffrischen und sich fachlich weiterentwickeln."
BRANDING = {
    "company_name": "Beispiel Partners GmbH",
    "company_line": "Beispiel Partners GmbH · Musterstr. 3 · 80331 München · www.example.org",
    "legal_text": "Mit Einladung dieses Kandidaten stimmen Sie unseren AGB zu.",
    "primary_color": "#1d6b5f",
    "contact_phone": "089 123 456",
}


def _text(pdf: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf))
    return " ".join(" ".join((p.extract_text() or "") for p in reader.pages).split())


def _pdf(marker: str, pages: int = 1) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i in range(pages):
        c.drawString(72, 720, f"{marker} {i + 1}")
        c.showPage()
    c.save()
    return buf.getvalue()


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 80), (29, 107, 95)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
async def client():
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()


async def _candidate(tenant: uuid.UUID = TENANT, **extra) -> uuid.UUID:
    fields = dict(
        full_name="Nesim Celik",
        first_name="Nesim",
        last_name="Celik",
        email="nesim.celik@example.org",
        phone="0170 999 888",
        current_title="Manager IT Workplace",
        profile_summary=SUMMARY,
        technical_profile="Windows Server, Active Directory, Netzwerk",
        salary_expectation=70000,
        notice_period="3 Monate",
        education=[{"degree": "Fachinformatiker für Systemintegration", "institution": "IHK"}],
        languages=["deutsch: Muttersprache (C2)", "englisch: fließend (C1)"],
        motivation=MOTIVATION,
    )
    fields.update(extra)
    async with SessionLocal() as s:
        row = Candidate(tenant_id=tenant, **fields)
        s.add(row)
        await s.commit()
        return row.id


async def _document(candidate_id, kind: str, filename: str, content: bytes, ctype="application/pdf"):
    async with SessionLocal() as s:
        doc = CandidateDocument(
            tenant_id=TENANT,
            candidate_id=candidate_id,
            kind=kind,
            filename=filename,
            content_type=ctype,
            byte_size=len(content),
            content=content,
        )
        s.add(doc)
        await s.commit()
        return doc.id


async def test_the_cover_sheet_carries_the_record_and_the_workspace_ci(client) -> None:
    cid = await _candidate()
    assert (await client.put(f"{API}/branding", json=BRANDING)).status_code == 200

    res = await client.get(
        f"{API}/candidates/{cid}/cover-sheet",
        params={"variant": "cover", "contact_name": "Thomas Berater", "contact_email": "tb@example.org"},
    )

    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert "attachment" in res.headers["content-disposition"]
    text = _text(res.content)
    for expected in (
        "Kandidatenprofil – Nesim Celik",
        "Angestrebte Position: Manager IT Workplace",
        "Zusammenfassung:",
        "verbindet seit rund vier Jahren",
        "Technologie Stack:",
        "Active Directory",
        "Gehaltsvorstellung: 70.000 €",
        "Kündigungsfrist: 3 Monate",
        "Fachinformatiker für Systemintegration",
        "Sprachkenntnisse nach Sprachniveau:",
        "deutsch: Muttersprache (C2)",
        "englisch: fließend (C1)",
        "Wechselmotivation:",
        "Zertifizierungen auffrischen",
        "Kontakt: Thomas Berater – tb@example.org – 089 123 456",
        BRANDING["company_line"],
        "stimmen Sie unseren AGB zu",
    ):
        assert expected in text, expected
    # The candidate's own contact data never reaches a client.
    assert "nesim.celik@example.org" not in text
    assert "0170 999 888" not in text
    assert len(PdfReader(io.BytesIO(res.content)).pages) == 1


async def test_anonymous_is_the_page_alone_with_initials(client) -> None:
    cid = await _candidate()
    await _document(cid, DocumentKind.CV.value, "cv.pdf", _pdf("LEBENSLAUF"))

    res = await client.get(f"{API}/candidates/{cid}/cover-sheet", params={"variant": "anonymous"})

    assert res.status_code == 200
    text = _text(res.content)
    assert "Kandidatenprofil – Kandidat N. C." in text
    # Not in the title, not in the recruiter's prose either.
    assert "Celik" not in text and "Nesim" not in text
    assert "Herr N. C. ist Fachinformatiker" in text
    assert "LEBENSLAUF" not in text
    assert len(PdfReader(io.BytesIO(res.content)).pages) == 1
    assert "Nesim" not in (PdfReader(io.BytesIO(res.content)).metadata.title or "")


async def test_anonymous_masks_the_current_employer_in_the_prose(client) -> None:
    cid = await _candidate(
        current_company="Coaching Company, Kreuztal",
        profile_summary="Seit 2022 bei der Coaching Company in Kreuztal.",
    )
    text = _text(
        (await client.get(f"{API}/candidates/{cid}/cover-sheet", params={"variant": "anonymous"})).content
    )
    assert "Seit 2022 bei der [Arbeitgeber] in Kreuztal." in text
    assert "Coaching" not in text
    # Named in the ordinary variant: a client who knows the name may know the firm.
    named = _text((await client.get(f"{API}/candidates/{cid}/cover-sheet")).content)
    assert "Coaching Company in Kreuztal" in named


async def test_the_files_follow_the_page_and_a_non_pdf_is_named_not_merged(client) -> None:
    cid = await _candidate()
    await _document(cid, DocumentKind.CV.value, "cv-alt.pdf", _pdf("ALTER-CV"))
    async with SessionLocal() as s:  # make the second CV unambiguously newer
        import datetime as dt

        (await s.scalars(select(CandidateDocument))).one().created_at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        await s.commit()
    await _document(cid, DocumentKind.CV.value, "cv.pdf", _pdf("LEBENSLAUF", pages=2))
    await _document(cid, DocumentKind.ZEUGNIS.value, "zeugnis.pdf", _pdf("ZEUGNIS"))
    await _document(cid, DocumentKind.ZERTIFIKAT.value, "zert.pdf", _pdf("ZERTIFIKAT"))
    word = await _document(
        cid, DocumentKind.ZEUGNIS.value, "zeugnis.docx", b"PK\x03\x04 word",
        ctype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    await _document(cid, DocumentKind.TRANSKRIPT.value, "notiz.pdf", _pdf("TRANSKRIPT"))

    preview = (
        await client.get(
            f"{API}/candidates/{cid}/cover-sheet/preview", params={"variant": "cover_cv_references"}
        )
    ).json()
    by_name = {a["filename"]: a for a in preview["attachments"]}
    assert set(by_name) == {"cv.pdf", "zeugnis.pdf", "zert.pdf", "zeugnis.docx"}
    assert by_name["zeugnis.docx"] == {
        "document_id": str(word), "filename": "zeugnis.docx", "kind": "zeugnis",
        "included": False, "reason": "not_pdf",
    }

    full = await client.get(
        f"{API}/candidates/{cid}/cover-sheet", params={"variant": "cover_cv_references"}
    )
    reader = PdfReader(io.BytesIO(full.content))
    assert len(reader.pages) == 1 + 2 + 1 + 1
    pages = [" ".join((p.extract_text() or "").split()) for p in reader.pages]
    assert "Kandidatenprofil" in pages[0]
    assert pages[1:] == ["LEBENSLAUF 1", "LEBENSLAUF 2", "ZEUGNIS 1", "ZERTIFIKAT 1"]

    cv_only = await client.get(f"{API}/candidates/{cid}/cover-sheet", params={"variant": "cover_cv"})
    assert len(PdfReader(io.BytesIO(cv_only.content)).pages) == 3
    assert "ALTER-CV" not in _text(cv_only.content)


async def test_empty_fields_are_listed_and_left_off_the_page(client) -> None:
    cid = await _candidate(
        current_title=None, profile_summary=None, technical_profile=None, skills=[],
        salary_expectation=None, notice_period=None, education=None, languages=None,
        motivation=None,
    )
    preview = (await client.get(f"{API}/candidates/{cid}/cover-sheet/preview")).json()
    assert preview["missing"] == [
        "Angestrebte Position", "Zusammenfassung", "Technologie Stack",
        "Gehaltsvorstellung", "Kündigungsfrist", "Qualifikationen",
        "Sprachkenntnisse", "Wechselmotivation",
    ]
    assert preview["branding_missing"] == ["logo", "company_line", "legal_text"]

    res = await client.get(f"{API}/candidates/{cid}/cover-sheet")
    assert res.status_code == 200
    text = _text(res.content)
    assert "Kandidatenprofil – Nesim Celik" in text
    for label in ("Angestrebte Position", "Zusammenfassung", "Wechselmotivation", "Rahmenbedingungen"):
        assert label not in text


async def test_the_skills_stand_in_for_a_missing_technical_profile(client) -> None:
    cid = await _candidate(technical_profile=None, skills=["Python", "Kubernetes"])
    text = _text((await client.get(f"{API}/candidates/{cid}/cover-sheet")).content)
    assert "Python, Kubernetes" in text


async def test_the_position_comes_from_the_process(client) -> None:
    cid = await _candidate()
    other = await _candidate(full_name="Andere Person", first_name="Andere", last_name="Person")
    async with SessionLocal() as s:
        job = Job(tenant_id=TENANT, title="IT-Administrator (m/w/d)")
        s.add(job)
        await s.flush()
        mine = Application(tenant_id=TENANT, candidate_id=cid, job_id=job.id)
        theirs = Application(tenant_id=TENANT, candidate_id=other, job_id=job.id)
        s.add_all([mine, theirs])
        await s.commit()

    preview = (
        await client.get(
            f"{API}/candidates/{cid}/cover-sheet/preview", params={"application_id": str(mine.id)}
        )
    ).json()
    assert (preview["position"], preview["position_source"]) == ("IT-Administrator (m/w/d)", "mandate")

    given = (
        await client.get(f"{API}/candidates/{cid}/cover-sheet/preview", params={"position": "SAP-Berater"})
    ).json()
    assert (given["position"], given["position_source"]) == ("SAP-Berater", "given")

    # Another candidate's process is not this one's.
    res = await client.get(
        f"{API}/candidates/{cid}/cover-sheet", params={"application_id": str(theirs.id)}
    )
    assert res.status_code == 404


async def test_a_download_leaves_a_receipt_with_references_only(client) -> None:
    cid = await _candidate()
    doc = await _document(cid, DocumentKind.CV.value, "cv.pdf", _pdf("LEBENSLAUF"))
    await client.get(f"{API}/candidates/{cid}/cover-sheet/preview", params={"variant": "cover_cv"})
    async with SessionLocal() as s:
        assert (await s.scalars(select(Receipt))).all() == []  # a preview discloses nothing

    await client.get(f"{API}/candidates/{cid}/cover-sheet", params={"variant": "cover_cv"})

    async with SessionLocal() as s:
        receipts = (await s.scalars(select(Receipt).where(Receipt.subject_id == str(cid)))).all()
    assert len(receipts) == 1
    r = receipts[0]
    assert r.action == ReceiptAction.READ and r.subject_type == "candidate"
    assert r.payload == {"variant": "cover_cv", "application_id": None, "documents": [str(doc)]}
    ledger = r.summary + json.dumps(r.payload)
    for value in ("Celik", "70000", "70.000", "nesim", "Muttersprache"):
        assert value not in ledger


async def test_another_workspaces_candidate_is_not_found(client) -> None:
    cid = await _candidate(tenant=uuid.uuid4())
    assert (await client.get(f"{API}/candidates/{cid}/cover-sheet")).status_code == 404
    assert (await client.get(f"{API}/candidates/{cid}/cover-sheet/preview")).status_code == 404


async def test_branding_is_an_admins_and_the_logo_must_be_an_image(client) -> None:
    from app.main import app

    default = (await client.get(f"{API}/branding")).json()
    assert default["primary_color"] == "#1F4E5A" and default["has_logo"] is False

    bad = await client.put(
        f"{API}/branding/logo", files={"file": ("logo.png", b"not an image", "image/png")}
    )
    assert bad.status_code == 422
    svg = await client.put(
        f"{API}/branding/logo", files={"file": ("logo.svg", b"<svg/>", "image/svg+xml")}
    )
    assert svg.status_code == 422
    ok = await client.put(f"{API}/branding/logo", files={"file": ("logo.png", _png(), "image/png")})
    assert ok.status_code == 200 and ok.json()["has_logo"] is True
    assert (await client.get(f"{API}/branding/logo")).content == _png()

    cid = await _candidate()
    assert (await client.get(f"{API}/candidates/{cid}/cover-sheet")).status_code == 200

    app.dependency_overrides[get_current_actor] = lambda: Actor(
        tenant_id=TENANT, user_id="user_rec", name="Rita", role=RECRUITER, role_known=True
    )
    assert (await client.put(f"{API}/branding", json=BRANDING)).status_code == 403
    assert (await client.delete(f"{API}/branding/logo")).status_code == 403
    assert (await client.get(f"{API}/branding")).status_code == 200
    # Downloading is everybody's work.
    assert (await client.get(f"{API}/candidates/{cid}/cover-sheet")).status_code == 200
    app.dependency_overrides.clear()

    assert (await client.delete(f"{API}/branding/logo")).status_code == 204
    assert (await client.get(f"{API}/branding")).json()["has_logo"] is False


async def test_branding_rejects_a_colour_that_is_not_hex(client) -> None:
    res = await client.put(f"{API}/branding", json={**BRANDING, "primary_color": "teal"})
    assert res.status_code == 422


def test_a_summary_longer_than_a_page_breaks_inside_its_row() -> None:
    long = " ".join(["Produktionsnahe IT und Shopfloor-Erfahrung."] * 400)
    pdf = render.render(
        render.Sheet(
            title="Kandidatenprofil – Test",
            position="Admin",
            rows=(render.Row(label="Zusammenfassung", text=long),),
            contact="Kontakt: A",
        ),
        render.Branding(primary_color="#1F4E5A", legal_text="AGB " * 120, company_line="Firma"),
    )
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) > 1
    # The foot is on every page.
    assert all("Firma" in (p.extract_text() or "") for p in reader.pages)


async def test_a_layout_failure_carries_no_candidate_text(monkeypatch) -> None:
    """ReportLab's errors quote the flowable; a crash report must not."""
    from app.domain.presentation import service

    def boom(*_a, **_k):
        raise ValueError("Flowable too large: Nesim Celik verbindet …")

    monkeypatch.setattr(service.render, "render", boom)
    cid = await _candidate()
    async with SessionLocal() as s:
        comp = await service.compose(s, tenant_id=TENANT, candidate_id=cid, variant=service.V.COVER)
    with pytest.raises(service.RenderFailed) as info:
        service.assemble(comp)
    assert "Celik" not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__
