#!/usr/bin/env python
"""Play out `data/examples/KandidatenInfo.txt` as a real mandate.

The document is one anonymised evaluation: a senior backend candidate against
"Senior Backend-Entwickler mit Architekturkenntnissen (Position 1) – GE
Software". Everything it contains — the Suchprofil, the person's
qualification data, the 8/10 assessment — exists in the record as fields
already; nothing of it was in the database, so there was nothing to click.

This creates exactly that: the client, the mandate, the (anonymous)
candidate, their process, and the Kandidatenauswertung. Then Jobs → the job
title → the cockpit's per-job view shows the whole thing.

    python -m scripts.seed_ge_example --tenant <uuid> [--dry-run] [--remove]

Idempotent: matched by name per tenant, so a re-run updates rather than
doubling. `--remove` deletes what it created, because a demo mandate you
cannot take out again is not a demo.

Two values are DERIVED rather than quoted, and both are flagged in the
output: the salary band (the document says the GE orientation is "~90k plus
minus" and that the Budgetrahmen is "nicht angegeben"), and the presentation
date (the Qualifikationsgespräch was 18.09.2026 and the document expects
client feedback "bis ~Dienstag", so the candidate is presented). Change both
in the Mandat editor if they are wrong.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import pathlib
import uuid

from sqlalchemy import select

from app.core.database import SessionLocal, current_tenant_var
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ApplicationStatus, DocumentKind, EmploymentForm
from app.domain.documents.models import CandidateDocument
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.pipeline import service as pipeline_service
from app.domain.pipeline.models import Application
from app.domain.registry import *  # noqa: F401,F403 — register every table
from scripts.import_assessment import parse_assessment

COMPANY = "GE Software"
JOB_TITLE = "Senior Backend-Entwickler mit Architekturkenntnissen (Position 1)"
#: The document is anonymised, so the record carries a handle instead of a
#: person: short, searchable, and obviously not a real name.
CANDIDATE = "AnonymGE"
#: What the row was called before the handle. Matched on re-run so the rename
#: moves the existing candidate instead of creating a second one.
LEGACY_CANDIDATE = "Senior Backend-Entwickler (anonymisiert)"

EXAMPLE = pathlib.Path(__file__).resolve().parents[2] / "data/examples/KandidatenInfo.txt"

#: Section D of the document, verbatim — the mandate's hard criteria.
MUST_HAVE = [
    "Java", "Jakarta EE/J2EE", "WildFly", "JBoss", "JPA/Hibernate", "REST",
    "Flyway/Liquibase", "GitLab CI/CD", "Oracle/PostgreSQL",
    "Microservices-Architektur",
]

#: Section B, "Technisches Know-how".
SKILLS = [
    "Java", "J2EE/Jakarta EE", "WildFly", "JBoss", "Weblogic", "GlassFish",
    "Tomcat", "Quarkus", "Spring Boot", "Hibernate", "JPA", "JSF", "React",
    "Angular", "TypeScript", "Oracle", "MySQL", "PostgreSQL", "Cassandra",
    "Elasticsearch", "Kafka", "Flyway/Liquibase", "GitLab CI/CD", "Docker",
    "Kubernetes", "Maven", "Git",
]

CANDIDATE_FIELDS = {
    "current_title": "Senior Software Entwickler / Software Architekt",
    "location": "Süddeutschland",
    "total_years_experience": "20+",
    "employment_form": EmploymentForm.FESTANSTELLUNG.value,
    "industries": ["Luftfahrt / Flugsicherung", "Behörden & Verteidigung"],
    "languages": ["Deutsch (Muttersprache)", "Englisch (verhandlungssicher)"],
    "education": [
        "Fachinformatiker Anwendungsentwicklung (IHK)",
        "Zertifizierter Enterprise Architect",
        "JBoss Certified Application Administrator",
        "Certified Java Programmer",
    ],
    "skills": SKILLS,
    "current_salary": 105000,
    "salary_minimum": 92000,
    "salary_expectation": 100000,
    "notice_period": "3 Monate zum Monatsende → Start ~Jahresanfang",
    "availability": "ab ~Jahresanfang",
    "interview_availability": "Mittwoch/Donnerstag ab ca. 11–12 Uhr, bis max. 18 Uhr",
    "other_processes": "Führt parallel mehrere Prozesse und Freelance-Optionen",
    "source": "kandidatenauswertung",
}

#: The CV stations, from section B. Employers are anonymised the same way the
#: document anonymises them — the domain is what matters for the match, and
#: inventing a company name would put an unverifiable claim on the record.
WORK_HISTORY = [
    {
        "title": "Senior Software Entwickler / Software Architekt",
        "company": "Luftfahrt-/AIS-Anbieter (anonymisiert)",
        "location": "Süddeutschland · remote",
        "start_date": "2018-01",
        "highlights": [
            "Architektur-Verantwortung für ein Fachteam; Interims-Teamlead (12–14 MA)",
            "Migration einer gewachsenen Swing/XML-Anwendung in eine Microservice-Architektur",
            "Umstellung Standalone → WildFly-Cluster (Payment), Vaadin → Angular",
            "NOTAM / Flugsicherung bis zur Eurocontrol-Abnahme",
            "Technisches Screening und Onboarding neuer Teammitglieder",
        ],
    },
    {
        "title": "Freiberuflicher Java-Entwickler und Architekt",
        "company": "Diverse Auftraggeber (anonymisiert)",
        "location": "Deutschland",
        "start_date": "2004-01",
        "end_date": "2017-12",
        "highlights": [
            "Enterprise-Anwendungen im behörden- und verteidigungsnahen Umfeld",
            "JBoss, Weblogic, GlassFish, Tomcat; OSGi-Implementierung",
            "Langjährige Projektverantwortung in sicherheitskritischen Domänen",
        ],
    },
    {
        "title": "Softwareentwickler",
        "company": "Mittelständischer IT-Dienstleister (anonymisiert)",
        "start_date": "2001-01",
        "end_date": "2003-12",
        "highlights": ["Ausbildung Fachinformatiker AE (IHK), anschließend Festanstellung"],
    },
]

MOTIVATION = (
    "Aktueller Arbeitgeber (Großkonzern, deutsche Division ~140 MA) mit schwachem "
    "Management; als Betriebsrat derzeit in konfliktreichen Verhandlungen. Die Firma "
    "verliert schrittweise Marktposition, eine Aufstiegs- und Gestaltungsperspektive "
    "fehlt. Gesucht werden kurze Wege, Gestaltungsspielraum und eine Aufgabe, die Spaß "
    "macht."
)

CV_FILENAME = "AnonymGE_CV_Kurzversion.html"


def eur(value: int) -> str:
    """90000 → "90.000 €" — German separators, so the mock reads like the UI."""
    return f"{value:,} €".replace(",", ".")


def cv_html() -> bytes:
    """The Kurz-CV as the document describes it — the evidence pane's left half.

    Stored as HTML rather than PDF on purpose: the drawer renders whatever the
    document's content type says, no dependency is added for a demo file, and
    the text stays greppable. The long version is the one the candidate
    offered and we do not have; the header says so instead of implying it.
    """
    stations = "".join(
        f"<section class='job'><h3>{w['title']}</h3>"
        f"<p class='meta'>{w['company']}"
        + (f" · {w['location']}" if w.get("location") else "")
        + f" · {w['start_date'][:4]}–{w.get('end_date', 'heute')[:4]}</p>"
        + "<ul>" + "".join(f"<li>{h}</li>" for h in w["highlights"]) + "</ul></section>"
        for w in WORK_HISTORY
    )
    skills = " · ".join(SKILLS)
    education = "".join(f"<li>{e}</li>" for e in CANDIDATE_FIELDS["education"])
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><title>{CANDIDATE} — Kurz-CV</title>
<style>
 body {{ font: 13px/1.55 -apple-system, Segoe UI, Roboto, sans-serif; color:#18201c;
        margin:0; padding:34px 40px; background:#fff; }}
 h1 {{ font-size:22px; margin:0 0 2px; letter-spacing:-.01em; }}
 .sub {{ color:#5d6b63; margin:0 0 4px; }}
 .flag {{ display:inline-block; margin:10px 0 18px; padding:3px 8px; border:1px solid #c9d8cf;
          border-radius:5px; background:#f3f8f5; color:#3d6b53; font-size:11px; }}
 h2 {{ font-size:11px; text-transform:uppercase; letter-spacing:.09em; color:#6c7a72;
       border-bottom:1px solid #e3e9e5; padding-bottom:4px; margin:22px 0 10px; }}
 h3 {{ font-size:14px; margin:0 0 1px; }}
 .meta {{ color:#6c7a72; margin:0 0 6px; font-size:12px; }}
 ul {{ margin:0 0 4px; padding-left:17px; }} li {{ margin:2px 0; }}
 .job {{ margin-bottom:14px; }}
 .grid {{ display:grid; grid-template-columns:150px 1fr; gap:4px 14px; }}
 .grid dt {{ color:#6c7a72; }} .grid dd {{ margin:0; }}
 .skills {{ color:#30403a; }}
</style></head><body>
<h1>{CANDIDATE}</h1>
<p class="sub">{CANDIDATE_FIELDS['current_title']} · {CANDIDATE_FIELDS['total_years_experience']} Jahre Erfahrung · {CANDIDATE_FIELDS['location']}</p>
<span class="flag">Kurzversion · anonymisiert · Kontakt über eligo · Langversion auf Anfrage</span>

<h2>Profil</h2>
<p>Senior Software Entwickler und Architekt mit über 20 Jahren Erfahrung in komplexen
Enterprise-Anwendungen. Schwerpunkt Java/J2EE bzw. Jakarta EE Full-Stack, Microservices
und Legacy-Modernisierung. Lange Freelancer-Historie, seit 2018 in Festanstellung in der
Luftfahrt-/AIS-Domäne, dort mit Architektur-Verantwortung und als Interims-Teamlead.</p>

<h2>Beruflicher Werdegang</h2>
{stations}

<h2>Technologien</h2>
<p class="skills">{skills}</p>

<h2>Ausbildung &amp; Zertifizierungen</h2>
<ul>{education}</ul>

<h2>Rahmen</h2>
<dl class="grid">
  <dt>Verfügbarkeit</dt><dd>{CANDIDATE_FIELDS['notice_period']}</dd>
  <dt>Gehalt</dt><dd>Minimum {eur(CANDIDATE_FIELDS['salary_minimum'])}, Wunsch {eur(CANDIDATE_FIELDS['salary_expectation'])} — verhandelbar, Stufenmodell denkbar</dd>
  <dt>Sprachen</dt><dd>{', '.join(CANDIDATE_FIELDS['languages'])}</dd>
  <dt>Arbeitsmodell</dt><dd>Remote-orientiert, monatliches Präsenzmodell machbar</dd>
</dl>
</body></html>""".encode("utf-8")

