"""Named contacts in public ad texts — who to call about a vacancy.

A German job ad very often ends with the person responsible for it: "Für
Rückfragen steht Ihnen Frau Katrin Wolter (Pflegedienstleitung) unter 0395
5442681 zur Verfügung." That is the most valuable line in the ad for a
recruiter, and it is already in the corpus — `HubPostingPayload.description`
holds the text. Reading it needs no crawl, so it respects ARCHITECTURE.md
RULE 1, and RULE 2 allows a person as a public source published them.

Deterministic on purpose. This is extraction, not judgement: a regex either
found "Frau Katrin Wolter" in the text or it did not, and every result carries
the quote it came from so a recruiter can see the evidence rather than trust
the parser. Nothing here writes anything — adopting a contact into `managers`
is a separate, explicit act.

Pure functions, no I/O: the unit CI exercises against real ad texts.

Tuned for precision over recall. A missed contact costs a recruiter a look at
the ad; an invented one ("Ansprechpartner für Patienten" read as a person) puts
a non-person into a contact list, where it reads as real.
"""

from __future__ import annotations

import dataclasses
import re
import unicodedata

# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------

_UPPER = "A-ZÄÖÜ"
_LOWER = "a-zäöüßéèáàóòíìúùçñ"
#: One capitalised name token, hyphenated parts allowed: "Anna-Lena", "Schöne-Bolinger".
_TOKEN = rf"[{_UPPER}][{_LOWER}]+(?:-[{_UPPER}][{_LOWER}]+)*"
#: Nobiliary particles that stay lowercase inside a name: "Anna von Berg".
_PARTICLE = r"(?:von|van|de|der|den|zu|vom|ten|la|le|di|da)"
#: A surname as some ads print it, in capitals: "Herrn Felix TSCHOHL". Three
#: letters or more, so "AG", "KG" and initials never qualify; company words
#: in capitals are refused in `_trim_name` (`_CAPS_NOT_NAMES`).
_CAPS = rf"[{_UPPER}]{{3,}}(?:-[{_UPPER}]{{3,}})*"
#: Academic / professional prefixes, kept as part of the displayed name.
#: The lowercase parts follow a "Dr.": "Dr. med.", "Dr. rer. nat.".
#: Written-together and Austrian forms too: "Dr.med.", "Dr.rer.nat.",
#: "Dr.-Ing.", "Dr.in", "Mag.a", "Mag. (FH)".
_TITLE = (
    r"(?:Dr\.|DDr\.|Prof\.|Mag\.|Mst\.|DI|Dipl\.-[A-Z][a-z]+\.|MBA|Ing\."
    r"|med\.|dent\.|rer\.|nat\.|jur\.|iur\.|phil\."
    r"|Dr\.med\.|Dr\.med\.dent\.|Dr\.rer\.nat\.|Dr\.phil\.|Dr\.jur\.|Dr\.-Ing\.|Dr\.in|Mag\.a"
    r"|\(FH\))"
)

#: Spaces only between tokens, never a line break: a contact block puts the
#: street on the next line, and "Sophie Bennicke\nEhrenbachstraße" is two
#: things. The trailing lookahead stops a token being cut mid-word ("GmbH"
#: must not yield "Gmb").
#: Titles may also stand between the parts: "Herr Landrat Dr. Richard Sieber"
#: (the leading role word is split off in `_trim_name`).
_NAME = (
    rf"(?:{_TITLE} +)*{_TOKEN}(?: +(?:{_TITLE} +)*(?:{_PARTICLE} +)?{_TOKEN}){{0,2}}"
    rf"(?![{_LOWER}{_UPPER}])"
)
#: After a salutation a part may be in capitals: "Herrn Felix TSCHOHL". Only
#: there — in a heading or after "Kontakt:" a word in capitals is a company
#: ("EDEKA Breitenbach", "NORMA Lebensmittelfilialbetrieb").
_NAME_SALUTED = (
    rf"(?:{_TITLE} +)*(?:{_TOKEN}|{_CAPS})(?: +(?:{_TITLE} +)*(?:{_PARTICLE} +)?(?:{_TOKEN}|{_CAPS})){{0,2}}"
    rf"(?![{_LOWER}{_UPPER}])"
)

