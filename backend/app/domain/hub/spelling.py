"""Forgiving search terms for the corpus.

The Markt search is keyword matching against 360,126 postings, and a keyword
that is one character off matches nothing at all. Measured on the live corpus:

    lower(city) like '%münchen%'    3,122 rows
    lower(city) like '%muenchen%'       0 rows
    lower(title) like '%embedded%'    188 rows
    lower(title) like '%embeded%'       0 rows

Both zeroes are the search failing, not the corpus being empty — and neither is
an exotic input. "Muenchen" is what a German writes when the keyboard fights
back; "embeded" is a typo nobody notices in their own typing.

Two deliberate limits:

* **Only for a term that found nothing.** A term with hits is never rewritten:
  guessing at a word that worked is how a search starts answering a question
  nobody asked.
* **Never silently.** `search_employers` reports what it substituted, and the
  UI says "Ergebnisse für „embedded"". A search that quietly corrects you
  teaches you to distrust its zero results.

The rewrite keeps the SQL predicates on `lower(col)`, the exact expressions
migration 0016 indexed with pg_trgm. Folding the column instead — `lower()`
wrapped in replaces — would make every index in that migration unusable and
turn a 0.5 ms bitmap scan into the 122 s sequential scan `_term_matches`
documents.
"""

from __future__ import annotations

import difflib
import re

#: Umlaut written out ↔ umlaut typed. One pair, applied both ways.
_PAIRS = (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"))

_WORD = re.compile(r"[a-zA-ZäöüÄÖÜß0-9]+")


def umlaut_variants(term: str) -> list[str]:
    """Other spellings of the same word, most likely first.

    "muenchen" → ["münchen"], "münchen" → ["muenchen"], "grosshandel" →
    ["großhandel"]. Every substitution is applied at once rather than in
    combination: a word mixing both conventions is a typo, not a spelling, and
    the combinations grow 2^n for a gain nobody has ever needed.

    These are candidates, not corrections — "neue" yields "nü", which exists in
    no German word. The caller only keeps a variant the corpus confirms, which
    is why generating a wrong one costs nothing.
    """
    out: list[str] = []
    for umlaut, ascii_pair in _PAIRS:
        if ascii_pair in term:
            out.append(term.replace(ascii_pair, umlaut))
        if umlaut in term:
            out.append(term.replace(umlaut, ascii_pair))
    seen = set()
    return [v for v in out if v != term and not (v in seen or seen.add(v))]


def has_other_spelling(q: str | None) -> bool:
    """Could any word here be the other umlaut convention? Pure, no queries.

    The router uses this to decide whether a search is worth re-checking at
    all. A thin answer is the obvious trigger, but it is not sufficient:
    "muenchen" finds 298 employers with München in their NAME while missing
    the 2,973 in the city, which looks like a perfectly good answer and is
    not. Any word carrying "ue", "oe", "ae" or "ss" earns the extra probes;
    everything else keeps the fast path.
    """
    return any(
        len(variant) >= 4
        for word in (q or "").lower().split()
        for variant in umlaut_variants(word)
    )


def closest_word(term: str, texts: list[str], *, floor: float = 0.72) -> str | None:
    """The word in `texts` that the term most likely meant to be.

    `texts` are whole titles or company names; the answer is one WORD out of
    them, because the term is one word. "embeded" against "Embedded Software
    Engineer (m/w/d)" has to come back as "embedded" — rewriting the query to
    the entire title would then match only that one posting.

    The term itself is never the answer, even when it occurs verbatim. The
    corpus contains other people's typos: a trigram lookup for
    "pflegefachkaft" returns, first and most similar, the two ads out of
    360,126 that carry the same slip. Accepting the word back would turn the
    rescue into a no-op precisely where it is needed.

    `floor` is a similarity, not an edit count: 0.72 keeps "embeded"→"embedded"
    (0.93) and "pflegefachkaft"→"pflegefachkraft" (0.97) while refusing
    "sap"→"sap-berater" and the short-word collisions that make a fuzzy search
    feel random. Below it the term stays as typed and the search honestly
    returns nothing.
    """
    best: tuple[float, str] | None = None
    for text in texts:
        for word in _WORD.findall(text.lower()):
            if word == term or abs(len(word) - len(term)) > 3:
                continue
            ratio = difflib.SequenceMatcher(None, term, word).ratio()
            if ratio >= floor and (best is None or ratio > best[0]):
                best = (ratio, word)
    return best[1] if best else None
