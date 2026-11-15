"""The Bewertungs-Prompt (ELI-41): what a recruiter pastes into Claude.

The recruiters evaluate a candidate against a mandate by copying the job, the
briefing, the CV and the transcript into Claude by hand, with a fixed schema
for the answer — the "Kandidatenauswertung" ELI-42 spells out. Eligo already
holds every one of those sources, so the prompt is assembled here instead.

Two halves, kept apart on purpose:

* `build_prompt` is a **pure function over an `EvaluationMaterial`**: no
  database, no model, no clock. What it writes can be read line by line
  against the record it was given.
* `service.evaluation_material` gathers that material for one application,
  under the caller's tenant — and decides what does NOT go in (another
  candidate's feedback, a note from another mandate, contact details the
  evaluation does not need).

The schema below is also the contract of the way back: the answer is pasted
into "Nach dem Gespräch erfassen" and read by `auswertung.parse_auswertung`.
Change a label here and that parser must learn it too
(`tests/test_bewertung_prompt.py` round-trips a filled-in answer).

No model is called. The hard criteria — right to work, salary floor against
the band, location — arrive already decided by code (`matching`), labelled
as such, and the prompt tells the model to explain them, not re-decide them
(CLAUDE.md §2.2).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

#: A document longer than this is cut, and the cut is said. A CV is a few
#: thousand characters; a 40-page PDF export is not what the model needs.
MAX_DOCUMENT_CHARS = 20_000

#: What each document kind is called in the prompt, in the order the
#: evaluation reads them.
DOCUMENT_LABELS: dict[str, str] = {
    "cv": "Lebenslauf",
    "transkript": "Gesprächstranskript",
    "zeugnis": "Zeugnis",
    "zertifikat": "Zertifikat",
    "sonstiges": "Sonstiges Dokument",
}


@dataclass(frozen=True)
class SourceDocument:
    """One file on the candidate. `text` None: stored, but nothing readable
    (a scan) — it is named in the prompt rather than silently dropped."""

    kind: str
    filename: str
    date: dt.date | None
    text: str | None


@dataclass(frozen=True)
class Note:
    """A dated line from the record: a briefing, a feedback, a call note."""

    date: dt.date | None
    text: str
    #: "Briefing" · "Qualifikationsgespräch" · "Kunde" …
    label: str | None = None
    who: str | None = None


@dataclass
class EvaluationMaterial:
    """Everything the prompt may say, already selected and scoped."""

    job_title: str
    client: str
    location: str | None
    vacancy_id: str
    candidate_name: str
    contact: str | None = None
    must_have: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    salary_band: str | None = None
    #: When the Suchprofil was last written — the "Stellenanzeige vom" date.
    profile_date: dt.date | None = None
    briefings: list[Note] = field(default_factory=list)
    feedback: list[Note] = field(default_factory=list)
    candidate_notes: list[Note] = field(default_factory=list)
    #: The candidate's own columns, as labelled lines. Contact details are
    #: not among them (see `service.evaluation_material`).
    profile: list[tuple[str, str]] = field(default_factory=list)
    documents: list[SourceDocument] = field(default_factory=list)
    #: The hard criteria, as code decided them.
    checks: list[str] = field(default_factory=list)


def _de(day: dt.date | None) -> str:
    return day.strftime("%d.%m.%Y") if day else "ohne Datum"


def basis_line(m: EvaluationMaterial) -> str:
    """"Basis: Stellenanzeige vom …, Gesprächstranskript vom …, Lebenslauf und
    Zeugnisse" — naming only what the record actually holds.

    Written by code, not left to the model: a provenance line listing a
    transcript nobody uploaded is exactly the claim this product refuses.
    """
    parts = [f"Suchprofil vom {_de(m.profile_date)}" if m.profile_date else "Suchprofil"]
    transcripts = [d for d in m.documents if d.kind == "transkript" and d.text]
    if transcripts:
        newest = max(
            (d.date for d in transcripts if d.date), default=None
        )
        parts.append(f"Gesprächstranskript vom {_de(newest)}")
    has_cv = any(d.kind == "cv" for d in m.documents)
    has_refs = any(d.kind in ("zeugnis", "zertifikat") for d in m.documents)
    if has_cv and has_refs:
        parts.append("Lebenslauf und Zeugnisse")
    elif has_cv:
        parts.append("Lebenslauf")
    elif has_refs:
        parts.append("Zeugnisse")
    if m.briefings:
        parts.append("Briefing")
    return "Basis: " + ", ".join(parts)


def position_line(m: EvaluationMaterial) -> str:
    where = f"{m.client} {m.location}".strip() if m.location else m.client
    return f"Position: {m.job_title} | {where} | Vakanz-ID {m.vacancy_id}"


_RULES = """\
Regeln:
- Schreibe auf Deutsch, in kurzen Sätzen.
- Jede Stärke und jede Lücke braucht einen Beleg aus dem Material: Lebenslauf, Zeugnis, Gesprächstranskript, Notiz, Briefing oder Suchprofil. Nenne die Quelle.
- Nichts raten. Fehlt eine Information im Material, schreibe „nicht angegeben“. Wurde sie im Gespräch nicht angesprochen, schreibe „nicht erfragt“.
- Widersprüche zwischen Lebenslauf und Zeugnissen (Daten, Titel, Arbeitgeber) gehören unter „Lücken / Risiken“.
- Die Punkte unter „Deterministisch geprüft“ hat Eligo per Code entschieden. Bewerte sie nicht neu, erläutere sie nur.
- Sensible Angaben (Gesundheit, Krankheitszeiten, Schwangerschaft, Behinderung, Religion, Herkunft) nur als Hinweis für den Recruiter unter „Vor der Vorstellung zu klären“ — nie in Abschnitt C.
- Abschnitt C geht an den Kunden: keine Gesundheitsdaten, kein Gehalt, keine Kontaktdaten.
- Gesamtbewertung als ganze Zahl von 0 bis 10.
- Reiner Text, keine Markdown-Überschriften. Labels genau wie im Schema, der Inhalt in derselben Zeile nach dem Doppelpunkt. Aufzählungen beginnen mit „- “."""


def _schema(m: EvaluationMaterial) -> str:
    return f"""\