#: A rank between the salutation and the name: "Herr Chefarzt Privatdozent Dr.
#: Jonas Diehm", "Herrn Oberlandeskirchenrat Dr. Thilo Daniel". Matched by its
#: ending, so a surname like "Meister" or "Leiter" is never one.
_RANK = (
    rf"[{_UPPER}][{_LOWER}]*(?:arzt|ärztin|dozent|dozentin|rat|rätin|meister|meisterin|"
    r"dekan|dekanin|direktor|direktorin|präsident|präsidentin|redakteur|redakteurin)"
)

#: "Frau Katrin Wolter", "Herrn Dr. Benjamin Schmidt", "Herr Trippner".
_SALUTED = re.compile(
    rf"\b(?P<sal>Frau|Herrn?) +(?P<rank>(?:{_RANK} +(?:{_TITLE} +)*){{0,2}})(?P<name>{_NAME_SALUTED})"
)

#: "Ansprechpartnerin: Jutta Dziobek" — a contact label, then a bare name.
#: Requires the colon or a line break: "Ansprechpartner für Patienten" is a
#: duty in a task list, not a person, and is the commonest false positive.
#: Gendered spellings the boards use: "Ansprechpartner*in", "Recruiter:in".
_GENDER = r"(?:in|\*in|:in|_in|In|\(in\))?"
_LABEL = (
    rf"(?:Ansprechpartner{_GENDER}|Ansprechperson|Kontaktperson|Kontakt|Recruiter{_GENDER})"
)
_LABELLED = re.compile(
    rf"\b(?:Ihr(?:e)?\s+|Dein(?:e)?\s+)?{_LABEL}"
    rf"\s*(?::|\n)\s*(?P<name>{_NAME})"
)

#: A contact HEADING, the partner-board layout: a short line naming the
#: function, then the name alone on its own line.
#:
#:     Deine Ansprechperson für weitere Fragen
#:     Kathrin Telega
#:     Junior People & Culture Business Partner
#:
#: The heading line must be short and end the line (no sentence after the
#: label), and the name must stand alone on its line. That is what separates
#: it from a duty in a task list — "Ansprechpartner für Bürgerinnen und Bürger,
#: Kommunen, Behörden …" runs on and never has a bare name under it.
_HEADED = re.compile(
    rf"(?m)^[^\n]{{0,30}}\b{_LABEL}\w*[^\n.!?]{{0,45}}:? *\n\s*"
    rf"(?P<name>{_NAME}) *(?=$|[,/(|–]| - )"
)

#: Words that follow "Frau"/"Herr" without being a name, or that a greedy name
#: match swallows from the next sentence.
_NOT_NAMES = {
    "Sie", "Ihr", "Ihre", "Ihnen", "Oder", "Und", "Divers", "Vorname", "Nachname",
    "Mustermann", "Musterfrau", "Muster", "Kollegin", "Kollege", "Bewerber",
    "Bewerberin", "Tel", "Telefon", "Mobil", "Mail", "E-Mail", "Email", "Fax",
    "Leitung", "Personal", "Bitte", "Gerne", "Jetzt", "Wir", "Unser", "Unsere",
    "Die", "Der", "Das", "Bei", "Für", "Mit", "Von", "Zur", "Zum", "Im", "In",
    "Am", "An", "Auf", "Aus", "Straße", "Str", "Platz", "Weg", "Gmbh", "Ag",
    "Als", "Wenn", "Nehmen", "Du", "Dein", "Deine", "Frau", "Herr", "Herrn",
    "Machen", "Neue", "Dienstort", "Bewerbungsformular", "Talent", "Recruiting",
    # Site furniture on partner-board pages, left over after the markup goes.
    "Job", "Jobs", "Cookie", "Cookies", "Einstellungen", "Datenschutz", "Impressum",
    "Kontakt", "Team", "Login", "Menü", "Suche", "Merken", "Teilen",
    # A heading read as a name: "Ansprechpartner:\nNoch Fragen", "Ihr
    # Kontakt\nÜber Uns".
    "Noch", "Fragen", "Über", "Uns", "Karriere", "Stellenangebote", "Benefits",
    "Standort", "Standorte", "Profil", "Aufgaben", "Unternehmen",
    # A title stem left alone when its dot was eaten: "Frau Dr. gern".
    "Dr", "Prof", "Mag",
    # Letters after a name: "Birgit Hunyar BSc".
    "BSc", "MSc", "BA", "MA",
    # "Human Resources" — a department, not a surname.
    "Resources", "Human",
}

