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


def pdf_to_text(content: bytes) -> str:
    """Extract text from a PDF byte string. Empty string if it can't be read."""
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
    return "\n".join(parts)


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