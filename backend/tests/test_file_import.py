"""Onboarding by file — the path that works whatever system a customer leaves.

The tests are shaped by what actually arrives: a German ATS export with
semicolons and cp1252, a title row above the table, a name split across two
columns, duplicate e-mails, and the same file imported twice because the
first run had something wrong with it.
"""

from __future__ import annotations

import io
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import SessionLocal
from app.domain.candidates.models import Candidate
from app.domain.companies.models import Company
from app.domain.imports import parser, service
from app.domain.managers.models import Manager

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.uuid4()
API = "/api/v1/imports"

GERMAN_EXPORT = (
    "Kandidatenliste Stand 01.10.2026;;;;;\r\n"
    "Vorname;Nachname;E-Mail (geschäftlich);Position;Gehaltsvorstellung;Kenntnisse\r\n"
    "Jörg;Müller;j.mueller@example.de;Senior Java Entwickler;85.000 €;Java; Spring\r\n"
    "Anna;Schmidt;a.schmidt@example.de;Data Engineer;92000;Python, Spark\r\n"
).encode("cp1252")


# ---------------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------------


def test_a_german_export_reads_without_anyone_fixing_it() -> None:
    """Semicolons, cp1252, a title row above the table. All three at once is
    the normal case, and any one of them used to be the end of the import."""
    sheet = parser.read("Kandidaten.csv", GERMAN_EXPORT)
    assert sheet.columns[:3] == ["Vorname", "Nachname", "E-Mail (geschäftlich)"]
    assert len(sheet.rows) == 2
    assert sheet.rows[0]["Vorname"] == "Jörg"
    assert "cp1252" in sheet.note and ";" in sheet.note
    assert any("übersprungen" in p for p in sheet.problems)


def test_an_empty_or_unreadable_file_says_which() -> None:
    with pytest.raises(parser.UnreadableFile):
        parser.read("leer.csv", b"")
    with pytest.raises(parser.UnreadableFile) as raised:
        parser.read("alt.xls", b"\xd0\xcf\x11\xe0")
    assert ".xlsx" in str(raised.value)


def test_duplicate_headers_do_not_overwrite_each_other() -> None:
    sheet = parser.read("x.csv", b"Name,Telefon,Telefon\nA,1,2\n")
    assert sheet.columns == ["Name", "Telefon", "Telefon (2)"]
    assert sheet.rows[0]["Telefon"] == "1" and sheet.rows[0]["Telefon (2)"] == "2"


def test_an_xlsx_is_read_the_same_way() -> None:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(["Vorname", "Nachname", "E-Mail"])
    sheet.append(["Lena", "Hoffmann", "lena@example.de"])
    buffer = io.BytesIO()
    book.save(buffer)

    parsed = parser.read("export.xlsx", buffer.getvalue())
    assert parsed.columns == ["Vorname", "Nachname", "E-Mail"]
    assert parsed.rows[0]["Nachname"] == "Hoffmann"


# ---------------------------------------------------------------------------
# Guessing what the columns mean
# ---------------------------------------------------------------------------


def test_the_mapping_is_guessed_from_real_header_names() -> None:
    mapping = service.suggest_mapping(
        "candidates",
        ["Vorname", "Nachname", "E-Mail (geschäftlich)", "Mobil", "Position",
         "Gehaltsvorstellung", "Kenntnisse", "Kandidaten-ID", "Lieblingsfarbe"],
    )
    assert mapping["Vorname"] == "first_name"
    assert mapping["E-Mail (geschäftlich)"] == "email"
    assert mapping["Mobil"] == "phone"
    assert mapping["Gehaltsvorstellung"] == "salary_expectation"
    assert mapping["Kenntnisse"] == "skills"
    assert mapping["Kandidaten-ID"] == "external_id"
    # A column nothing understands is simply left out, not forced somewhere.
    assert "Lieblingsfarbe" not in mapping


def test_one_column_cannot_claim_two_fields() -> None:
    """"Gehalt" and "Mindestgehalt" both contain "gehalt"; the longer, more
    specific synonym must win and the other must not be stolen."""
    mapping = service.suggest_mapping("candidates", ["Mindestgehalt", "Gehalt"])
    assert mapping["Mindestgehalt"] == "salary_minimum"
    assert mapping["Gehalt"] == "salary_expectation"


