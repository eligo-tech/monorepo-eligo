"""Import a Kandidatenauswertung (`data/examples/KandidatenInfo.txt`) onto one
candidate's run at one mandate.

The document is the recruiter's own template, four sections deep:

    A. Passungsbewertung zur Position      → the assessment (per application)
    B. Gesprächszusammenfassung            → the CANDIDATE's own columns
    C. Kandidatenzusammenfassung für den Kunden → the client-facing text
    D. Relevante Technologien              → the technology list

Only A/C/D are per-mandate; B describes the person and therefore lands on
`candidates`, where it holds for every mandate they run on.

**The application is named, never guessed.** The example document is
anonymised ("GE Software", "Position 1") and the real tracker holds real
people; matching it onto a candidate by resemblance would attach invented
claims — "Betriebsrat in Konfrontation mit dem Management" — to a named
person. So the company, job and candidate are arguments, and the script fails
if they do not already exist.

    python -m scripts.import_assessment --file data/examples/KandidatenInfo.txt \\
        --tenant <uuid> --company "EM Software" --job "Java Dev" \\
        --candidate "<name>" [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import pathlib
import re
import uuid

from sqlalchemy import select

from app.core.database import SessionLocal, current_tenant_var
from app.domain.candidates.models import Candidate
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.pipeline import service as pipeline_service
from app.domain.pipeline.models import Application
from app.domain.registry import *  # noqa: F401,F403 — register every table

#: "Gesamtbewertung: 8 / 10" — the score, on the document's own scale.
SCORE = re.compile(r"Gesamtbewertung:\s*(\d{1,2})\s*/\s*10")
#: "Grundlage: CV (Kurzversion) + Gesprächstranskript (18.09.2026)"
BASIS = re.compile(r"^Grundlage:\s*(.+)$", re.MULTILINE)
GERMAN_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")

#: Section headings, as the template writes them. Matched at the start of a
#: line so a mention inside a paragraph cannot split the document.
_SECTIONS = (
    ("A", re.compile(r"^A\.\s", re.MULTILINE)),
    ("B", re.compile(r"^B\.\s", re.MULTILINE)),
    ("C", re.compile(r"^C\.\s", re.MULTILINE)),
    ("D", re.compile(r"^D\.\s", re.MULTILINE)),
)

#: Labelled lines of section B → the candidate column each belongs in.
#: Everything here describes the PERSON, not their fit for one position.
_B_FIELDS: dict[str, str] = {
    "Zusammenfassung des Profils": "profile_summary",
    "Kündigungsfrist / Verfügbarkeit": "notice_period",
    "Wechselmotivation": "motivation",
    "Verfügbarkeit für Interviews": "interview_availability",
}


def _split_sections(text: str) -> dict[str, str]:
    """The document as {"A": …, "B": …, "C": …, "D": …}, text before A dropped."""
    marks: list[tuple[str, int]] = []
    for name, pattern in _SECTIONS:
        match = pattern.search(text)
        if match:
            marks.append((name, match.start()))
    marks.sort(key=lambda m: m[1])
    out: dict[str, str] = {}
    for index, (name, start) in enumerate(marks):
        end = marks[index + 1][1] if index + 1 < len(marks) else len(text)
        out[name] = text[start:end].strip()
    return out


def _lines_between(block: str, start_label: str, stop_labels: tuple[str, ...]) -> list[str]:
    """The bullet lines under `start_label:` up to the next labelled line.

    The template writes its lists as one item per line with no bullet
    character, so the terminator is the next label rather than a marker.
    """
    out: list[str] = []
    collecting = False
    for raw in block.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.rstrip(":") == start_label:
            collecting = True
            continue
        if collecting:
            if any(line.startswith(stop) for stop in stop_labels):
                break
            out.append(line)
    return out


def _labelled(block: str, label: str) -> str | None:
    """The text after `Label:` — the paragraph it introduces, one line."""
    for raw in block.splitlines():
        line = raw.strip()
        if line.startswith(f"{label}:"):
            value = line.split(":", 1)[1].strip()
            return value or None
    return None


def parse_assessment(text: str) -> dict:
    """The document as data. Pure: takes the text, returns what to store.

    Unknown or missing sections come back empty rather than raising — a
    recruiter's file that stops after section A is still worth importing, and
    a parser that insists on all four would simply never be used.
    """
    sections = _split_sections(text)
    a, b = sections.get("A", ""), sections.get("B", "")

    score = SCORE.search(a)
    basis_match = BASIS.search(text)
    basis = basis_match.group(1).strip() if basis_match else None
    assessed_at = None
    if basis:
        date = GERMAN_DATE.search(basis)
        if date:
            day, month, year = (int(g) for g in date.groups())
            assessed_at = dt.datetime(year, month, day, tzinfo=dt.UTC)

    # The Kurzfazit is the headline; the "Fachliche & professionelle Passung"
    # paragraph is the same verdict argued out. Both are section A's prose and
    # are kept together — splitting them across fields would leave the cockpit
    # showing a conclusion with its reasoning elsewhere.
    verdict_parts = [
        part
        for part in (
            _labelled(a, "Kurzfazit"),
            _labelled(a, "Fachliche & professionelle Passung"),
        )
        if part
    ]

    technologies = [
        tech.strip()
        for tech in re.split(r"[,;]", _technology_text(sections.get("D", "")))
        if tech.strip()
    ]

    return {
        "assessment": {
            "fit_score": int(score.group(1)) if score else None,
            "verdict": "\n\n".join(verdict_parts) or None,
            "strengths": _lines_between(a, "Stärken", ("Lücken/Risiken",)),
            "risks": _lines_between(
                a, "Lücken/Risiken", ("Fachliche & professionelle Passung",)
            ),
            "client_summary": _client_summary(sections.get("C", "")),
            "technologies": technologies,
            "basis": basis,
            "assessed_at": assessed_at,
        },
        "candidate": {
            field: value
            for label, field in _B_FIELDS.items()
            if (value := _labelled(b, label))
        },
    }


def _body(block: str) -> str:
    """A section without its heading line."""
    lines = block.splitlines()
    return "\n".join(line.strip() for line in lines[1:] if line.strip())


def _client_summary(block: str) -> str | None:
    return _body(block) or None


def _technology_text(block: str) -> str:
    return _body(block)


async def load(
    parsed: dict,
    *,
    tenant_id: uuid.UUID,
    company: str,
    job: str,
    candidate: str,
) -> dict:
    """Write the parsed document onto an EXISTING application."""
    current_tenant_var.set(str(tenant_id))
    async with SessionLocal() as session:
        company_row = await session.scalar(
            select(Company).where(
                Company.tenant_id == tenant_id, Company.name == company
            )
        )
        if company_row is None:
            raise SystemExit(f"no company named {company!r} for this tenant")
        job_row = await session.scalar(
            select(Job).where(
                Job.tenant_id == tenant_id,
                Job.title == job,
                Job.client_company_id == company_row.id,
            )
        )
        if job_row is None:
            raise SystemExit(f"no mandate {job!r} at {company!r}")
        candidate_row = await session.scalar(
            select(Candidate).where(
                Candidate.tenant_id == tenant_id, Candidate.full_name == candidate
            )
        )
        if candidate_row is None:
            raise SystemExit(f"no candidate named {candidate!r} for this tenant")
        application = await session.scalar(
            select(Application).where(
                Application.tenant_id == tenant_id,
                Application.candidate_id == candidate_row.id,
                Application.job_id == job_row.id,
            )
        )
        if application is None:
            raise SystemExit(f"{candidate!r} is not running on {job!r} at {company!r}")

        for field, value in parsed["candidate"].items():
            setattr(candidate_row, field, value)
        await session.commit()

        await pipeline_service.set_assessment(
            session,
            tenant_id=tenant_id,
            application_id=application.id,
            **parsed["assessment"],
        )
    return {
        "application": str(application.id),
        "candidate_fields": sorted(parsed["candidate"]),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", type=pathlib.Path, required=True)
    ap.add_argument("--tenant", type=uuid.UUID, required=True)
    ap.add_argument("--company", required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    parsed = parse_assessment(args.file.read_text(encoding="utf-8"))
    a = parsed["assessment"]
    print(f"Bewertung {a['fit_score']}/10 · {len(a['strengths'])} Stärken · "
          f"{len(a['risks'])} Risiken · {len(a['technologies'])} Technologien")
    print(f"Grundlage: {a['basis']}")
    print(f"Kandidatenfelder: {', '.join(sorted(parsed['candidate'])) or '—'}")
    if args.dry_run:
        return
    result = asyncio.run(
        load(
            parsed,
            tenant_id=args.tenant,
            company=args.company,
            job=args.job,
            candidate=args.candidate,
        )
    )
    print(f"geschrieben auf application {result['application']}")


if __name__ == "__main__":
    main()