Kandidatenauswertung
{position_line(m)}
{basis_line(m)}
[Optional: ein kurzer Absatz zu Abweichungen oder Einschränkungen des Materials.]

A. Passungsbewertung zur Position
Gesamtbewertung: X / 10
Kurzfazit: [2–3 Sätze]
Stärken:
- **[Thema]:** [Beleg aus Lebenslauf/Zeugnis/Transkript/Suchprofil]
Lücken / Risiken:
- **[Thema]:** [Beleg; auch Abweichungen zwischen Lebenslauf und Zeugnissen]
Fachliche & professionelle Passung: [ein Absatz]
Gehalt: [Wunsch vs. zuletzt vs. Rahmen der Position]

B. Gesprächszusammenfassung für Datenbank
Zusammenfassung des Profils: [ein Absatz]
Schwerpunkte: [kommagetrennt]
Technisches Know-how: [kommagetrennt; jede Muss-Anforderung, die im Material fehlt, als „<Skill>: nicht angegeben“]
Kündigungsfrist / Verfügbarkeit: […]
Gehaltsvorstellung: [Aktuell …; Minimum …; Wunsch …]
Wechselmotivation: […]
Höchster Abschluss: […]
Verfügbarkeit für Interviews: […]
Weitere relevante Punkte:
- […]

C. Kandidatenzusammenfassung für Kundenvorstellung ({m.client})
[Ein Absatz für den Kunden. Keine Gesundheitsdaten, kein Gehalt, keine Kontaktdaten.]

D. Relevante Technologien für die Position
[kommagetrennt]