#: Derived, not quoted — see the module docstring.
SALARY_MIN, SALARY_MAX = 85000, 95000
PRESENTED_AT = dt.datetime(2026, 9, 18, tzinfo=dt.UTC)


async def _one(session, model, **where):
    return await session.scalar(select(model).filter_by(**where))


async def seed(tenant_id: uuid.UUID) -> dict:
    current_tenant_var.set(str(tenant_id))
    async with SessionLocal() as s:
        company = await _one(s, Company, tenant_id=tenant_id, name=COMPANY)
        if company is None:
            company = Company(
                tenant_id=tenant_id, name=COMPANY, is_client=True,
                source="kandidatenauswertung",
            )
            s.add(company)
            await s.flush()

        job = await _one(s, Job, tenant_id=tenant_id, title=JOB_TITLE)
        if job is None:
            job = Job(tenant_id=tenant_id, title=JOB_TITLE)
            s.add(job)
        job.client_company_id = company.id
        job.location = "München"
        job.must_have_skills = MUST_HAVE
        job.salary_min, job.salary_max = SALARY_MIN, SALARY_MAX
        job.salary_currency = "EUR"
        job.status = "open"
        await s.flush()

        candidate = await _one(s, Candidate, tenant_id=tenant_id, full_name=CANDIDATE)
        if candidate is None:
            # The row may still carry the pre-handle name — rename it rather
            # than leaving two anonymous seniors on the same mandate.
            candidate = await _one(
                s, Candidate, tenant_id=tenant_id, full_name=LEGACY_CANDIDATE
            )
        if candidate is None:
            candidate = Candidate(tenant_id=tenant_id, full_name=CANDIDATE)
            s.add(candidate)
        candidate.full_name = CANDIDATE
        for field, value in CANDIDATE_FIELDS.items():
            setattr(candidate, field, value)
        candidate.work_history = WORK_HISTORY
        candidate.motivation = MOTIVATION
        await s.flush()

        # The Kurz-CV, so the candidate's page has the evidence pane the rest
        # of the record is checked against. Replaced on re-run: a demo that
        # grows a new CV every time it is seeded is a demo nobody re-runs.
        cv = await _one(
            s, CandidateDocument, tenant_id=tenant_id,
            candidate_id=candidate.id, filename=CV_FILENAME,
        )
        body = cv_html()
        if cv is None:
            cv = CandidateDocument(
                tenant_id=tenant_id, candidate_id=candidate.id, filename=CV_FILENAME
            )
            s.add(cv)
        cv.kind = DocumentKind.CV.value
        cv.content_type = "text/html; charset=utf-8"
        cv.content = body
        cv.byte_size = len(body)
        await s.flush()

        application = await _one(
            s, Application, tenant_id=tenant_id,
            candidate_id=candidate.id, job_id=job.id,
        )
        if application is None:
            application = Application(
                tenant_id=tenant_id, candidate_id=candidate.id, job_id=job.id,
                status=ApplicationStatus.PRESENTED,
            )
            s.add(application)
        await s.commit()
        app_id, job_id, candidate_id = application.id, job.id, candidate.id

        # Section B's profile summary belongs on the person, not the mandate.
        parsed = parse_assessment(EXAMPLE.read_text(encoding="utf-8"))
        for field, value in parsed["candidate"].items():
            setattr(candidate, field, value)
        await s.commit()

        await pipeline_service.set_step(
            s, tenant_id=tenant_id, application_id=app_id,
            step_key="vorgestellt", done_at=PRESENTED_AT, outcome="pass",
            actor="seed_ge_example",
        )
        await pipeline_service.set_assessment(
            s, tenant_id=tenant_id, application_id=app_id, **parsed["assessment"]
        )

    return {
        "job_id": str(job_id),
        "candidate_id": str(candidate_id),
        "application": str(app_id),
        "cv_bytes": len(body),
        "fit_score": parsed["assessment"]["fit_score"],
        "strengths": len(parsed["assessment"]["strengths"]),
        "risks": len(parsed["assessment"]["risks"]),
    }