def test_values_are_coerced_the_way_the_cells_are_written() -> None:
    assert service.coerce("85.000 €", "int") == 85000
    assert service.coerce("85", "int") == 85000  # somebody wrote thousands
    assert service.coerce("Java; Spring, Kafka", "list") == ["Java", "Spring", "Kafka"]
    assert service.coerce("  ", "text") is None


# ---------------------------------------------------------------------------
# The preview — the whole point
# ---------------------------------------------------------------------------


async def test_the_plan_says_what_would_happen_before_anything_is_written() -> None:
    sheet = parser.read("k.csv", GERMAN_EXPORT)
    mapping = service.suggest_mapping("candidates", sheet.columns)
    async with SessionLocal() as s:
        planned = await service.plan(
            s, tenant_id=TENANT, entity="candidates", rows=sheet.rows, mapping=mapping
        )
        after = (await s.execute(__import__("sqlalchemy").select(Candidate))).scalars().all()

    assert planned.counts == {"create": 2, "update": 0, "skip": 0}
    # A name split across two columns satisfies the required full_name.
    assert planned.rows[0].values["full_name"] == "Jörg Müller"
    assert planned.rows[0].values["salary_expectation"] == 85000
    assert after == [], "the preview wrote to the database"


async def test_a_row_without_the_required_field_is_skipped_with_a_reason() -> None:
    sheet = parser.read("k.csv", b"Vorname,E-Mail\n,nobody@example.de\nAnna,a@example.de\n")
    mapping = service.suggest_mapping("candidates", sheet.columns)
    async with SessionLocal() as s:
        planned = await service.plan(
            s, tenant_id=TENANT, entity="candidates", rows=sheet.rows, mapping=mapping
        )
    assert planned.counts == {"create": 1, "update": 0, "skip": 1}
    skipped = next(r for r in planned.rows if r.action == "skip")
    assert "Name" in (skipped.reason or "")


async def test_a_file_that_cannot_identify_its_rows_is_refused_outright() -> None:
    """No required field mapped means every row would be junk — say so once,
    rather than listing the same problem a thousand times."""
    sheet = parser.read("k.csv", b"Spalte A,Spalte B\n1,2\n")
    async with SessionLocal() as s:
        planned = await service.plan(
            s, tenant_id=TENANT, entity="candidates", rows=sheet.rows, mapping={}
        )
    assert planned.rows == []
    assert planned.problems and "Pflichtfeld" in planned.problems[0]


async def test_the_same_person_twice_in_one_file_imports_once() -> None:
    sheet = parser.read(
        "k.csv",
        b"Name,E-Mail\nAnna Schmidt,a@example.de\nAnna Schmidt,A@Example.de\n",
    )
    mapping = service.suggest_mapping("candidates", sheet.columns)
    async with SessionLocal() as s:
        planned = await service.plan(
            s, tenant_id=TENANT, entity="candidates", rows=sheet.rows, mapping=mapping
        )
    assert planned.counts["create"] == 1
    assert "Dublette" in (planned.rows[1].reason or "")


# ---------------------------------------------------------------------------
# Writing, and writing again
# ---------------------------------------------------------------------------


async def _import(entity: str, raw: bytes, tenant: uuid.UUID = TENANT) -> dict:
    sheet = parser.read("f.csv", raw)
    mapping = service.suggest_mapping(entity, sheet.columns)
    async with SessionLocal() as s:
        return await service.commit(
            s, tenant_id=tenant, entity=entity, rows=sheet.rows, mapping=mapping
        )


async def test_importing_the_same_file_twice_is_one_book_not_two() -> None:
    """THE property that makes a messy first import survivable: fix the file,
    run it again."""
    first = await _import("candidates", GERMAN_EXPORT)
    assert (first["created"], first["updated"]) == (2, 0)

    second = await _import("candidates", GERMAN_EXPORT)
    assert (second["created"], second["updated"]) == (0, 2)

    async with SessionLocal() as s:
        rows = (await s.execute(__import__("sqlalchemy").select(Candidate))).scalars().all()
    assert len(rows) == 2
    assert {r.full_name for r in rows} == {"Jörg Müller", "Anna Schmidt"}
    assert rows[0].source == "datei-import"