Vor der Vorstellung zu klären:
1. […]"""


def _notes(title: str, notes: list[Note]) -> list[str]:
    if not notes:
        return []
    out = [f"### {title}"]
    for note in notes:
        head = _de(note.date)
        if note.label:
            head += f" · {note.label}"
        if note.who:
            head += f" · {note.who}"
        out.append(f"- [{head}] {note.text.strip()}")
    return out + [""]


def _document(doc: SourceDocument) -> list[str]:
    label = DOCUMENT_LABELS.get(doc.kind, doc.kind)
    head = f"### {label} — {doc.filename} ({_de(doc.date)})"
    if not doc.text or not doc.text.strip():
        return [head, "(gespeichert, aber kein Text lesbar — z. B. ein Scan)", ""]
    text = doc.text.strip()
    if len(text) > MAX_DOCUMENT_CHARS:
        text = text[:MAX_DOCUMENT_CHARS] + "\n[… gekürzt]"
    return [head, "<<<", text, ">>>", ""]


def _material(m: EvaluationMaterial) -> str:
    lines = ["### Position"]
    lines.append(f"- Titel: {m.job_title}")
    lines.append(f"- Kunde: {m.client}")
    if m.location:
        lines.append(f"- Ort: {m.location}")
    if m.contact:
        lines.append(f"- Ansprechpartner: {m.contact}")
    lines.append(
        "- Muss-Kriterien: " + (", ".join(m.must_have) if m.must_have else "nicht angegeben")
    )
    if m.certifications:
        lines.append("- Pflicht-Zertifikate: " + ", ".join(m.certifications))
    lines.append(f"- Gehaltsband: {m.salary_band or 'nicht angegeben'}")
    lines.append("")

    if m.checks:
        lines.append("### Deterministisch geprüft (Eligo, per Code — nicht neu bewerten)")
        lines.extend(f"- {c}" for c in m.checks)
        lines.append("")

    lines += _notes("Briefing — was der Kunde gesagt hat", m.briefings)
    lines += _notes("Feedback zu diesem Kandidaten", m.feedback)

    lines.append(f"### Kandidat — erfasste Daten ({m.candidate_name})")
    if m.profile:
        lines.extend(f"- {label}: {value}" for label, value in m.profile)
    else:
        lines.append("- keine strukturierten Daten erfasst")
    lines.append("")

    lines += _notes("Notizen zum Kandidaten", m.candidate_notes)

    if m.documents:
        lines.extend(line for doc in m.documents for line in _document(doc))
    else:
        lines += ["### Dokumente", "keine Dokumente hinterlegt", ""]
    return "\n".join(lines).rstrip()


def sources(m: EvaluationMaterial) -> list[str]:
    """What went into the prompt, for the line under the copy button."""
    out = ["Suchprofil"]
    for title, notes in (
        ("Briefing", m.briefings),
        ("Feedback", m.feedback),
        ("Notizen", m.candidate_notes),
    ):
        if notes:
            out.append(f"{title} ({len(notes)})")
    if m.profile:
        out.append("Kandidatenprofil")
    for doc in m.documents:
        label = DOCUMENT_LABELS.get(doc.kind, doc.kind)
        suffix = "" if doc.text and doc.text.strip() else " (nicht lesbar)"
        out.append(f"{label} — {doc.filename}{suffix}")
    return out


def build_prompt(m: EvaluationMaterial) -> str:
    """The whole prompt: task, rules, schema, material. Pure."""
    return "\n".join(
        [
            "Du bist Recruiting-Analyst einer Personalberatung. Erstelle eine "
            f"Kandidatenauswertung für {m.candidate_name} zur unten genannten "
            "Position — ausschließlich auf Basis des Materials unten.",
            "",
            _RULES,
            "",
            "Ausgabe — genau diese Struktur:",
            "",
            _schema(m),
            "",
            "Material:",
            "",
            _material(m),
            "",
        ]
    )
