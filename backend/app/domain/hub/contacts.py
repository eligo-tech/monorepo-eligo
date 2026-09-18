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
#: Academic / professional prefixes, kept as part of the displayed name.
_TITLE = r"(?:Dr\.|Prof\.|Mag\.|DI|Dipl\.-[A-Z][a-z]+\.|MBA|Ing\.)"

#: Spaces only between tokens, never a line break: a contact block puts the
#: street on the next line, and "Sophie Bennicke\nEhrenbachstraße" is two
#: things. The trailing lookahead stops a token being cut mid-word ("GmbH"
#: must not yield "Gmb").
_NAME = (
    rf"(?:{_TITLE} +)*{_TOKEN}(?: +(?:{_PARTICLE} +)?{_TOKEN}){{0,2}}"
    rf"(?![{_LOWER}{_UPPER}])"
)

#: "Frau Katrin Wolter", "Herrn Dr. Benjamin Schmidt", "Herr Trippner".
_SALUTED = re.compile(rf"\b(?P<sal>Frau|Herrn?) +(?P<name>{_NAME})")

#: "Ansprechpartnerin: Jutta Dziobek" — a contact label, then a bare name.
#: Requires the colon or a line break: "Ansprechpartner für Patienten" is a
#: duty in a task list, not a person, and is the commonest false positive.
_LABELLED = re.compile(
    rf"\b(?:Ihr(?:e)?\s+)?(?:Ansprechpartner(?:in)?|Ansprechperson|Kontaktperson|Kontakt)"
    rf"\s*(?::|\n)\s*(?P<name>{_NAME})"
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
}

#: The name is a company if a legal form follows it: "Vision Consulting GmbH".
_LEGAL_FORM_AFTER = re.compile(r"^ *(?:GmbH|gGmbH|mbH|AG|KG|SE|e\. ?V\.|OHG|UG|GbR|Gmb)\b")
#: Street-shaped tokens a name must not end in: "Friedrich-Mohr-Straße", "Wahlerstr".
_STREET = re.compile(r"(?i)(stra(ss|ß)e|str\.?|allee|weg|platz|ring|gasse|damm|ufer)$")

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
    r"lead|officer|partner|spezialist|berater|pflegedienst)"
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
    bare_idx = [i for i, t in enumerate(tokens) if not re.fullmatch(_TITLE, t)]
    if len(bare_idx) >= 2 and _ROLE_HINT.search(tokens[bare_idx[0]]):
        role = tokens.pop(bare_idx[0])

    def bare() -> list[str]:
        return [t for t in tokens if not re.fullmatch(_TITLE, t)]

    while len(bare()) > 1 and (
        tokens[-1].rstrip(".,") in _NOT_NAMES
        or _ROLE_HINT.search(tokens[-1])
        or _STREET.search(tokens[-1])
    ):
        tokens.pop()
    while len(tokens) > 1 and re.fullmatch(_PARTICLE, tokens[-1]):
        tokens.pop()
    # A third token is only trusted when the name ends cleanly (line end,
    # comma, bracket). "Anna Maria Lombardo\n" is a name; "Isabella Luczak
    # Hausbank München" runs on into the next words.
    if len(bare()) == 3 and re.match(rf"^ +[{_UPPER}{_LOWER}]", following):
        tokens.pop()
    names = bare()
    if not names or names[0] in _NOT_NAMES or tokens[-1] in _NOT_NAMES:
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


def _role_near(text: str, start: int, end: int) -> str | None:
    """The person's function, from the phrase right after or right before
    the name: "Frau Katrin Wolter (Pflegedienstleitung)", "…, Leitung Human
    Resources", "unsere Pflegedirektorin Frau Christina Lemke"."""
    after = text[end : end + 90]
    m = re.match(r"\s*\(([^)\n]{3,60})\)", after) or re.match(
        r" *[,–-] *([^,\n.;:()]{3,60})", after
    )
    if (
        m
        and _ROLE_HINT.search(m.group(1))
        and not _LABEL_WORD.search(m.group(1))
        and not re.search(r"[@\d]", m.group(1))
    ):
        return m.group(1).strip(" ,–-/")
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
    role = " ".join(words)
    if role and _ROLE_HINT.search(role) and not _LABEL_WORD.search(role):
        return role
    return None


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
    # A postcode + house number reads like a short number; require real length.
    return phone if len(re.sub(r"\D", "", phone)) >= 7 else None


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
        or _STREET.search(token)
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

    Two forms are recognised, both of which put a person in front of a reader
    on purpose:

      * a salutation — "Frau Katrin Wolter", "Herrn Dr. Benjamin Schmidt",
        "Herr Trippner" (surname only is the formal German form);
      * a contact label with at least first + last name — "Ansprechpartnerin:
        Jutta Dziobek". A single bare word after a label is not accepted: it
        is as likely to be a department as a person.
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
        window = clean[max(0, start - _WINDOW_BEFORE) : end + _WINDOW_AFTER]
        tail = clean[end : end + _WINDOW_AFTER]
        mention = ContactMention(
            full_name=name,
            salutation=salutation,
            first_name=first,
            last_name=last,
            role_title=lead_role or _role_near(clean, start, end),
            email=_email_for(window, first, last),
            phone=_phone_in(tail),
            quote=_quote(clean, start, end),
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
        if name:
            sal = "Frau" if m.group("sal") == "Frau" else "Herr"
            end = clean.find(name, m.start("name")) + len(name)
            if len([t for t in name.split() if not re.fullmatch(_TITLE, t)]) == 1:
                wrapped = _wrapped_surname(clean, end)
                if wrapped:
                    name = f"{name} {wrapped}"
                    end = clean.find(wrapped, end) + len(wrapped)
            add(m.start(), end, name, sal, lead_role)

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
