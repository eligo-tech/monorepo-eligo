"""What a column can mean, per entity — the whole of "generic" lives here.

Adding a new importable entity is one `EntitySpec`; adding a synonym is one
string. Nothing else in the import path knows what a candidate is.

Two decisions worth stating:

* **Synonyms are matched, not required.** A customer's export says "Nachname"
  or "Last Name" or "Name 2"; making them rename columns before the product
  works is how onboarding dies. The mapping is a SUGGESTION the recruiter can
  correct — the product guesses and shows its guess.
* **Identity is explicit per entity.** Import must be re-runnable: the same
  file twice is one book, not two. Each spec names the fields that identify a
  row, in order, and the first one present decides.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Field:
    """One canonical field a column can be mapped to."""

    name: str
    label: str
    #: Lower-cased header texts that mean this field. Matched after
    #: normalisation (umlauts folded, punctuation and spaces dropped).
    synonyms: tuple[str, ...] = ()
    #: "text" | "int" | "list" — how the cell is coerced before writing.
    kind: str = "text"


@dataclass(frozen=True)
class EntitySpec:
    label: str
    #: Shown in the UI above the mapping table.
    hint: str
    fields: tuple[Field, ...]
    #: Fields that must be mapped for the import to be allowed at all.
    required: tuple[str, ...]
    #: Identity, best first. A row matching an existing record updates it.
    identity: tuple[str, ...]
    #: Written to `source` so every row says where it came from.
    source: str = "datei-import"
    #: Required fields that can be BUILT from other columns. Vorname +
    #: Nachname with no "Name" column is the commonest export there is, and
    #: refusing it because `full_name` is unmapped would reject most files
    #: on arrival. Composition is one-way: never split a full name into
    #: first/last, because "Dr. Anna von Weber" has no safe answer.
    composed: tuple[tuple[str, tuple[str, ...]], ...] = ()
    aliases: tuple[str, ...] = field(default_factory=tuple)


def _f(name: str, label: str, *synonyms: str, kind: str = "text") -> Field:
    return Field(name=name, label=label, synonyms=synonyms, kind=kind)


CANDIDATE = EntitySpec(
    label="Kandidaten",
    hint="Die Personen aus Ihrem bisherigen System — Pflicht ist nur ein Name.",
    required=("full_name",),
    identity=("external_id", "email"),
    composed=(("full_name", ("first_name", "last_name")),),
    fields=(
        _f("full_name", "Name", "name", "vollständiger name", "kandidat", "candidate", "full name"),
        _f("first_name", "Vorname", "vorname", "first name", "given name", "name 1"),
        _f("last_name", "Nachname", "nachname", "familienname", "last name", "surname", "name 2"),
        _f("email", "E-Mail", "email", "e-mail", "mail", "e mail", "emailadresse", "e-mail-adresse"),
        _f("phone", "Telefon", "telefon", "phone", "tel", "mobil", "handy", "telefonnummer"),
        _f("current_title", "Job-Titel", "position", "jobtitel", "titel", "job title", "rolle", "berufsbezeichnung"),
        _f("current_company", "Aktueller Arbeitgeber", "firma", "unternehmen", "arbeitgeber", "company", "employer"),
        _f("city", "Stadt", "stadt", "ort", "wohnort", "city"),
        _f("postal_code", "PLZ", "plz", "postleitzahl", "zip", "postal code"),
        _f("street", "Straße", "straße", "strasse", "adresse", "street", "address"),
        _f("country", "Land", "land", "country"),
        _f("date_of_birth", "Geburtsdatum", "geburtsdatum", "geburtstag", "date of birth", "dob"),
        _f("linkedin_url", "LinkedIn", "linkedin", "linkedin url", "linkedin profil"),
        _f("xing_url", "Xing", "xing", "xing url", "xing profil"),
        _f("notice_period", "Kündigungsfrist", "kündigungsfrist", "notice period", "kuendigungsfrist"),
        _f("availability", "Verfügbarkeit", "verfügbarkeit", "verfuegbarkeit", "availability", "verfügbar ab"),
        _f("current_salary", "Aktuelles Gehalt", "aktuelles gehalt", "gehalt aktuell", "current salary", kind="int"),
        _f("salary_minimum", "Mindestgehalt", "mindestgehalt", "gehalt minimum", "minimum salary", kind="int"),
        _f("salary_expectation", "Wunschgehalt", "wunschgehalt", "gehaltsvorstellung", "gehalt", "salary", "expected salary", kind="int"),
        _f("skills", "Skills", "skills", "kenntnisse", "technologien", "fähigkeiten", "tech stack", kind="list"),
        _f("languages", "Sprachen", "sprachen", "languages", kind="list"),
        _f("industries", "Branchen", "branche", "branchen", "industry", "industries", kind="list"),
        _f("employment_type", "Anstellungsart (Quelle)", "anstellungsart", "anstellungsform", "employment type", "vertragsart"),
        _f("profile_summary", "Profil-Zusammenfassung", "zusammenfassung", "profil", "summary", "notizen", "notes"),
        _f("motivation", "Wechselmotivation", "wechselmotivation", "motivation"),
        _f("external_id", "ID im Altsystem", "id", "kandidaten-id", "candidate id", "external id", "nummer", "referenz"),
    ),
)

COMPANY = EntitySpec(
    label="Firmen",
    hint="Ihre Kunden und Zielfirmen. Pflicht ist der Firmenname.",
    required=("name",),
    identity=("external_id", "name"),
    fields=(
        _f("name", "Firma", "firma", "unternehmen", "firmenname", "company", "kunde", "name"),
        _f("domain", "Webseite", "webseite", "website", "domain", "url", "homepage"),
        _f("industry", "Branche", "branche", "industry", "sektor"),
        _f("location", "Ort", "ort", "stadt", "standort", "city", "location"),
        _f("external_id", "ID im Altsystem", "id", "firmen-id", "company id", "external id", "nummer"),
    ),
)

MANAGER = EntitySpec(
    label="Ansprechpartner",
    hint="Die Menschen bei Ihren Kunden. Die Firma wird über den Namen zugeordnet.",
    required=("full_name",),
    identity=("external_id", "email"),
    composed=(("full_name", ("first_name", "last_name")),),
    fields=(
        _f("full_name", "Name", "name", "ansprechpartner", "kontakt", "contact", "full name"),
        _f("first_name", "Vorname", "vorname", "first name"),
        _f("last_name", "Nachname", "nachname", "last name", "surname"),
        _f("company_name", "Firma", "firma", "unternehmen", "company", "kunde"),
        _f("role_title", "Position", "position", "rolle", "titel", "job title", "funktion"),
        _f("email", "E-Mail", "email", "e-mail", "mail"),
        _f("phone", "Telefon", "telefon", "phone", "tel", "mobil"),
        _f("linkedin_url", "LinkedIn", "linkedin", "linkedin url"),
        _f("xing_url", "Xing", "xing", "xing url"),
        _f("city", "Stadt", "stadt", "ort", "city"),
        _f("external_id", "ID im Altsystem", "id", "kontakt-id", "external id", "nummer"),
    ),
)

JOB = EntitySpec(
    label="Mandate",
    hint="Offene Suchen. Die Firma wird über den Namen zugeordnet.",
    required=("title",),
    identity=("external_id", "title"),
    fields=(
        _f("title", "Titel", "titel", "position", "stelle", "mandat", "job", "title"),
        _f("company_name", "Kunde", "firma", "kunde", "unternehmen", "company"),
        _f("location", "Ort", "ort", "standort", "city", "location"),
        _f("salary_min", "Gehalt von", "gehalt von", "gehalt min", "salary min", "von", kind="int"),
        _f("salary_max", "Gehalt bis", "gehalt bis", "gehalt max", "salary max", "bis", kind="int"),
        _f("must_have_skills", "Muss-Kriterien", "muss", "musskriterien", "requirements", "skills", kind="list"),
        _f("status", "Status", "status", "zustand"),
        _f("external_id", "ID im Altsystem", "id", "job-id", "external id", "nummer"),
    ),
)

SPECS: dict[str, EntitySpec] = {
    "candidates": CANDIDATE,
    "companies": COMPANY,
    "managers": MANAGER,
    "jobs": JOB,
}
