"""Import a Kandidatenauswertung (`data/examples/KandidatenInfo.txt`) onto one
candidate's run at one mandate.

The document is the recruiter's own template, four sections deep:

    A. Passungsbewertung zur Position      → the assessment (per application)
    B. Gesprächszusammenfassung            → the CANDIDATE's own columns
    C. Kandidatenzusammenfassung für den Kunden → the client-facing text
    D. Relevante Technologien              → the technology list

Only A/C/D are per-mandate; B describes the person and therefore lands on
`candidates`, where it holds for every mandate they run on.

The parsing itself is `app.domain.pipeline.auswertung.parse_auswertung` — the
same pure function the cockpit's paste box calls, so a document imported from
a file and one pasted into the form are read identically.

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
import pathlib
import uuid

from sqlalchemy import select

from app.core.database import SessionLocal, current_tenant_var
from app.domain.candidates.models import Candidate
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.pipeline import service as pipeline_service
from app.domain.pipeline.auswertung import parse_auswertung
from app.domain.pipeline.models import Application
from app.domain.registry import *  # noqa: F401,F403 — register every table


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

    parsed = parse_auswertung(args.file.read_text(encoding="utf-8"))
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
