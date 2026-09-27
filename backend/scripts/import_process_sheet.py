"""Import the recruiter's tracker (docs/process_design/*.docx) into the record.

The tracker is a spreadsheet pasted into a Word file. Its shape, decoded from
the cells and their FILL COLOURS rather than from headers (four of the ten
columns have none):

    col 0  date presented            "25.08."
    col 1  candidate name            "Mariana Melnychenko"
    col 2  free note                 "IAM"
    col 3  client verdict            green = through, red = out
    col 4  interview                 "09.09. um 11 Uhr"
    col 5  verdict after interview   green / red
    col 6  interview (final)         "24.09. um 10 Uhr"
    col 7  verdict after final       green / red
    col 9  further interview ("IvT") "22.09. um 8:30 Uhr"

Rows with a lone cell in col 0 are structure — either a company
("Computacenter") or a mandate under it ("ServiceNow"). **The file does not
say which.** Both are bold, same size, same indent; blank rows do not separate
them either (a blank precedes the mandate "Site Manager 1618" but not the
company "Sixt"). So the company names are passed in with `--company` and
everything else is a mandate, and the parse prints the tree it built for you
to check. Guessing here would silently invent client relationships.

Dates carry no year — the sheet is the current season — so they take
`--year`, defaulting to the current one. Times are German local time ("09.09.
um 11 Uhr" is 11:00 in Berlin), so they are localised there and stored as the
UTC instant; storing 11:00 UTC would move every appointment two hours.

Idempotent: companies, jobs, candidates and applications are matched by name
per tenant and updated, never duplicated, so a re-run after fixing a cell
changes that cell only.

    python -m scripts.import_process_sheet --docx docs/process_design/X.docx \\
        --tenant <uuid> [--year 2026] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import pathlib
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.database import SessionLocal, current_tenant_var
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ApplicationStatus
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.pipeline import service as pipeline_service
from app.domain.pipeline.models import Application
from app.domain.registry import *  # noqa: F401,F403 — register every table

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
GREEN, RED = "6aa84f", "e06666"
#: The tracker is kept by a German recruiter: its clock is Berlin's.
BERLIN = ZoneInfo("Europe/Berlin")
DATE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.?$")
#: "09.09. um 11 Uhr", "23.09. 15:00 Uhr", "22.09 um 16:30 Uhr vor Ort"
APPOINTMENT = re.compile(
    r"^(\d{1,2})\.(\d{1,2})\.?\s*(?:um\s*)?(?:(\d{1,2})(?::(\d{2}))?\s*Uhr)?\s*(.*)$"
)
#: Which tracker column feeds which step, and which verdict follows it.
APPOINTMENT_COLUMNS = {4: ("interview", 5), 6: ("finaltermin", 7), 9: ("interviewtermin_3", None)}

#: The companies in the tracker as pasted (docs/process_design, Sept 2026).
#: A default, not a rule: override with --company for a different sheet.
DEFAULT_COMPANIES = (
    "EM Software", "GOSA", "SSI", "KVB", "Computacenter", "Sixt", "KurtzErsa",
)


def _cell_text(tc: ET.Element) -> str:
    return "".join(n.text or "" for n in tc.iter(f"{W}t")).strip()


def _cell_fill(tc: ET.Element) -> str | None:
    shd = tc.find(f".//{W}shd")
    fill = shd.get(f"{W}fill") if shd is not None else None
    return fill if fill in (GREEN, RED) else None


def _verdict(fill: str | None) -> str:
    return {GREEN: "pass", RED: "out"}.get(fill or "", "open")


def _date(value: str, year: int) -> dt.datetime | None:
    m = DATE.match(value.strip())
    if not m:
        return None
    # A date with no time: midnight in Berlin, not in UTC, so it still reads
    # as that date for the person who wrote it.
    return dt.datetime(year, int(m.group(2)), int(m.group(1)), tzinfo=BERLIN).astimezone(dt.UTC)


def _appointment(value: str, year: int) -> tuple[dt.datetime | None, str | None]:
    """("22.09 um 16:30 Uhr vor Ort") → (datetime, "vor Ort")."""
    m = APPOINTMENT.match(value.strip())
    if not m:
        return None, value.strip() or None
    day, month, hour, minute, rest = m.groups()
    when = dt.datetime(
        year, int(month), int(day), int(hour or 0), int(minute or 0), tzinfo=BERLIN
    ).astimezone(dt.UTC)
    return when, (rest.strip() or None)


def parse_sheet(
    docx: pathlib.Path, *, year: int, companies: tuple[str, ...] = DEFAULT_COMPANIES
) -> list[dict]:
    """The tracker as rows: company → job → candidate with their steps.

    Pure: takes a file, returns data. The DB half below can then be read on
    its own, and this half tested against the real document.
    """
    with zipfile.ZipFile(docx) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    tables = list(root.iter(f"{W}tbl"))
    if not tables:
        return []
    table = tables[-1]  # the pasted sheet is the last table in the document

    known = {c.casefold() for c in companies}
    out: list[dict] = []
    company = job = None
    for tr in table.findall(f"{W}tr"):
        cells = tr.findall(f"{W}tc")
        text = [_cell_text(tc) for tc in cells]
        fills = [_cell_fill(tc) for tc in cells]
        first, name = (text + ["", ""])[:2]

        if not any(t for t in text):
            continue
        if name == "Name":
            # The header row, which also carries the first company in col 0.
            company, job = first or None, None
            continue
        if first and not name and not DATE.match(first):
            if first.casefold() in known:
                company, job = first, None
            else:
                job = first
            continue
        if not name:
            continue

        presented = _date(first, year) if first else None
        steps: list[dict] = [
            {
                "step_key": "vorgestellt",
                "done_at": presented,
                "outcome": "pass" if presented else "open",
            },
            {"step_key": "feedback-1", "outcome": _verdict(fills[3] if len(fills) > 3 else None)},
        ]
        for col, (step_key, verdict_col) in APPOINTMENT_COLUMNS.items():
            value = text[col] if len(text) > col else ""
            if not value:
                continue
            when, note = _appointment(value, year)
            steps.append(
                {
                    "step_key": step_key,
                    "scheduled_at": when,
                    "note": note,
                    "outcome": "open",
                }
            )
            if verdict_col is not None and len(fills) > verdict_col:
                verdict = _verdict(fills[verdict_col])
                if verdict != "open":
                    # The colour belongs to the appointment it follows, so it
                    # marks that step's outcome. Where the nine steps also have
                    # a feedback step for that round, it carries the same
                    # verdict. A green cell after the FINAL interview is not an
                    # offer — the sheet has no offer column, and inventing one
                    # would claim something the recruiter never wrote down.
                    steps[-1]["outcome"] = verdict
                    if step_key == "interview":
                        steps.append({"step_key": "feedback-2", "outcome": verdict})
        out.append(
            {
                "company": company,
                "job": job or company,  # a company without a named mandate
                "candidate": name,
                "note": (text[2] if len(text) > 2 else "") or None,
                "steps": [s for s in steps if s.get("outcome") != "open" or s.get("scheduled_at") or s.get("done_at")],
            }
        )
    return out


async def _upsert(session, model, *, tenant_id: uuid.UUID, name_field: str, name: str, **extra):
    """Match by name within the tenant so a re-run updates instead of doubling."""
    column = getattr(model, name_field)
    row = await session.scalar(
        select(model).where(model.tenant_id == tenant_id, column == name)
    )
    if row is None:
        row = model(tenant_id=tenant_id, **{name_field: name}, **extra)
        session.add(row)
        await session.flush()
    return row


async def load(rows: list[dict], *, tenant_id: uuid.UUID) -> dict[str, int]:
    counts = {"companies": 0, "jobs": 0, "candidates": 0, "applications": 0, "steps": 0}
    current_tenant_var.set(str(tenant_id))
    async with SessionLocal() as session:
        for row in rows:
            company = await _upsert(
                session, Company, tenant_id=tenant_id, name_field="name",
                name=row["company"], is_client=True, source="process_sheet",
            )
            job = await _upsert(
                session, Job, tenant_id=tenant_id, name_field="title",
                name=row["job"], client_company_id=company.id,
            )
            candidate = await _upsert(
                session, Candidate, tenant_id=tenant_id, name_field="full_name",
                name=row["candidate"], source="process_sheet",
            )
            counts["companies"] += 1
            counts["jobs"] += 1
            counts["candidates"] += 1

            application = await session.scalar(
                select(Application).where(
                    Application.tenant_id == tenant_id,
                    Application.candidate_id == candidate.id,
                    Application.job_id == job.id,
                )
            )
            if application is None:
                application = Application(
                    tenant_id=tenant_id,
                    candidate_id=candidate.id,
                    job_id=job.id,
                    status=ApplicationStatus.PRESENTED,
                )
                session.add(application)
                await session.flush()
            if row["note"]:
                application.notes = row["note"]
            counts["applications"] += 1
            await session.commit()

            for step in row["steps"]:
                await pipeline_service.set_step(
                    session,
                    tenant_id=tenant_id,
                    application_id=application.id,
                    actor="process_sheet_import",
                    **step,
                )
                counts["steps"] += 1
    return counts


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docx", required=True, type=pathlib.Path)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--year", type=int, default=dt.date.today().year)
    parser.add_argument(
        "--company",
        action="append",
        default=[],
        help="a company heading in the sheet; repeatable. Defaults to the seven "
        "in docs/process_design. Everything else is read as a mandate.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print what would be written"
    )
    args = parser.parse_args()

    rows = parse_sheet(
        args.docx,
        year=args.year,
        companies=tuple(args.company) or DEFAULT_COMPANIES,
    )
    print(f"parsed {len(rows)} candidate rows from {args.docx.name}")
    for row in rows:
        marks = " ".join(
            f"{s['step_key']}"
            + (f"={s['outcome']}" if s.get("outcome") != "open" else "")
            + (f"@{s['scheduled_at']:%d.%m. %H:%M}" if s.get("scheduled_at") else "")
            for s in row["steps"]
        )
        print(f"  {row['company']:<16} {row['job']:<20} {row['candidate']:<24} {marks}")
    if args.dry_run:
        return 0

    counts = await load(rows, tenant_id=uuid.UUID(args.tenant))
    print(f"written: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