#: Words in capitals that are a company line or a label, not a surname.
_CAPS_NOT_NAMES = {
    "GMBH", "MBH", "UND", "TEL", "FAX", "MAIL", "KONTAKT", "STR", "STRASSE", "STRAßE",
    "CEO", "GESCHÄFTSFÜHRUNG", "PERSONAL", "BEWERBUNG", "JOBS", "KARRIERE", "TEAM",
    # Postnominals: "Heinz Hierl MAS".
    "MAS", "BSC", "MSC", "MBA", "LLM",
    # Ordinary words an ad sets in capitals: "Frau Steiner NACH telefonischer …".
    "NACH", "UNTER", "ODER", "BEI", "MIT", "FÜR", "PER", "VON", "ZUR", "DER", "DIE",
    "DAS", "BITTE", "AUCH", "NUR", "SIE", "WIR", "IHR",
    # Labels of the Austrian AMS ad layout: "BEWERBUNG: … DIENSTGEBER: …".
    "DIENSTGEBER", "ARBEITSORT", "ENTLOHNUNG", "ANSPRECHPARTNER", "ANSPRECHPARTNERIN",
}

#: A single word after "Frau"/"Herr" that names a unit, not a person:
#: "Frau Bewerbermanagement". Suffix-matched, so "Leitner" stays a surname.
_UNIT_WORD = re.compile(
    r"(?i)(management|abteilung|referat|bereich|team|service|verwaltung|zentrale)$"
)

#: The name is a company if a legal form follows it: "Vision Consulting GmbH".
_LEGAL_FORM_AFTER = re.compile(r"^ *(?:GmbH|gGmbH|mbH|AG|KG|SE|e\. ?V\.|OHG|UG|GbR|Gmb)\b")
#: Street-shaped tokens a name must not end in: "Friedrich-Mohr-Straße", "Wahlerstr".
_STREET = re.compile(r"(?i)(stra(ss|ß)e|str\.?|allee|platz|gasse)$")
#: Suffixes that also end common surnames — Hering, Döring, Kaufer, Damm.
#: Taken as a street only when a house number follows or the name already
#: has two parts before it.
_STREET_WEAK = re.compile(r"(?i)(weg|ring|damm|ufer)$")


def _is_street(token: str, *, following: str = "", parts: int = 3) -> bool:
    """A street-shaped token — but a suffix on its own is a surname: "Herr
    Marco Damm" is a person, "Kurfürstendamm" is an address; and "Herr
    Thomas Hering" is a person, "Am Hering 4" is not a name at all."""
    m = _STREET.search(token)
    if m and m.start() > 0:
        return True
    numbered = bool(re.match(r"^\s*\d", following))
    m = _STREET_WEAK.search(token)
    if m and m.start() == 0:
        # The suffix as a word of its own is a street only before a house
        # number: "Kreuzberger Ring 46a" — but "Herr Thomas Ring" is a person.
        return numbered
    return bool(m) and (parts >= 3 or numbered)


#: A business, not a person: "Kontakt:\nBäckerei Sonnenschein", "Frau Cordula
#: Steiner Gasthof - Krone". Rejected as the first word of a name, dropped as
#: the last.
_BUSINESS = re.compile(
    r"(?i)^(bäckerei|konditorei|metzgerei|fleischerei|gasthof|landgasthof|gasthaus|"
    r"hotel|restaurant|café|cafe|bistro|pizzeria|pension|brauerei|weingut|praxis|"
    r"\w*praxis|kanzlei|\w*kanzlei|apotheke|\w*apotheke|autohaus|friseur\w*|"
    r"\w*büro|klinik\w*|\w*klinik|werkstatt|schreinerei|tischlerei|gärtnerei|"
    r"zahnarztpraxis|pflegedienst|sanitätshaus)$"
)

