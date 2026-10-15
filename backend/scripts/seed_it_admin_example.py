#!/usr/bin/env python
"""One mandate, three candidates: the IT-Administrator role at Linde + Wiemann.

Three Gesprächsnotizen from 08.10.2026 (Thomas Bausch, Panam Partners) all
describe the SAME vacancy — the IT/OT interface in a production environment at
Dillenburg, 60–70k in the Metalltarif, two days of home office. They are the
shape the product is for: a mandate with its candidates hanging off it, each
one carrying what the call actually produced.

    python -m scripts.seed_it_admin_example --tenant <uuid> [--dry-run] [--remove]

Idempotent: matched by name per tenant, so a re-run updates rather than
doubling. `--remove` takes it out again.

Three readings worth stating, because each one could be wrong:

1. **The client is Linde + Wiemann in Dillenburg, not Linde Gas.** The notes
   write "Linde & Wietmann" and "Linde". The workspace already holds "Linde
   Gas Deutschland - Pullach", which is a different company (industrial gases,
   Munich). Metalltarif, produktionsnahe IT/OT, MES, Shop Floor and Dillenburg
   all point at the automotive metal former. A new client row is created
   rather than hanging this mandate off the gas company.

2. **The CV facts in the Celik note belong to Celik, not to the recruiter.**
   Gemini labelled every sentence of that transcript "Thomas Bausch",
   including "wohnt in Naurot" and the whole Werdegang. Bausch is the
   recruiter in all three notes and the invitee is nesim.celik@hotmail.de, so
   the career belongs to the candidate. If that reading is wrong, this script
   has attached one person's CV to another, which is why it says so here.

3. **Nothing is invented.** Only what the notes state is written down. Where a
   note is silent — Fink's stack, Sehr's location, anybody's interview window
   — the field stays empty instead of being filled with something plausible.
   An empty field is readable as "not asked yet"; a plausible one is not.

The fit scores ARE a judgement, and the basis line says so: they rank the
three against the band and the commute the notes describe, which is the one
thing all three calls have in common.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import uuid

from sqlalchemy import select

from app.core.database import SessionLocal, current_tenant_var
from app.domain.candidates import service as candidates_service
from app.domain.candidates.models import Candidate
from app.domain.common.enums import (
    ApplicationStatus,
    ConfidenceSource,
    EmploymentForm,
    InteractionType,
)
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.managers.models import ManagerInteraction
from app.domain.pipeline import service as pipeline_service
from app.domain.pipeline.models import Application
from app.domain.registry import *  # noqa: F401,F403 — register every table
from app.domain.verification import service as verification
from app.domain.verification.schemas import ProposedChange

COMPANY = "Linde + Wiemann"
JOB_TITLE = "IT-Administrator produktionsnahe IT / OT (m/w/d)"
#: The day all three conversations happened.
CALLED_ON = dt.datetime(2026, 10, 8, 12, 0, tzinfo=dt.UTC)
BASIS = "Gesprächsnotiz 08.10.2026"

#: Stated outright: "Metalltarifrahmen von 60.000 bis 70.000 Euro".
SALARY_MIN, SALARY_MAX = 60000, 70000

#: One hard criterion, because the notes name exactly one thing the role is
#: defined by. The rest of the task list is the briefing, not a filter — a
#: must-have invented here would silently exclude people.
MUST_HAVE = ["Produktionsnahe IT (OT)"]

BRIEFING = (
    "Vakanz Linde + Wiemann, Standort Dillenburg: Schnittstelle zwischen IT und "
    "Betriebstechnik (OT) im produktionsnahen Umfeld.\n"
    "Aufgaben: Betreuung der produktionsnahen IT, Rückverfolgbarkeit, Maschinendaten, "
    "MES-Unterstützung, Backup-Strukturen, Patch-Management im OT-Umfeld, globales "
    "Remote Maintenance System, Shop Floor und Mobile Device Management.\n"
    "Gehalt: Zielkorridor 60.000–70.000 € im Metalltarifrahmen; für ideale "
    "Kandidaturen geringer Spielraum.\n"
    "Homeoffice: vertraglich zwei Tage pro Woche. Der Head of IT agiert flexibel — "
    "bei größerer Entfernung ist auch ein Präsenztag pro Woche vereinbar, während "
    "der Einarbeitung temporär drei bis vier Präsenztage.\n"
    "Hinweis aus den Gesprächen: Einsparungen bei Arbeitsweg und Homeoffice können "
    "in der Gehaltsverhandlung berücksichtigt werden. Bei großer Entfernung kann die "
    "Personalabteilung trotz flexibler IT-Leitung Fragen aufwerfen.\n"
    "(Zusammengetragen aus den drei Qualifikationsgesprächen vom 08.10.2026.)"
)

#: Each candidate: the columns the note fills, the assessment, and the call
#: record. `None` and `[]` mean the note is silent — see reading 3 above.
CANDIDATES: list[dict] = [
    {
        "full_name": "Nesim Celik",
        "fields": {
            "email": "nesim.celik@hotmail.de",
            "city": "Naurot",
            "current_title": "Workplace-Manager",
            "current_company": "Coaching Company, Kreuztal",
            "employment_form": EmploymentForm.FESTANSTELLUNG.value,
            "notice_period": "3 Monate zum Monatsende",
            "salary_expectation": 70000,
            "focus_areas": [
                "IT- und OT-Systeme",
                "Device-Management",
                "Change- und Problem-Management",
                "Second- und Third-Level-Support",
            ],
            "technical_profile": (
                "Kernprofil: IT- und OT-Systeme, Device-Management, Change- und "
                "Problem-Management, Second- und Third-Level-Support. Cloud-Themen "
                "benennt der Kandidat selbst als Entwicklungsfeld — die "
                "Weiterbildungsmöglichkeiten beim aktuellen Arbeitgeber wurden "
                "wirtschaftsbedingt gestrichen. Frühere Zertifizierungen sind "
                "abgelaufen, die Bereitschaft sie nachzuholen besteht."
            ),
            "education": [
                "Fachhochschulreife IT, Schwerpunkt Anwendungsentwicklung",
                "Ausbildung zum Fachinformatiker Systemintegration",
            ],
            "profile_summary": (
                "Workplace-Manager, seit rund zweieinhalb Jahren bei der Coaching "
                "Company in Kreuztal, dort von Telefonmontage über Serverwartung bis "
                "zur Dienstleisterkommunikation zuständig. Kernprofil IT- und "
                "OT-Systeme, Device-Management, Change- und Problem-Management sowie "
                "Second- und Third-Level-Support — die OT-Nähe, um die es in dieser "
                "Vakanz geht, bringt er also bereits mit. Weg zur neuen Stelle ist "
                "das entscheidende Motiv."
            ),
            "motivation": (
                "Räumliche Nähe ist das ausdrückliche Hauptmotiv: wohnt in Naurot, "
                "pendelt aktuell nach Kreuztal, mit hohen Fahrtkosten durch die "
                "Kraftstoffpreise. Die vertraglichen zwei Homeoffice-Tage plus die "
                "Flexibilität der IT-Leitung sind damit ein direkter Vorteil."
            ),
            "work_history": [
                {
                    "title": "Workplace-Manager",
                    "company": "Coaching Company, Kreuztal",
                    "period": "seit ca. 2024 (2,5 Jahre)",
                    "summary": (
                        "Von Telefonmontage über Serverwartung bis zur "
                        "Dienstleisterkommunikation."
                    ),
                },
                {
                    "title": "IT (Zwei-Personen-Team)",
                    "company": "Guntermann & Drunck",
                    "period": "kurze Station",
                    "summary": "Zwei-Personen-IT; das Unternehmen kurzfristig wieder verlassen.",
                },
                {
                    "title": "IT-Techniker im Außendienst",
                    "company": "Netgo GmbH",
                    "period": "erste Station nach der Ausbildung",
                    "summary": "Außendienst mit längeren Abwesenheiten von zu Hause.",
                },
                {
                    "title": "Maschinenanlagenführer / CNC-Fräser",
                    "company": "vor der IT-Ausbildung",
                    "period": "—",
                    "summary": "Produktionsnahe Tätigkeit vor der Ausbildung zum Systemintegrator.",
                },
            ],
            "other_notes": (
                "Kommunikation: Telefon bevorzugt — formelle Meetings sind im "
                "Arbeitsalltag schwer unterzubringen.\n"
                "Bereitschaft zu zeitnahen Schritten und Vorstellungsgesprächen.\n"
                "Stellenbeschreibung Linde + Wiemann wurde übermittelt; Feedback bis "
                "Mitte der kommenden Woche zugesagt.\n"
                "Einsparungen beim Arbeitsweg können in der Gehaltsverhandlung "
                "berücksichtigt werden."
            ),
        },
        "assessment": {
            "fit_score": 8,
            "verdict": (
                "Der inhaltlich beste Treffer der drei: IT- UND OT-Systeme stehen "
                "bereits im Kernprofil, dazu Device-Management und Second-/Third-Level "
                "— genau die Schnittstelle, die die Vakanz beschreibt. Der Arbeitsweg "
                "spricht für ihn, nicht gegen ihn. Die beiden Vorbehalte sind "
                "kaufmännisch, nicht fachlich: das Zielgehalt liegt mit 70.000 € am "
                "oberen Rand des Tarifkorridors, und drei Monate Kündigungsfrist zum "
                "Monatsende verschieben den Start deutlich nach hinten."
            ),
            "strengths": [
                "IT- und OT-Systeme bereits im Kernprofil — die Schnittstelle der Vakanz",
                "Device-Management sowie Change- und Problem-Management benannt",
                "Second- und Third-Level-Support aus dem laufenden Betrieb",
                "Produktionsnähe aus früherer Tätigkeit als Maschinenanlagenführer/CNC-Fräser",
                "Räumliche Nähe ist sein eigenes Hauptmotiv — Bindung statt Pendelrisiko",
            ],
            "risks": [
                "Zielgehalt 70.000 € = Obergrenze des Metalltarifrahmens, wenig Spielraum",
                "Kündigungsfrist 3 Monate zum Monatsende → späterer Start als bei den anderen",
                "Cloud-Themen vom Kandidaten selbst als Entwicklungsfeld benannt",
                "Zertifizierungen abgelaufen (Bereitschaft zum Nachholen besteht)",
            ],
            "client_summary": (
                "Der Kandidat arbeitet seit zweieinhalb Jahren als Workplace-Manager "
                "und deckt dort die ganze Breite ab — von der Telefonmontage über die "
                "Serverwartung bis zur Steuerung externer Dienstleister. Sein "
                "Kernprofil nennt IT- und OT-Systeme in einem Atemzug, dazu "
                "Device-Management, Change- und Problem-Management sowie Second- und "
                "Third-Level-Support; die Schnittstelle zwischen Informationstechnologie "
                "und Betriebstechnik, um die es in dieser Position geht, ist für ihn "
                "also kein Neuland. Vor der IT-Ausbildung war er Maschinenanlagenführer "
                "und CNC-Fräser, kennt das produktionsnahe Umfeld also auch von der "
                "anderen Seite. Die räumliche Nähe zum Standort ist sein ausdrückliches "
                "Hauptmotiv für den Wechsel."
            ),
            "technologies": [
                "IT-/OT-Systeme",
                "Device-Management",
                "Change-Management",
                "Problem-Management",
                "Second-/Third-Level-Support",
                "Serverwartung",
            ],
        },
        "call": (
            "Kandidat: Qualifikationsgespräch 08.10.2026 (Gesprächsnotiz).\n"
            "Motiv ist die räumliche Nähe — pendelt aktuell von Naurot nach Kreuztal, "
            "hohe Fahrtkosten. Zielgehalt 70.000 €. Kündigungsfrist 3 Monate zum "
            "Monatsende. Werdegang: Fachhochschulreife IT, Maschinenanlagenführer/"
            "CNC-Fräser, Ausbildung Systemintegration, Netgo (Außendienst), "
            "Guntermann & Drunck (Zwei-Personen-IT, kurz), seit 2,5 Jahren "
            "Workplace-Manager bei der Coaching Company in Kreuztal. Kernprofil IT/OT, "
            "Device-Management, Change-/Problem-Management, 2nd/3rd-Level. Cloud ist "
            "Entwicklungsfeld, Zertifizierungen abgelaufen.\n"
            "Nächste Schritte: Unterlagen gelesen → Profil an den Head of IT → "
            "Feedback bis Mitte der kommenden Woche. Telefon bevorzugt."
        ),
    },
    {
        "full_name": "Andreas Fink",
        "fields": {
            "phone": "015203257227",
            "employment_form": EmploymentForm.FESTANSTELLUNG.value,
            "notice_period": "1 Monat, bei Einigung anpassbar",
            "salary_expectation": 62300,
            "focus_areas": ["IT-Infrastruktur", "IT-Administration"],
            "profile_summary": (
                "Kommt aus Infrastruktur und Administration — genau den Bereichen, die "
                "sein aktueller Arbeitgeber komplett auslagert, während Software und "
                "Embedded voraussichtlich bleiben. Das ist der Anlass der Suche. "
                "Gehaltsvorstellung 62.300 €, Kündigungsfrist ein Monat, Fahrweg rund "
                "39 Minuten: die Rahmenbedingungen passen von allen drei am besten. "
                "Einen Teil des Aufgabenkatalogs (MES, Patch-Management im OT-Umfeld) "
                "bezeichnet er als neu, zeigt daran aber ausdrücklich Interesse."
            ),
            "motivation": (
                "Die gesamte IT des aktuellen Arbeitgebers wird ausgesourct, "
                "einschließlich Infrastruktur und Administration; Software und "
                "Embedded-Bereiche verbleiben voraussichtlich."
            ),
            "other_notes": (
                "Fahrweg ca. 39 Minuten bzw. 50 km im Feierabendverkehr.\n"
                "Homeoffice: zwei Tage Standard; Head of IT flexibel, bei größerer "
                "Entfernung auch ein Präsenztag pro Woche vereinbar. Während der "
                "Einarbeitung temporär drei bis vier Präsenztage.\n"
                "Einige Aufgaben der Vakanz sind neu für ihn — Rückverfolgbarkeit, "
                "MES-Unterstützung, Patch-Management im OT-Umfeld; grundsätzliches "
                "Interesse ausdrücklich bekundet.\n"
                "Stellenbeschreibung per E-Mail erhalten und bestätigt; Lebenslauf "
                "wird am Folgetag nachgereicht."
            ),
        },
        "assessment": {
            "fit_score": 7,
            "verdict": (
                "Kaufmännisch der glatteste der drei: 62.300 € liegen mitten im "
                "Tarifkorridor, die Kündigungsfrist ist ein Monat, der Fahrweg rund 39 "
                "Minuten — kein Homeoffice-Konflikt, kein Startverzug, kein "
                "Budgetproblem. Fachlich kommt er aus Infrastruktur und Administration, "
                "die sein Arbeitgeber gerade auslagert; der produktionsnahe Teil des "
                "Katalogs ist für ihn neu. Die offene Frage ist Tiefe im OT-Umfeld, "
                "nicht Verfügbarkeit."
            ),
            "strengths": [
                "Gehaltsvorstellung 62.300 € liegt mitten im Metalltarifrahmen",
                "Kündigungsfrist 1 Monat, bei Einigung noch anpassbar",
                "Fahrweg ca. 39 Minuten / 50 km — die Homeoffice-Regel reicht aus",
                "Klarer, nachvollziehbarer Wechselanlass: seine Bereiche werden ausgesourct",
                "Interesse an den neuen Aufgabenfeldern ausdrücklich bekundet",
            ],
            "risks": [
                "Rückverfolgbarkeit, MES-Unterstützung und OT-Patch-Management sind neu für ihn",
                "Lebenslauf lag im Gespräch noch nicht vor — Detailtiefe erst danach beurteilbar",
                "Tiefe im OT-/Shop-Floor-Umfeld in der Notiz nicht belegt",
            ],
            "client_summary": (
                "Der Kandidat verantwortet Infrastruktur und Administration bei seinem "
                "aktuellen Arbeitgeber — also genau die Bereiche, die dort gerade "
                "vollständig ausgelagert werden, was den Wechsel erklärt. Die "
                "Rahmenbedingungen passen: Gehaltsvorstellung im Tarifkorridor, "
                "Kündigungsfrist ein Monat, Fahrweg rund 39 Minuten, sodass die "
                "vorgesehene Homeoffice-Regelung ohne Sonderabsprache funktioniert. Den "
                "produktionsnahen Teil des Aufgabenkatalogs — Maschinendaten, MES, "
                "Patch-Management im OT-Umfeld — kennt er noch nicht aus der Praxis und "
                "benennt das offen, verbindet damit aber ausdrücklich Interesse."
            ),
            "technologies": ["IT-Infrastruktur", "IT-Administration"],
        },
        "call": (
            "Kandidat: Qualifikationsgespräch 08.10.2026 (Gesprächsnotiz).\n"
            "Anlass der Suche: die komplette IT des Arbeitgebers wird ausgesourct, "
            "Infrastruktur und Administration eingeschlossen; Software und Embedded "
            "bleiben voraussichtlich. Vakanz Linde vorgestellt (produktionsnahe IT/OT, "
            "Rückverfolgbarkeit, Maschinendaten, MES, Backup, OT-Patch-Management, "
            "Remote Maintenance, Shop Floor, MDM) — einige Aufgaben neu, Interesse "
            "vorhanden. Kündigungsfrist 1 Monat, anpassbar. Fahrweg 39 min / 50 km. "
            "Homeoffice 2 Tage, flexibel; Einarbeitung 3–4 Präsenztage. "
            "Gehaltsvorstellung 62.300 € — als vernünftig eingestuft.\n"
            "Nächste Schritte: Stellenbeschreibung lesen → Lebenslauf per E-Mail → "
            "Status aktuell halten."
        ),
    },
    {
        "full_name": "Lukas Sehr",
        "fields": {
            "email": "lukas.sehr0207@gmail.com",
            "employment_form": EmploymentForm.FESTANSTELLUNG.value,
            "notice_period": "1 Monat",
            "current_salary": 47000,
            "salary_expectation": 50000,
            "focus_areas": [
                "Anlagenautomatisierung / SPS",
                "Virtualisierung (VMs, Server)",
                "IT-Dienstleistung",
            ],
            "technical_profile": (
                "Vorerfahrung aus einer Metallwarenfabrik mit vollständig "
                "automatisierter Anlage inklusive speicherprogrammierbarer Steuerung "
                "(SPS). Aktuell als Dienstleister Betreuung zahlreicher virtueller "
                "Maschinen und Server. Eine ITIL-Zertifizierung liegt nicht vor."
            ),
            "profile_summary": (
                "Bringt die Produktionsseite mit: eine vollautomatisierte Anlage samt "
                "SPS aus einer Metallwarenfabrik, aktuell als Dienstleister viele "
                "virtuelle Maschinen und Server. Gehaltsvorstellung über 50.000 € bei "
                "aktuell rund 47.000 €, verhandelbar, Kündigungsfrist ein Monat. Der "
                "offene Punkt ist die Entfernung: Dillenburg liegt rund eineinhalb "
                "Stunden entfernt, er möchte drei bis vier Tage Homeoffice, vertraglich "
                "vorgesehen sind zwei."
            ),
            "motivation": (
                "Ungewisse Zukunft des aktuellen Unternehmens und für das nächste Jahr "
                "angekündigte Veränderungen."
            ),
            "other_notes": (
                "Arbeitsort Dillenburg ca. eineinhalb Stunden entfernt.\n"
                "Bevorzugt drei bis vier Tage Homeoffice pro Woche, wäre aber bereit, "
                "in der Anfangsphase täglich zu pendeln.\n"
                "Umzug oder das Anmieten einer Unterkunft nur ungern.\n"
                "Vertraglich sind zwei Homeoffice-Tage vorgesehen — die Entfernung "
                "könnte in der Personalabteilung Fragen aufwerfen, auch wenn die "
                "IT-Leitung es entspannter sieht.\n"
                "Keine ITIL-Zertifizierung.\n"
                "Lebenslauf wird in die Datenbank aufgenommen; Gespräch mit dem "
                "IT-Leiter in der kommenden Woche, danach Rückmeldung."
            ),
        },
        "assessment": {
            "fit_score": 5,
            "verdict": (
                "Fachlich interessant von der Produktionsseite — eine vollautomatisierte "
                "Anlage mit SPS und aktuell viele VMs und Server sind beides Teile der "
                "Vakanz. Günstig sind außerdem Gehaltsband und Kündigungsfrist. Der "
                "entscheidende Punkt ist die Entfernung: rund eineinhalb Stunden bei "
                "vertraglich zwei Homeoffice-Tagen und einem Wunsch von drei bis vier. "
                "Das ist vor einer Vorstellung mit der Personalabteilung zu klären, "
                "nicht danach."
            ),
            "strengths": [
                "Vollautomatisierte Anlage inkl. SPS aus einer Metallwarenfabrik",
                "Aktuell Betreuung zahlreicher virtueller Maschinen und Server",
                "Gehaltsvorstellung ab 50.000 € — klar innerhalb des Rahmens, verhandelbar",
                "Kündigungsfrist 1 Monat",
                "Bereit, in der Anfangsphase täglich zu pendeln",
            ],
            "risks": [
                "Dillenburg ca. 1,5 h entfernt — der kritische Punkt",
                "Wunsch 3–4 Tage Homeoffice gegen vertraglich zwei",
                "Umzug oder Unterkunft nur ungern — die Entfernung bleibt dauerhaft",
                "Keine ITIL-Zertifizierung",
                "Entfernung kann in der Personalabteilung Fragen aufwerfen",
            ],
            "client_summary": (
                "Der Kandidat bringt die Produktionsseite der Position mit: In einer "
                "Metallwarenfabrik hat er eine vollständig automatisierte Anlage "
                "inklusive speicherprogrammierbarer Steuerung betreut, aktuell "
                "verantwortet er als Dienstleister eine größere Zahl virtueller "
                "Maschinen und Server. Beides berührt den produktionsnahen Teil der "
                "Vakanz unmittelbar. Die Gehaltsvorstellung liegt im Rahmen und ist "
                "verhandelbar, die Kündigungsfrist beträgt einen Monat. Offen ist die "
                "Entfernung zum Standort von rund eineinhalb Stunden; er wäre bereit, "
                "in der Anfangsphase täglich zu pendeln, wünscht sich mittelfristig "
                "jedoch mehr Homeoffice als vorgesehen."
            ),
            "technologies": [
                "SPS / speicherprogrammierbare Steuerung",
                "Anlagenautomatisierung",
                "Virtuelle Maschinen",
                "Serverbetrieb",
            ],
        },
        "call": (
            "Kandidat: Qualifikationsgespräch 08.10.2026 (Gesprächsnotiz).\n"
            "Wechselmotiv: ungewisse Zukunft des Unternehmens, für das nächste Jahr "
            "angekündigte Veränderungen. Vorerfahrung Metallwarenfabrik mit "
            "vollautomatisierter Anlage inkl. SPS; aktuell als Dienstleister viele VMs "
            "und Server. Keine ITIL-Zertifizierung. Kündigungsfrist 1 Monat, aktuell "
            "~47.000 €, Vorstellung über 50.000 € und verhandelbar. Dillenburg ca. 1,5 h "
            "entfernt, Wunsch 3–4 Tage Homeoffice, anfangs tägliches Pendeln möglich, "
            "Umzug ungern. Vertraglich zwei Homeoffice-Tage — Entfernung könnte in der "
            "Personalabteilung Fragen aufwerfen.\n"
            "Nächste Schritte: Gespräch mit dem IT-Leiter in der kommenden Woche → "
            "Rückmeldung an den Kandidaten → Lebenslauf in die Datenbank aufnehmen."
        ),
    },
]

#: The fields the notes actually state, routed through the verification gate so
#: the record can show WHERE each came from. `verification_score` counts
#: exactly these; writing the columns directly leaves a candidate whose every
#: field reads "ohne Beleg".
EVIDENCED_FIELDS = (
    "full_name",
    "notice_period",
    "salary_expectation",
    "current_salary",
    "focus_areas",
    "technical_profile",
    "profile_summary",
    "motivation",
    "other_notes",
    "current_title",
    "current_company",
    "city",
    "email",
    "phone",
)


async def _one(session, model, **where):
    return await session.scalar(select(model).filter_by(**where))


async def _evidence(session, *, tenant_id: uuid.UUID, candidate) -> list[str]:
    done: list[str] = []
    for field in EVIDENCED_FIELDS:
        value = getattr(candidate, field, None)
        if value in (None, "", [], {}):
            continue
        await verification.verify_and_commit(
            session,
            change=ProposedChange(
                tenant_id=tenant_id,
                entity_type="candidate",
                entity_id=candidate.id,
                field=field,
                proposed_value=json.dumps(value, ensure_ascii=False, default=str)
                if isinstance(value, (list, dict))
                else str(value),
                source=ConfidenceSource.HUMAN_VERIFIED,
                source_detail=f"Qualifikationsgespräch 08.10.2026 — {BASIS}",
                confidence=0.95,
            ),
            agent="seed_it_admin_example",
        )
        done.append(field)
    return done


async def seed(tenant_id: uuid.UUID) -> dict:
    current_tenant_var.set(str(tenant_id))
    async with SessionLocal() as s:
        company = await _one(s, Company, tenant_id=tenant_id, name=COMPANY)
        if company is None:
            company = Company(
                tenant_id=tenant_id,
                name=COMPANY,
                is_client=True,
                source="qualifikationsgespraeche",
            )
            s.add(company)
            await s.flush()

        job = await _one(s, Job, tenant_id=tenant_id, title=JOB_TITLE)
        if job is None:
            job = Job(tenant_id=tenant_id, title=JOB_TITLE)
            s.add(job)
        job.client_company_id = company.id
        job.location = "Dillenburg"
        job.must_have_skills = MUST_HAVE
        job.salary_min, job.salary_max = SALARY_MIN, SALARY_MAX
        job.salary_currency = "EUR"
        job.status = "open"
        await s.flush()

        # What the client wants, once, on the mandate — not copied onto three
        # candidates. Matched on its own text so a re-run does not add a fourth.
        existing = await _one(
            s,
            ManagerInteraction,
            tenant_id=tenant_id,
            job_id=job.id,
            interaction_type=InteractionType.BRIEFING.value,
        )
        if existing is None:
            s.add(
                ManagerInteraction(
                    tenant_id=tenant_id,
                    job_id=job.id,
                    manager_id=None,
                    interaction_type=InteractionType.BRIEFING.value,
                    occurred_at=CALLED_ON,
                    summary=BRIEFING,
                )
            )
        else:
            existing.summary = BRIEFING
            existing.occurred_at = CALLED_ON
        await s.flush()

        out: list[dict] = []
        for spec in CANDIDATES:
            candidate = await _one(
                s, Candidate, tenant_id=tenant_id, full_name=spec["full_name"]
            )
            if candidate is None:
                candidate = Candidate(
                    tenant_id=tenant_id,
                    full_name=spec["full_name"],
                    source="qualifikationsgespraech",
                )
                s.add(candidate)
            for field, value in spec["fields"].items():
                setattr(candidate, field, value)
            await s.flush()

            application = await _one(
                s,
                Application,
                tenant_id=tenant_id,
                candidate_id=candidate.id,
                job_id=job.id,
            )
            if application is None:
                application = Application(
                    tenant_id=tenant_id,
                    candidate_id=candidate.id,
                    job_id=job.id,
                    # Spoken to, nobody presented yet — which is exactly where
                    # all three stand on 08.10.2026.
                    status=ApplicationStatus.SCREENED,
                )
                s.add(application)
            await s.flush()

            # The call itself, per candidate, in the append-only store the
            # Feedback panel reads. Prefixed so it is labelled "von Kandidat".
            note = await _one(
                s,
                ManagerInteraction,
                tenant_id=tenant_id,
                job_id=job.id,
                candidate_id=candidate.id,
                interaction_type=InteractionType.FEEDBACK.value,
            )
            if note is None:
                s.add(
                    ManagerInteraction(
                        tenant_id=tenant_id,
                        job_id=job.id,
                        candidate_id=candidate.id,
                        manager_id=None,
                        interaction_type=InteractionType.FEEDBACK.value,
                        occurred_at=CALLED_ON,
                        summary=spec["call"],
                    )
                )
            else:
                note.summary = spec["call"]
                note.occurred_at = CALLED_ON
            await s.commit()

            await pipeline_service.set_assessment(
                s,
                tenant_id=tenant_id,
                application_id=application.id,
                basis=BASIS,
                assessed_at=CALLED_ON,
                **spec["assessment"],
            )
            evidenced = await _evidence(s, tenant_id=tenant_id, candidate=candidate)
            await s.flush()
            await candidates_service.recompute_scores(
                s, tenant_id=tenant_id, candidate=candidate
            )
            await s.commit()
            out.append(
                {
                    "candidate": spec["full_name"],
                    "candidate_id": str(candidate.id),
                    "fit": spec["assessment"]["fit_score"],
                    "evidenced": len(evidenced),
                }
            )

        return {"job_id": str(job.id), "company": COMPANY, "candidates": out}


async def remove(tenant_id: uuid.UUID) -> dict:
    """Take it out again. A demo mandate you cannot remove is not a demo."""
    current_tenant_var.set(str(tenant_id))
    async with SessionLocal() as s:
        job = await _one(s, Job, tenant_id=tenant_id, title=JOB_TITLE)
        gone: list[str] = []
        if job is not None:
            for spec in CANDIDATES:
                candidate = await _one(
                    s, Candidate, tenant_id=tenant_id, full_name=spec["full_name"]
                )
                if candidate is None:
                    continue
                app = await _one(
                    s,
                    Application,
                    tenant_id=tenant_id,
                    candidate_id=candidate.id,
                    job_id=job.id,
                )
                if app is not None:
                    await s.delete(app)
                await s.delete(candidate)
                gone.append(spec["full_name"])
            for row in (
                await s.scalars(
                    select(ManagerInteraction).where(
                        ManagerInteraction.tenant_id == tenant_id,
                        ManagerInteraction.job_id == job.id,
                    )
                )
            ).all():
                await s.delete(row)
            await s.delete(job)
        company = await _one(s, Company, tenant_id=tenant_id, name=COMPANY)
        if company is not None:
            await s.delete(company)
        await s.commit()
        return {"candidates": gone, "job": JOB_TITLE if job else None}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tenant", type=uuid.UUID, required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        print(f"würde anlegen: {COMPANY} · {JOB_TITLE}")
        print(f"  Standort Dillenburg · Band {SALARY_MIN}–{SALARY_MAX} € · Muss {MUST_HAVE}")
        print(f"  Briefing: {len(BRIEFING)} Zeichen")
        for spec in CANDIDATES:
            a = spec["assessment"]
            print(
                f"  {spec['full_name']}: {a['fit_score']}/10 · "
                f"{len(a['strengths'])} Stärken · {len(a['risks'])} Risiken · "
                f"{len(spec['fields'])} Felder"
            )
        return

    if args.remove:
        print("entfernt:", asyncio.run(remove(args.tenant)))
        return

    result = asyncio.run(seed(args.tenant))
    print("angelegt:", result)
    print(f"  → Cockpit: #cockpit/{result['job_id']}")


if __name__ == "__main__":
    main()
