"""CV parsing — PDF → text → structured fields with confidence.

This is a deterministic, dependency-light extractor: regex for contact details,
a skill vocabulary for skills, and positional heuristics for name/title. It is
the stand-in for the LLM document-intelligence model and returns the exact same
``ExtractedField`` contract, so swapping in an LLM is a drop-in change.
"""

from __future__ import annotations

import io
import re

from app.agents.document_extraction import ExtractedField

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\w)(\+?\d[\d\s().-]{7,}\d)(?!\w)")

# Known skills, lower-cased. Matched as whole words against the CV text.
_SKILL_VOCAB = {
    "python", "java", "javascript", "typescript", "go", "rust", "c++", "c#",
    "react", "vue", "angular", "svelte", "next.js", "node.js", "django",
    "flask", "fastapi", "spring", "rails", "postgresql", "mysql", "mongodb",
    "redis", "kafka", "spark", "airflow", "hadoop", "snowflake", "dbt",
    "docker", "kubernetes", "terraform", "aws", "gcp", "azure", "graphql",
    "rest", "grpc", "scala", "kotlin", "swift", "sql", "pandas", "numpy",
    "pytorch", "tensorflow", "m&a", "valuation", "modelling", "controlling",
    "risk", "ifrs", "excel", "powerbi", "tableau",
}

# Lines containing any of these are unlikely to be a person's name — CV section
# headings, role words, and contact markers all produce false positives.
_NAME_STOPWORDS = re.compile(
    r"(curriculum|vitae|lebenslauf|resume|cv|profile|profil|contact|kontakt|"
    r"phone|email|address|www\.|http|@|experience|erfahrung|leadership|"
    r"engineering|summary|zusammenfassung|skills|kenntnisse|education|"
    r"ausbildung|projects|projekte|management|employment|work|references|"
    r"languages|sprachen|certifications|about|senior|junior|developer|"
    r"engineer|manager|consultant|analyst|architect)",
    re.IGNORECASE,
)
_TITLE_HINT = re.compile(
    r"(engineer|developer|manager|director|lead|analyst|consultant|"
    r"architect|designer|scientist|officer|head of|specialist|associate)",
    re.IGNORECASE,
)


def _looks_letter_spaced(line: str) -> bool:
    """True when a line is rendered with a space between every character
    (`S A R A H   B A U S`), a common artefact of PDF text extraction where
    glyph kerning is emitted as spaces. Detected by a high share of
    single-character tokens."""
    toks = line.split()
    if len(toks) < 4:
        return False
    singles = sum(1 for t in toks if len(t) == 1)
    return singles / len(toks) > 0.6


def _despace(text: str) -> str:
    """Collapse letter-spacing while preserving word boundaries. In these PDFs a
    single space separates characters and 2+ spaces separate words, so per
    letter-spaced line we split on the wide gaps and join the narrow ones —
    turning `S A R A H   B A U S` into `SARAH BAUS`. Normal lines are untouched."""
    out: list[str] = []
    for line in text.split("\n"):
        if _looks_letter_spaced(line):
            words = re.split(r" {2,}", line.strip())
            out.append(" ".join(w.replace(" ", "") for w in words))
        else:
            out.append(line)
    return "\n".join(out)