#: A sentence about the firm's history names an owner, not a contact:
#: "… hat Herr X die Traditionsfirma von Herrn Y übernommen." Three parts must
#: agree: a history verb (whole words: "nachfolgend" and "Übernahme" are not
#: history), a firm it happened to, and no contact cue — "Fragen beantwortet
#: Frau X …, Fahrtkosten werden übernommen" is a contact sentence.
_HISTORY_VERB = re.compile(
    r"(?i)\b(?:übernommen|übernahm|gegründet|gründete|verstorben|nachfolge|nachfolger(?:in)?)\b"
    r"|firmengründer|unternehmensgründer"
)
_HISTORY_SUBJECT = re.compile(
    r"(?i)firma|betrieb|unternehm|geschäft|praxis|kanzlei|inhaber|chefärzt|chefarzt|"
    r"traditions|im jahre?\b"
)
_CONTACT_CUE = re.compile(
    r"(?i)ansprech|kontakt|fragen|bewerb|wenden|erreich|telefon|\btel\b|e-mail|melde|"
    r"auskunft|auskünfte"
)


def _is_history(sentence: str) -> bool:
    return bool(
        _HISTORY_VERB.search(sentence)
        and _HISTORY_SUBJECT.search(sentence)
        and not _CONTACT_CUE.search(sentence)
    )

#: Words before a name that are grammar, not part of a role: "Ihnen gern die
#: Teamleitung" → "Teamleitung".
_ROLE_STOP = {
    "ihnen", "gern", "gerne", "die", "der", "das", "den", "dem", "unsere", "unser",
    "unserer", "unseren", "ihre", "ihr", "ist", "sind", "steht", "stehen", "als",
    "für", "an", "bei", "mit", "von", "und", "oder", "sie", "wenden", "sich",
    "bitte", "per", "e-mail", "mail", "dein", "deine", "dir", "dich", "erteilt",
    "erteilen", "auskünfte", "vorab", "können", "kannst", "zur", "zum", "verfügung",
    "&", "co", "kg", "gmbh", "ag", "se", "mbh", "e.v.",
}
#: A contact label is not a role: "Ihre Ansprechpartnerin: Frau X" names no function.
_LABEL_WORD = re.compile(r"(?i)ansprechpartner|ansprechperson|kontakt")

#: Role words — a phrase next to a name is taken as the person's title only if
#: it contains one of these. Keeps "Potsdamer Str. 50" out of `role_title`.
_ROLE_HINT = re.compile(
    r"(?i)(leit|referent|recruit|talent|personal|human|people|hr\b|manager|"
    r"direktor|geschäftsführ|inhaber|assistenz|sachbearbeit|business partner|"
    r"ausbild|koordinat|verwaltung|vorstand|bereich|abteilung|team|chef|head|"
    r"lead|officer|partner|spezialist|berater|pflegedienst|prokurist|"
    r"landrat|bürgermeister|dekan|oberarzt|oberärzt|chefärzt|privatdozent|redakteur|präsident)"
)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-zA-Z]{2,}")
#: German/Austrian phone numbers as ads write them: "0395 5442681",
#: "(02323/16-3221)", "+43 664 4930931", "05423-4764416".
_PHONE = re.compile(r"(?<![\w/])(?:\+\d{2}[\s(]*0?\)?\s*|0)\d{2,5}[\s/-]*\d[\d\s/-]{3,14}\d")

#: Local parts that name a function, not a person: bewerbung@, jobs@, hr@ …
_GENERIC_LOCAL = re.compile(
    r"(?i)^(bewerbung|bewerbungen|jobs?|karriere|career|careers|hr|personal|"
    r"personalabteilung|info|recruiting|recruitment|talent|apply|application|"
    r"datenschutz|privacy|kontakt|contact|office|mail|post|service|team|"
    r"verwaltung|zentrale|sekretariat|ausbildung|stellen|noreply|no-reply)"
)

#: How far around a name to look for the same person's role, phone and e-mail.
_WINDOW_AFTER = 220
_WINDOW_BEFORE = 90


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ContactMention:
    """One person named in one ad text, with the line that names them."""

    full_name: str
    salutation: str | None  # "Frau" | "Herr" | None
    first_name: str | None
    last_name: str
    role_title: str | None
    email: str | None
    phone: str | None
    quote: str
    #: "direct" | "switchboard" | None — see `phone_kind`.
    phone_kind: str | None = None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _fold(value: str) -> str:
    """Lowercase ASCII fold for comparing names with e-mail local parts:
    "Grümbel" ↔ "gruembel"."""
    value = value.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    value = value.replace("ß", "ss")
    return "".join(
        c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)
    )


