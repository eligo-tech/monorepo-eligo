"""Reading a job advert into a Suchprofil — the seam, and the shared parts.

ELI-6: *"das tool soll die [Stellenanzeige] Parsen können und darüber den Job
anlegen"*. A recruiter has a link to the client's advert; retyping the title,
the band, the region and the Muss-Kriterien out of it is the hour nobody
wants, and it is where a search quietly arrives different from the one the
client described.

Two boundaries this file sets, and both matter more than the parsing:

**The extractor PROPOSES.** Nothing here writes a `Job`. The endpoint returns
fields with confidence and the recruiter saves them from the form they were
going to fill in anyway. Hard criteria are the reason: `must_have_skills`
feeds `apply_hard_filters`, which EXCLUDES people, and a model deciding who
is excluded is exactly what ARCHITECTURE.md RULE 5 forbids.

**This is not ingestion.** RULE 1 keeps users away from crawling public
sources, and this fetches a URL a user pasted. The distinction is what the
fetch is *for*: nothing here touches `hub_*`, follows a link, enumerates a
board, or runs on a schedule. It reads one document a recruiter is holding,
for their own record — the same shape as uploading that advert as a PDF,
which the product has always allowed. `fetch.py` enforces the "one document"
part rather than leaving it to good intentions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Protocol, runtime_checkable


@dataclass
class ProposedField:
    """One value the extractor believes it read, and how sure it is.

    Confidence is the UI's business: a 0.9 title can prefill silently, a 0.4
    salary band should look like a suggestion. Nothing downstream treats it
    as truth.
    """

    value: str
    confidence: float = 0.5


@dataclass
class JobSpec:
    """What an advert can say that a mandate has a field for.

    Deliberately a subset of `JobCreate`. The client company and the contact
    are NOT here: an advert names the employer, and resolving that to a row
    in this workspace's `companies` is an identity decision, not a parse.
    Guessing it would attach a mandate to the wrong client.
    """

    title: ProposedField | None = None
    location: ProposedField | None = None
    salary_min: ProposedField | None = None
    salary_max: ProposedField | None = None
    employment_form: ProposedField | None = None
    must_have_skills: list[ProposedField] = field(default_factory=list)
    #: The advert's own words, kept so a recruiter can check any proposal
    #: against the source without opening the link again.
    excerpt: str = ""

    def as_dict(self) -> dict:
        one = lambda f: None if f is None else {"value": f.value, "confidence": f.confidence}  # noqa: E731
        return {
            "title": one(self.title),
            "location": one(self.location),
            "salary_min": one(self.salary_min),
            "salary_max": one(self.salary_max),
            "employment_form": one(self.employment_form),
            "must_have_skills": [
                {"value": s.value, "confidence": s.confidence} for s in self.must_have_skills
            ],
            "excerpt": self.excerpt,
        }


@runtime_checkable
class JobSpecExtractor(Protocol):
    """text → a proposed Suchprofil. The same shape as `CVExtractor`."""

    def extract(self, text: str) -> JobSpec: ...


# ── HTML → text ────────────────────────────────────────────────────────────
#
# stdlib rather than a parser dependency: the job is to drop tags and keep
# the words, and an advert is not adversarial markup.

_DROP = {"script", "style", "noscript", "svg", "head"}
_BREAK = {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._muted = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROP:
            self._muted += 1
        if tag == "title":
            self._in_title = True
        # og:title is the advert's own idea of its headline and survives the
        # site chrome that a <title> usually carries.
        if tag == "meta":
            got = dict(attrs)
            if got.get("property") == "og:title" and got.get("content") and not self.title:
                self.title = got["content"] or ""
        if tag in _BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP and self._muted:
            self._muted -= 1
        if tag == "title":
            self._in_title = False
        if tag in _BREAK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._muted:
            return
        if self._in_title and not self.title:
            self.title = data.strip()
        self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """(plain text, the document's own title). Never raises on bad markup."""
    parser = _Text()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # malformed markup: keep whatever was parsed
        pass
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text)
    return text.strip(), parser.title.strip()