def pdf_to_text(content: bytes) -> str:
    """Extract text from a PDF byte string. Empty string if it can't be read.

    Letter-spacing artefacts are normalized so downstream extraction, grounding
    and display all see clean words rather than `S E N I O R  P M`."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception:
        return ""
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return _despace("\n".join(parts))


def _clean_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


_YEAR_RANGE_RE = re.compile(r"^\d{4}\s*[-–—]\s*(\d{4}|present|heute|now)$", re.IGNORECASE)


def _guess_phone(text: str) -> ExtractedField | None:
    """First match that plausibly is a phone number: 9-15 digits, not a year range."""
    for m in _PHONE_RE.finditer(text):
        raw = m.group(0).strip()
        digits = re.sub(r"\D", "", raw)
        if 9 <= len(digits) <= 15 and not _YEAR_RANGE_RE.match(raw):
            phone = re.sub(r"\s{2,}", " ", raw).strip()
            return ExtractedField(field="phone", value=phone, confidence=0.85)
    return None


def _guess_name(lines: list[str]) -> ExtractedField | None:
    """First plausible 'Firstname Lastname' line near the top of the document."""
    for line in lines[:12]:
        if _NAME_STOPWORDS.search(line):
            continue
        words = line.split()
        if 2 <= len(words) <= 4 and all(
            w[0].isupper() and w.isalpha() for w in words if w
        ):
            return ExtractedField(field="full_name", value=line, confidence=0.7)
    return None


def _guess_title(lines: list[str]) -> ExtractedField | None:
    for line in lines[:20]:
        if _TITLE_HINT.search(line) and len(line) <= 60:
            return ExtractedField(field="current_title", value=line, confidence=0.55)
    return None


# ── Address (ELI-28) ─────────────────────────────────────────────────────────
#
# A German postcode is five digits directly followed by a town: "10115 Berlin",
# "D-80331 München", "Am Hang 3, 80331 München". Read only in the header, where
# a CV puts the candidate's own address — further down five digits next to a
# word are an employer's office. Not preceded by a digit, "+" or "/" so a phone
# number ("+49 30 12345 6789") never yields one.
_HEADER_LINES = 15
_PLZ_RE = re.compile(
    r"(?:^|(?<=[\s,]))(?:D-|DE-)?(\d{5})\s+"
    r"([A-ZÄÖÜ][a-zäöüß]+(?:[ -][A-ZÄÖÜ][a-zäöüß]+)?(?:\s\([^)]{1,40}\))?)"
)
#: Countries a DACH CV names in its address line. The value is kept as WRITTEN
#: — "Germany" stays "Germany"; translating it would not be in the text.
_COUNTRY_RE = re.compile(
    r"(?<!\w)(Deutschland|Germany|Österreich|Austria|Schweiz|Switzerland)(?!\w)"
)


def _guess_address(lines: list[str]) -> list[ExtractedField]:
    out: list[ExtractedField] = []
    for line in lines[:_HEADER_LINES]:
        if m := _PLZ_RE.search(line):
            if _COUNTRY_RE.fullmatch(m.group(2)):
                continue
            out.append(ExtractedField(field="postal_code", value=m.group(1), confidence=0.8))
            out.append(ExtractedField(field="city", value=m.group(2), confidence=0.75))
            break
    for line in lines[:_HEADER_LINES]:
        if m := _COUNTRY_RE.search(line):
            out.append(ExtractedField(field="country", value=m.group(1), confidence=0.8))
            break
    return out


# ── Current position (ELI-28) ────────────────────────────────────────────────
#
# The current job is the one whose period has no end: "03/2021 – heute",
# "seit 01/2020", "2019 – present". A closed period ("2015 – 2019") never is.
_DATE = r"(?:\d{1,2}[./])?\d{4}"
_OPEN_PERIOD_RE = re.compile(
    rf"(?:{_DATE}\s*[-–—]\s*(?:heute|present|now|aktuell|current|today|dato|bis heute)"
    rf"|seit\s+{_DATE}|since\s+{_DATE})",
    re.IGNORECASE,
)
_ANY_PERIOD_RE = re.compile(rf"{_DATE}\s*[-–—]\s*(?:{_DATE}|\w+)|seit\s+{_DATE}", re.IGNORECASE)
_COMPANY_HINT = re.compile(
    r"(?<!\w)(GmbH|AG|SE|KG|KGaA|OHG|UG|e\.\s?V\.|Inc\.?|Ltd\.?|LLC|plc|S\.A\.|B\.V\.|Group|Gruppe)(?!\w)"
)
_SEPARATORS = re.compile(r"\s*[|·•]\s*|\s+[-–—]\s+|\s+(?:bei|at)\s+")


def _company_part(segment: str) -> str:
    """'Beispiel Software GmbH, Berlin' → 'Beispiel Software GmbH' — the town
    after the comma is the office, not the name."""
    head, _, _ = segment.partition(",")
    return head.strip() if _COMPANY_HINT.search(head) else segment.strip()


def _split_role(parts: list[str]) -> tuple[str | None, str | None]:
    parts = [p.strip() for p in parts if p and p.strip()]
    company = next((p for p in parts if _COMPANY_HINT.search(p)), None)
    title = next((p for p in parts if p is not company and _TITLE_HINT.search(p)), None)
    if title is None:
        title = next((p for p in parts if p is not company), None)
    return title, (_company_part(company) if company else None)


def _guess_current_role(lines: list[str]) -> list[ExtractedField]:
    for i, line in enumerate(lines):
        m = _OPEN_PERIOD_RE.search(line)
        if not m:
            continue
        rest = (line[: m.start()] + " | " + line[m.end():]).strip(" |,()")
        if rest:
            title, company = _split_role(_SEPARATORS.split(rest))
        else:
            # Stacked layout: the period on its own line, then title, then employer.
            following: list[str] = []
            for nxt in lines[i + 1 : i + 3]:
                if _ANY_PERIOD_RE.search(nxt):
                    break
                following.append(nxt)
            title, company = _split_role(following)
        out: list[ExtractedField] = []
        if title and len(title) <= 80:
            out.append(ExtractedField(field="current_title", value=title, confidence=0.65))
        if company and len(company) <= 120:
            out.append(ExtractedField(field="current_company", value=company, confidence=0.65))
        return out
    return []


def extract_cv_fields(text: str) -> list[ExtractedField]:
    """Heuristically extract candidate fields from raw CV text.

    Confidence encodes reliability of each heuristic: contact regex is high,
    skills medium, positional guesses (name/title) lower — the lower ones fall
    below the agent's review threshold and are routed to a human.
    """
    fields: list[ExtractedField] = []
    lines = _clean_lines(text)
    lower = text.lower()

    if m := _EMAIL_RE.search(text):
        fields.append(ExtractedField(field="email", value=m.group(0), confidence=0.95))

    if phone := _guess_phone(text):
        fields.append(phone)

    if name := _guess_name(lines):
        fields.append(name)

    fields += _guess_address(lines)

    # The open-ended position names the current job; the positional title
    # guess is only the fallback when no period is open.
    current = _guess_current_role(lines)
    fields += current
    if not any(f.field == "current_title" for f in current):
        if title := _guess_title(lines):
            fields.append(title)

    found_skills = sorted(
        {
            skill
            for skill in _SKILL_VOCAB
            if re.search(rf"(?<![\w+#]){re.escape(skill)}(?![\w+#])", lower)
        }
    )
    if found_skills:
        # More matches → higher confidence, capped.
        confidence = min(0.6 + 0.05 * len(found_skills), 0.9)
        fields.append(
            ExtractedField(
                field="skills", value=", ".join(found_skills), confidence=round(confidence, 2)
            )
        )

    return fields