def _clean(text: str) -> str:
    """Strip the markdown the source uses (``**bold**``, ``[x](mailto:x)``) so
    a name in bold still reads as a name. Line breaks are kept: they are the
    most reliable boundary a contact block has."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("**", "").replace("\\*", "*").replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", text)


def _trim_name(raw: str, following: str) -> tuple[str | None, str | None]:
    """(name, leading role). Drop tokens a greedy match swallowed, and reject
    the match if nothing name-shaped remains.

    `following` is the text right after the raw match. Three rules, each from
    a real ad:

      * a legal form right after it means the "name" is a company
        ("Vision Consulting GmbH");
      * trailing role, street or filler words go ("Julian Köppel Recruiting",
        "Ann-Kathrin Heuter Wahlerstr", "Sarah Weiler Machen Sie …");
      * a leading role word is split off as the role ("Frau
        Stadtamtsleiterin Ulrike Edtbauer").
    """
    if _LEGAL_FORM_AFTER.match(following):
        return None, None
    tokens = raw.split()
    role = None
    # Leading role words go to the role — all of them: "Chefarzt Privatdozent
    # Dr. Jonas Diehm" is Jonas Diehm, Chefarzt Privatdozent.
    roles: list[str] = []
    while True:
        bare_idx = [i for i, t in enumerate(tokens) if not re.fullmatch(_TITLE, t)]
        if len(bare_idx) >= 2 and _ROLE_HINT.search(tokens[bare_idx[0]]):
            roles.append(tokens.pop(bare_idx[0]))
            continue
        break
    role = " ".join(roles) or None

    def bare() -> list[str]:
        return [t for t in tokens if not re.fullmatch(_TITLE, t)]

    trailing = following
    while len(bare()) > 1 and (
        tokens[-1].rstrip(".,") in _NOT_NAMES
        or tokens[-1].rstrip(".,") in _CAPS_NOT_NAMES
        or _ROLE_HINT.search(tokens[-1])
        or _is_street(tokens[-1], following=trailing, parts=len(bare()))
        # A business word ends a name only after a full name: "Cordula Steiner
        # Gasthof", never "Maria Salon".
        or (len(bare()) >= 3 and _BUSINESS.match(tokens[-1]))
    ):
        trailing = f" {tokens.pop()}{trailing}"
    while len(tokens) > 1 and re.fullmatch(_PARTICLE, tokens[-1]):
        tokens.pop()
    # A third token is only trusted when the name ends cleanly (line end,
    # comma, bracket). "Anna Maria Lombardo\n" is a name; "Isabella Luczak
    # Hausbank München" runs on into the next words.
    if len(bare()) == 3 and re.match(rf"^ +[{_UPPER}{_LOWER}]", following):
        tokens.pop()
    names = bare()
    if (
        not names
        or names[0] in _NOT_NAMES
        or tokens[-1] in _NOT_NAMES
        or any(t in _CAPS_NOT_NAMES for t in names)
    ):
        return None, None
    if any(_UNIT_WORD.search(t) for t in names):
        return None, None
    if any(_BUSINESS.match(t) for t in names):
        return None, None
    return " ".join(tokens), role


def _split(name: str) -> tuple[str | None, str]:
    """(first, last). A single token after "Frau"/"Herr" is a surname — the
    formal German form ("Herr Trippner"). Without a salutation a single token
    is not accepted at all (see the `_LABELLED` caller)."""
    parts = [p for p in name.split() if not re.fullmatch(_TITLE, p)]
    if len(parts) == 1:
        return None, parts[0]
    return parts[0], " ".join(parts[1:])


def _plausible_role(role: str) -> str | None:
    """A role, or None if the phrase is really an address, a URL or a company
    line that happened to contain a role word ("www.hacker-partner.de",
    "Oblak & Partner GmbH & Co KG"). "Projektmanager bei X GmbH" keeps the
    part before "bei"."""
    role = role.strip(" ,–-/")
    if re.search(r"(?i)www\.|https?:|\.(de|com|at|ch)\b|[@\d]", role):
        return None
    if re.search(r"\b(GmbH|gGmbH|mbH|AG|KG|SE|e\. ?V\.|KdöR|Co\.?)\b", role):
        head = re.split(r"\s+bei\s+", role, maxsplit=1)
        return head[0] if len(head) == 2 and _ROLE_HINT.search(head[0]) else None
    if not _ROLE_HINT.search(role) or _LABEL_WORD.search(role):
        return None
    return role


def _role_near(text: str, start: int, end: int) -> str | None:
    """The person's function, from the phrase right after or right before
    the name: "Frau Katrin Wolter (Pflegedienstleitung)", "…, Leitung Human
    Resources", "unsere Pflegedirektorin Frau Christina Lemke"."""
    after = text[end : end + 90]
    m = re.match(r"\s*\(([^)\n]{3,60})\)", after) or re.match(
        r" *[,–-] *([^,\n.;:()]{3,60})", after
    )
    if m and (role := _plausible_role(m.group(1))):
        return role
    # The partner-board layout puts the role on its own line under the name:
    # "Kathrin Telega\nJunior People & Culture Business Partner".
    m = re.match(r" *\n\s*([^\n]{3,60})\n", after + "\n")
    if m and (role := _plausible_role(m.group(1))):
        return role
    # Before the name, same line: walk back over words until grammar starts.
    line = text[: start].rsplit("\n", 1)[-1]
    words: list[str] = []
    for word in reversed(line.rstrip(" ,:").split()):
        # A sentence end is a boundary: "…Jutta Weber unterstützt. Frau Weber"
        # must not read "unterstützt" as part of a role.
        if word.endswith((".", "!", "?")) and not re.fullmatch(_TITLE, word):
            break
        if word in ("-", "–", "|", "·"):
            continue  # "Bereich Personal - Frau Sophie Bennicke"
        bare = word.strip(",:;()–-").rstrip("/")
        if not bare or bare.lower() in _ROLE_STOP or re.search(r"[@\d]", bare):
            break
        words.insert(0, bare)
        if len(words) == 4:
            break
    return _plausible_role(" ".join(words)) if words else None


def _email_for(window: str, first: str | None, last: str) -> str | None:
    """The e-mail in the window that belongs to THIS person — its local part
    contains their surname, or is exactly their first name. A generic
    `bewerbung@` next to a name is the company's inbox, not the person's, and
    is not attributed. Matching on first name alone would hand Susanne Treu the
    address of Susanne Brendler two lines up."""
    folded_last = _fold(last.split()[-1])
    folded_first = _fold(first) if first else None
    for email in _EMAIL.findall(window):
        local = _fold(email.split("@")[0])
        if _GENERIC_LOCAL.match(local):
            continue
        if folded_last in local or (folded_first and local == folded_first):
            return email
    return None


def _phone_in(window: str) -> str | None:
    m = _PHONE.search(window)
    if not m:
        return None
    phone = re.sub(r"\s+", " ", m.group(0)).strip(" /-")
    # Two numbers in a row ("Hotline 0800 / 4007766 0800 / 4007767") match as
    # one run of digits. A space then a fresh area code (at least three digits
    # after the "0": "0800", "0531", "0151", or a "+") after an already
    # complete number (10+ national digits) starts the second one. A trailing
    # two-digit group ("+49 151 571 579 07") is the same number. Groups like "+41 41 553 01 65" or "030 9210 952 00" stay whole:
    # their prefix is too short to be a number on its own.
    for cut in re.finditer(r" (?=\+\d|0[1-9]\d{2})", phone):
        if _national_digits(phone[: cut.start()]) >= 10:
            phone = phone[: cut.start()].strip(" /-")
            break
    # A postcode + house number reads like a short number; require real length.
    return phone if len(re.sub(r"\D", "", phone)) >= 7 else None


def _national_digits(phone: str) -> int:
    """Digits of the number as dialled inside the country: "+49 (0)160 99 80"
    is "0160 99 80" — seven, not ten. The country code and the "(0)" would
    otherwise make a half number look complete."""
    national = re.sub(r"^\+\d{2}\s*(?:\(0\))?\s*", "0", phone.strip())
    return len(re.sub(r"\D", "", national))


#: Service numbers reach a hotline, never a named person. Matched on the
#: number with spaces and slashes removed, so no word boundary after the code.
_SERVICE_NUMBER = re.compile(r"^(?:\+\d{2}(?:\(0\))?|00\d{2}|0)(?:800|180|900|700)")


def phone_kind(phone: str | None) -> str | None:
    """`direct` or `switchboard`. A German extension "-0" is the reception
    desk ("0271/33583-0"), and an 0800/0180 number is a hotline: dialling
    either reaches the company, not the person named next to it."""
    if not phone:
        return None
    compact = re.sub(r"[\s/]", "", phone)
    # "-0" or a lone trailing " 0": "0271/33583-0", "0711 2525 0".
    if re.search(r"[\s-]0$", phone.strip()) or _SERVICE_NUMBER.match(compact):
        return "switchboard"
    return "direct"


_WRAPPED = re.compile(rf" ?\n *({_TOKEN})(?=[ ,(]|$)", re.MULTILINE)


def _wrapped_surname(text: str, end: int) -> str | None:
    """The surname when an ad wraps it onto the next line: "Frau Anna-Lena\\n
    Horn (Recruiterin)". Only called for a single-token saluted name, and
    refused when the next line is an address ("Potsdamer Str. 50")."""
    m = _WRAPPED.match(text, end)
    if not m:
        return None
    token, rest = m.group(1), text[m.end() : m.end() + 6]
    if (
        token in _NOT_NAMES
        or _is_street(token, following=text[m.end() :], parts=2)
        or _BUSINESS.match(token)
        or _ROLE_HINT.search(token)
        or re.match(r"(?i) *(str\b|str\.|\d|&)", rest)
        or _LEGAL_FORM_AFTER.match(text, m.end())
    ):
        return None
    return token


def _first_name_elsewhere(text: str, last: str, salutation: str) -> str | None:
    """"Frau Weber" often has a full-name mention elsewhere in the same ad
    ("unserer Ansprechpartnerin Jutta Weber"). Recover the first name from it
    rather than show a surname alone.

    Only from a mention that is itself introduced as a contact — a label or
    the same salutation right before it. "Frau Büger" in an ad from the
    practice of "Dr. iur. Gerald Büger" is not Gerald.
    """
    for m in re.finditer(rf"\b({_TOKEN}) {re.escape(last)}\b", text):
        token = m.group(1)
        if token in _NOT_NAMES or _ROLE_HINT.search(token) or _LABEL_WORD.search(token):
            continue
        lead = text[max(0, m.start() - 30) : m.start()]
        if re.search(rf"(?:{salutation}n?|Ansprechpartner(?:in)?|Kontakt\w*):? *$", lead):
            return token
    return None


#: A sentence end: . ! ? or a line break — but not the dot of a title ("Dr.",
#: "Mst."), an abbreviation ("z.B.") or an ordinal/date ("3.", "1.1.").
_SENTENCE_END = re.compile(
    r"(?<!\bDr)(?<!\bDDr)(?<!\bProf)(?<!\bMag)(?<!\bMst)(?<!\bIng)(?<!\bDipl)(?<!\bmed)"
    r"(?<!\bz\.B)(?<!\bbzw)(?<!\bca)(?<!\bggf)(?<!\bTel)(?<!\bNr)(?<!\d)[.!?]|\n"
)


def _sentence(text: str, start: int, end: int) -> str:
    """The sentence around a mention, bounded by `_SENTENCE_END`."""
    left = 0
    for m in _SENTENCE_END.finditer(text, 0, start):
        left = m.end()
    right_m = _SENTENCE_END.search(text, end)
    return text[left : right_m.start() if right_m else len(text)]


def _quote(text: str, start: int, end: int) -> str:
    """The line(s) naming the person — the evidence shown next to the contact."""
    left = text.rfind("\n", 0, max(0, start - 1))
    left = 0 if left == -1 else left + 1
    right = text.find("\n", end)
    right = len(text) if right == -1 else right
    snippet = text[left:right].strip()
    if len(snippet) > 240:
        lo = max(0, start - left - 100)
        snippet = ("…" if lo else "") + snippet[lo : lo + 240].strip() + "…"
    return snippet


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def extract_contacts(text: str | None) -> list[ContactMention]:
    """Every person an ad text names as a contact, in order of appearance.

    Three forms are recognised, each of which puts a person in front of a
    reader on purpose:

      * a salutation — "Frau Katrin Wolter", "Herrn Dr. Benjamin Schmidt",
        "Herr Trippner" (surname only is the formal German form);
      * a contact label with at least first + last name — "Ansprechpartnerin:
        Jutta Dziobek", "Recruiter*in: Jana Lawinsky". A single bare word after
        a label is not accepted: it is as likely to be a department as a person;
      * a contact heading with the name alone on the next line — the
        partner-board layout ("Deine Ansprechperson für weitere Fragen" /
        "Kathrin Telega" / "Junior People & Culture Business Partner").
    """
    if not text:
        return []
    clean = _clean(text)
    found: dict[str, ContactMention] = {}
    spans: list[tuple[int, int]] = []

    def add(
        start: int, end: int, name: str, salutation: str | None, lead_role: str | None
    ) -> None:
        if any(s <= start < e for s, e in spans):
            return
        first, last = _split(name)
        if salutation and first is None:
            first = _first_name_elsewhere(clean, last, salutation)
            if first:
                titles = [t for t in name.split() if re.fullmatch(_TITLE, t)]
                name = " ".join([*titles, first, last])
        if _is_history(_sentence(clean, start, end)):
            return
        window = clean[max(0, start - _WINDOW_BEFORE) : end + _WINDOW_AFTER]
        tail = clean[end : end + _WINDOW_AFTER]
        phone = _phone_in(tail)
        mention = ContactMention(
            full_name=name,
            salutation=salutation,
            first_name=first,
            last_name=last,
            role_title=lead_role or _role_near(clean, start, end),
            email=_email_for(window, first, last),
            phone=phone,
            quote=_quote(clean, start, end),
            phone_kind=phone_kind(phone),
        )
        spans.append((start, end))
        key = _fold(last)
        existing = found.get(key)
        # Keep the fuller mention of the same person: "Frau Weber" and
        # "Ansprechpartnerin Jutta Weber" in one text are one person.
        if existing is None or (existing.first_name is None and first is not None):
            found[key] = mention

    for m in _SALUTED.finditer(clean):
        name, lead_role = _trim_name(m.group("name"), clean[m.end() :])
        rank = " ".join(t for t in m.group("rank").split() if not re.fullmatch(_TITLE, t))
        if rank:
            lead_role = " ".join(p for p in (rank, lead_role) if p)
        if name:
            sal = "Frau" if m.group("sal") == "Frau" else "Herr"
            end = clean.find(name, m.start("name")) + len(name)
            if len([t for t in name.split() if not re.fullmatch(_TITLE, t)]) == 1:
                wrapped = _wrapped_surname(clean, end)
                if wrapped:
                    name = f"{name} {wrapped}"
                    end = clean.find(wrapped, end) + len(wrapped)
            add(m.start(), end, name, sal, lead_role)

    for m in _HEADED.finditer(clean):
        name, lead_role = _trim_name(m.group("name"), clean[m.end() :])
        if name and len([p for p in name.split() if not re.fullmatch(_TITLE, p)]) >= 2:
            start = clean.find(name, m.start("name"))
            add(start, start + len(name), name, None, lead_role)

    for m in _LABELLED.finditer(clean):
        name, lead_role = _trim_name(m.group("name"), clean[m.end() :])
        if name and len([p for p in name.split() if not re.fullmatch(_TITLE, p)]) >= 2:
            start = clean.find(name, m.start("name"))
            add(start, start + len(name), name, None, lead_role)

    return sorted(found.values(), key=lambda c: clean.find(c.full_name))


def company_mailboxes(text: str | None) -> list[str]:
    """Function inboxes an ad gives — `bewerbung@`, `jobs@`. The company's
    channel rather than a person's, shown apart from the named contacts."""
    if not text:
        return []
    seen: list[str] = []
    for email in _EMAIL.findall(_clean(text)):
        email = email.lower().rstrip(".")
        if _GENERIC_LOCAL.match(email.split("@")[0]) and email not in seen:
            seen.append(email)
    return seen


def person_key(first_name: str | None, last_name: str) -> str:
    """Identity for merging one person across several ads of the same employer.

    Surname-keyed on purpose: the same recruiter appears as "Frau Bennicke" in
    one ad and "Sophie Bennicke" in the next. Two different people sharing a
    surname at one employer is rarer than one person written two ways.
    """
    return _fold(last_name.split()[-1])
