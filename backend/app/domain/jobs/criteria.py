"""Muss-Kriterien proposed from what the mandate already says.

63 of 76 mandates in the live workspace carry no must-have skills and 72 no
salary band, which makes `matching.apply_hard_filters` a no-op for most of
the book: the deterministic half of the matching rule decides nothing, and
what reaches the recruiter is soft ranking over an unfiltered pool. The
invariant is not violated in code — there is simply nothing for it to apply.

The cheapest honest fix is not to invent criteria but to PROPOSE the ones the
mandate already names. These titles say the stack out loud:

    "Anwendungsentwickler (m/w/d) Java (DevOps)"
    "IT-Spezialist - Kubernetes Cluster und Netzwerkvirtualisierung (NSX)"
    "Senior Software Engineer Golang (m/f/d)"
    "Microsoft 365 & Azure Administrator (m/w/d)"

So: match the title against the vocabulary the workspace's own candidates
use, and hand the recruiter one-click chips. Deterministic, explainable
("der Titel nennt »Java«"), and a proposal — the human commits it, which is
the same rule the agents follow.

No fuzzy matching here on purpose. A near-miss in a search costs a scroll; a
near-miss that becomes a HARD FILTER silently excludes people.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: A term shorter than this matches too much to be a criterion ("C", "KI",
#: "IT"). Two-letter technologies exist; they are not worth the false
#: positives on a filter that excludes people.
_MIN_TERM = 3

#: How many candidates must share a skill before it is worth proposing. One
#: person's idiosyncratic spelling ("Java 8 (Lambda)") is not a criterion.
MIN_VOCABULARY_COUNT = 3


@dataclass(frozen=True)
class Suggestion:
    """One proposed criterion, why it is proposed, and how many it keeps."""

    skill: str
    evidence: str
    candidates: int = 0


def _fold(value: str) -> str:
    """Lowercase, umlaut-folded, punctuation turned into spaces.

    The title writes "Microsoft 365 & Azure Administrator"; the vocabulary
    holds "Azure". Both have to become comparable without either losing its
    word boundaries — which is why punctuation becomes a space rather than
    being deleted: "C#/Java" must not fold into one word.
    """
    lowered = value.lower()
    for umlaut, pair in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        lowered = lowered.replace(umlaut, pair)
    stripped = "".join(
        c for c in unicodedata.normalize("NFD", lowered) if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9+#.]+", " ", stripped).strip()


def _words(value: str) -> list[str]:
    return [w for w in _fold(value).split(" ") if w]


def normalise_vocabulary(skills: list[str]) -> dict[str, int]:
    """Count skills case-insensitively, keeping the commonest spelling.

    The pool writes "DevOps", "devops" and "DEVOPS", and counted separately
    they produce three chips for one criterion. The spelling kept is the one
    most candidates use, because that is the one a reader recognises.
    """
    buckets: dict[str, dict[str, int]] = {}
    for raw in skills:
        if not isinstance(raw, str) or not raw.strip():
            continue
        value = raw.strip()
        buckets.setdefault(_fold(value), {}).setdefault(value, 0)
        buckets[_fold(value)][value] += 1
    out: dict[str, int] = {}
    for spellings in buckets.values():
        total = sum(spellings.values())
        best = max(spellings.items(), key=lambda kv: (kv[1], kv[0]))[0]
        out[best] = total
    return out


def _drop_overlaps(found: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Keep "SAP" or "SAP Business", never both.

    They are chips a recruiter clicks, and clicking both makes the filter
    demand a candidate carry BOTH strings — which is nonsense and silently
    excludes everyone. Where one term contains the other, the one more
    candidates actually have wins: it is the safer filter and the one that
    matches people.
    """
    kept: list[tuple[int, str]] = []
    for count, skill in sorted(found, key=lambda row: (-row[0], len(row[1]))):
        needle = _fold(skill)
        if any(
            needle in _fold(other) or _fold(other) in needle for _, other in kept
        ):
            continue
        kept.append((count, skill))
    return kept


def suggest_must_have(
    title: str,
    vocabulary: dict[str, int],
    *,
    already: list[str] | None = None,
    limit: int = 8,
) -> list[Suggestion]:
    """Skills the TITLE names, drawn from the workspace's own vocabulary.

    `vocabulary` maps a skill to how many candidates carry it; the count is
    what breaks ties, because a term the pool actually uses is the one a
    search will find people by.

    A multi-word skill ("Spring Boot") must appear as a phrase; a single-word
    one must appear as a whole word, so "Java" is not proposed for
    "JavaScript-Entwickler".
    """
    haystack = _words(title)
    if not haystack:
        return []
    phrase = " ".join(haystack)
    taken = {_fold(s) for s in (already or [])}

    found: list[tuple[int, str]] = []
    for skill, count in vocabulary.items():
        if count < MIN_VOCABULARY_COUNT:
            continue
        needle = _fold(skill)
        if len(needle.replace(" ", "")) < _MIN_TERM or needle in taken:
            continue
        parts = needle.split(" ")
        hit = (
            re.search(rf"(?:^| ){re.escape(needle)}(?:$| )", phrase) is not None
            if len(parts) > 1
            else needle in haystack
        )
        if hit:
            found.append((count, skill))

    found = _drop_overlaps(found)
    found.sort(key=lambda row: (-row[0], row[1].lower()))
    return [
        Suggestion(
            skill=skill,
            evidence=f"Der Titel nennt „{skill}“",
            candidates=count,
        )
        for count, skill in found[:limit]
    ]
