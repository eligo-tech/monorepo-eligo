"""Sprachkenntnisse with a level (ELI-56).

`candidates.languages` stays what it always was — a list of strings — and a
level is written into the entry as "Sprache (Niveau)". So "Deutsch" from an
import or an older CV stays valid and simply has no level, and every reader of
the list (cover sheet, presentation, matching, notices) keeps working.

The scale is LinkedIn's five steps, in German. Only words that plainly name a
step are read as one; anything else ("C1", "gut in Wort und Schrift") is kept
exactly as written and gets no level — mapping it would be a guess.
"""

from __future__ import annotations

import re
import unicodedata

#: LinkedIn: Native or bilingual · Full professional · Professional working ·
#: Limited working · Elementary. Stored values — data, not copy.
LANGUAGE_LEVELS: tuple[str, ...] = (
    "Muttersprache",
    "Verhandlungssicher",
    "Fließend",
    "Erweiterte Grundkenntnisse",
    "Grundkenntnisse",
)

#: What a CV or a person writes → the step it names. Exact phrases only.
_SYNONYM_WORDS: dict[str, str] = {
    **{w: "Muttersprache" for w in (
        "muttersprache", "muttersprachlich", "zweisprachig", "bilingual",
        "native", "native speaker", "native or bilingual", "native or bilingual proficiency",
    )},
    **{w: "Verhandlungssicher" for w in (
        "verhandlungssicher", "business fluent", "full professional",
        "full professional proficiency",
    )},
    **{w: "Fließend" for w in (
        "fließend", "fliessend", "fluent", "gute kenntnisse", "sehr gute kenntnisse",
        "fließend / gute kenntnisse", "professional working", "professional working proficiency",
    )},
    **{w: "Erweiterte Grundkenntnisse" for w in (
        "erweiterte grundkenntnisse", "limited working", "limited working proficiency",
    )},
    **{w: "Grundkenntnisse" for w in (
        "grundkenntnisse", "basiskenntnisse", "elementary", "elementary proficiency",
    )},
}

# "Englisch (fließend)" · "Englisch – fließend" · "Englisch - fließend" · "Englisch: fließend"
_PAREN = re.compile(r"^(?P<name>.+?)\s*\((?P<level>[^()]+)\)\s*$")
_DASH = re.compile(r"^(?P<name>.+?)\s*(?:\s[-–—]\s|:)\s*(?P<level>.+?)\s*$")


def _norm(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


#: Keys through the same `_norm` as a lookup — casefold turns "ß" into "ss".
_SYNONYMS: dict[str, str] = {_norm(k): v for k, v in _SYNONYM_WORDS.items()}


def _parts(entry: str) -> tuple[str, str, str] | None:
    """(name, raw level as written, canonical level) — or None."""
    text = entry.strip()
    for pattern in (_PAREN, _DASH):
        m = pattern.match(text)
        if m:
            level = _SYNONYMS.get(_norm(m.group("level")))
            if level and m.group("name").strip():
                return m.group("name").strip(), m.group("level").strip(), level
    return None


def split_language(entry: str) -> tuple[str, str | None]:
    """("Englisch", "Fließend") — or the entry as written and None."""
    parts = _parts(entry)
    if parts is None:
        return entry.strip(), None
    return parts[0], parts[2]


def normalise_language(entry: str) -> str:
    """The canonical spelling: "Englisch (Fließend)". Idempotent."""
    name, level = split_language(entry)
    return f"{name} ({level})" if level else name


def normalise_languages(entries: list[str] | None) -> list[str] | None:
    if entries is None:
        return None
    return [normalise_language(e) for e in entries if e and e.strip()]


def split_languages(value: str | None) -> list[str] | None:
    """A CV's language list → entries, split on ';' or ',' — but never inside
    brackets, so "Englisch (fließend, C1)" stays one entry."""
    if not value:
        return None
    items: list[str] = []
    depth, current = 0, []
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        if ch in ",;" and depth == 0:
            items.append("".join(current))
            current = []
        else:
            current.append(ch)
    items.append("".join(current))
    out = [i.strip() for i in items if i.strip()]
    return out or None


def ground_language_levels(entries: list[str] | None, source: str) -> list[str] | None:
    """Evidence rule for a CV: a level stays only when the word that names it
    is in the document. A level the model added on its own is dropped; the
    language stays."""
    if entries is None:
        return None
    text = _norm(source)
    out: list[str] = []
    for entry in entries:
        parts = _parts(entry)
        if parts is None:
            out.append(entry.strip())
        # A whole word: "native" inside "alternative" is no evidence.
        elif re.search(rf"(?<!\w){re.escape(_norm(parts[1]))}(?!\w)", text):
            out.append(f"{parts[0]} ({parts[2]})")
        else:
            out.append(parts[0])
    return out