async def test_a_corrected_file_updates_rather_than_duplicates() -> None:
    await _import("candidates", b"Name,E-Mail,Position\nAnna Schmidt,a@example.de,Entwicklerin\n")
    await _import("candidates", b"Name,E-Mail,Position\nAnna Schmidt,a@example.de,Lead Engineer\n")
    async with SessionLocal() as s:
        rows = (await s.execute(__import__("sqlalchemy").select(Candidate))).scalars().all()
    assert len(rows) == 1 and rows[0].current_title == "Lead Engineer"


async def test_contacts_attach_to_their_company_even_if_it_is_not_imported_yet() -> None:
    """Files arrive in whatever order the customer sends them."""
    result = await _import(
        "managers",
        "Name;Firma;Position;E-Mail\nM. Wagner;Nexval GmbH;CTO;wagner@nexval.de\n".encode(),
    )
    assert result["created"] == 1
    async with SessionLocal() as s:
        sa = __import__("sqlalchemy")
        manager = (await s.execute(sa.select(Manager))).scalars().one()
        company = (await s.execute(sa.select(Company))).scalars().one()
    assert manager.company_id == company.id
    assert company.name == "Nexval GmbH"


async def test_an_import_lands_only_in_its_own_workspace() -> None:
    await _import("candidates", b"Name,E-Mail\nNur Meine,mine@example.de\n", TENANT)
    await _import("candidates", b"Name,E-Mail\nNur Ihre,theirs@example.de\n", OTHER)
    async with SessionLocal() as s:
        sa = __import__("sqlalchemy")
        mine = (
            await s.execute(sa.select(Candidate).where(Candidate.tenant_id == TENANT))
        ).scalars().all()
    assert [c.full_name for c in mine] == ["Nur Meine"]


async def test_routes() -> None:
    from app.main import app as fastapi_app

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://t"
    ) as client:
        kinds = (await client.get(f"{API}/entities")).json()
        assert {k["key"] for k in kinds} == {"candidates", "companies", "managers", "jobs"}

        files = {"file": ("Kandidaten.csv", GERMAN_EXPORT, "text/csv")}
        preview = await client.post(
            f"{API}/preview", data={"entity": "candidates"}, files=files
        )
        assert preview.status_code == 200
        body = preview.json()
        assert body["counts"] == {"create": 2, "update": 0, "skip": 0}
        assert body["mapping"]["Vorname"] == "first_name"
        assert len(body["sample"]) == 2

        import json as jsonlib

        done = await client.post(
            f"{API}/commit",
            data={"entity": "candidates", "mapping": jsonlib.dumps(body["mapping"])},
            files={"file": ("Kandidaten.csv", GERMAN_EXPORT, "text/csv")},
        )
        assert done.status_code == 200
        assert done.json()["created"] == 2

        broken = await client.post(
            f"{API}/preview",
            data={"entity": "candidates"},
            files={"file": ("leer.csv", b"", "text/csv")},
        )
        assert broken.status_code == 400


def test_a_two_cell_title_row_is_not_mistaken_for_the_header() -> None:
    """Measured, not imagined: "Export Kandidaten;Stand 03.10.2026" has two
    filled cells, which beat the first version of this rule and turned every
    column into "Spalte 3". The header is the first row as WIDE as the data,
    not merely the first with more than one value."""
    raw = (
        "Export Kandidaten;Stand 03.10.2026;;;\r\n"
        "Vorname;Nachname;E-Mail;Position\r\n"
        "Jörg;Müller;j@example.de;Entwickler\r\n"
    ).encode("cp1252")
    sheet = parser.read("export.csv", raw)
    assert sheet.columns == ["Vorname", "Nachname", "E-Mail", "Position"]
    assert sheet.rows[0]["Vorname"] == "Jörg"


def test_a_file_with_no_title_row_loses_nothing() -> None:
    sheet = parser.read("x.csv", b"Vorname,Nachname\nAnna,Schmidt\nJan,Koch\n")
    assert sheet.columns == ["Vorname", "Nachname"]
    assert len(sheet.rows) == 2 and not sheet.problems