async def remove(tenant_id: uuid.UUID) -> dict:
    """Take it out again — rows first, then the client."""
    current_tenant_var.set(str(tenant_id))
    removed = {"applications": 0, "jobs": 0, "candidates": 0, "companies": 0}
    async with SessionLocal() as s:
        job = await _one(s, Job, tenant_id=tenant_id, title=JOB_TITLE)
        candidate = await _one(
            s, Candidate, tenant_id=tenant_id, full_name=CANDIDATE
        ) or await _one(s, Candidate, tenant_id=tenant_id, full_name=LEGACY_CANDIDATE)
        if job is not None:
            apps = (
                await s.execute(
                    select(Application).where(
                        Application.tenant_id == tenant_id,
                        Application.job_id == job.id,
                    )
                )
            ).scalars().all()
            for application in apps:
                await s.delete(application)  # steps + assessment cascade
                removed["applications"] += 1
            await s.flush()
            await s.delete(job)
            removed["jobs"] += 1
        if candidate is not None:
            docs = (
                await s.execute(
                    select(CandidateDocument).where(
                        CandidateDocument.tenant_id == tenant_id,
                        CandidateDocument.candidate_id == candidate.id,
                    )
                )
            ).scalars().all()
            for doc in docs:
                await s.delete(doc)
                removed["documents"] = removed.get("documents", 0) + 1
            await s.flush()
            await s.delete(candidate)
            removed["candidates"] += 1
        company = await _one(s, Company, tenant_id=tenant_id, name=COMPANY)
        if company is not None:
            await s.delete(company)
            removed["companies"] += 1
        await s.commit()
    return removed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tenant", type=uuid.UUID, required=True)
    ap.add_argument("--remove", action="store_true", help="delete what this created")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not EXAMPLE.exists():
        raise SystemExit(f"{EXAMPLE} not found")

    if args.dry_run:
        parsed = parse_assessment(EXAMPLE.read_text(encoding="utf-8"))
        print(f"würde anlegen: {COMPANY} · {JOB_TITLE}")
        print(f"  Kandidat: {CANDIDATE} (vorher: {LEGACY_CANDIDATE})")
        print(f"  CV: {CV_FILENAME}, {len(cv_html())} Bytes, {len(WORK_HISTORY)} Stationen")
        print(f"  Muss-Kriterien: {', '.join(MUST_HAVE)}")
        print(f"  Band: {SALARY_MIN}–{SALARY_MAX} € (abgeleitet aus „~90k plus minus“)")
        print(f"  Bewertung: {parsed['assessment']['fit_score']}/10, "
              f"{len(parsed['assessment']['strengths'])} Stärken, "
              f"{len(parsed['assessment']['risks'])} Risiken")
        return

    if args.remove:
        print("entfernt:", asyncio.run(remove(args.tenant)))
        return

    result = asyncio.run(seed(args.tenant))
    print("angelegt:", result)
    print(f"  → Cockpit:  #cockpit/{result['job_id']}")
    print(f"  → Kandidat: #kandidaten/{result['candidate_id']}")


if __name__ == "__main__":
    main()
