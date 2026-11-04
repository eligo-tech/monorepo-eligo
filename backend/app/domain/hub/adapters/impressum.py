"""An agency's Impressum — read, and checked to be the agency's own.

German law (§ 5 DDG) makes every commercial site publish who operates it: the
legal name, the register entry, the VAT id, a way to reach them, and who
represents the company. That makes the Impressum the one page that can
VERIFY a website candidate (`domains.py`): a domain is the agency's only when
its Impressum names the agency as the operator.

Same split as every adapter: the functions here are PURE (text or HTML in,
facts out) and CI runs them against captured real pages
(`tests/fixtures/impressum/`, people replaced by placeholders). The fetching
lives in `sites.py`, behind the partner-page discipline (robots.txt,
identified, paced) plus `safe_url`.

People are PARSED here and NOT stored by this PR (decision 2026-11-04,
option A): whether indexing them owes a GDPR Art. 14 notice at collection is
an open legal question. `ImpressumFacts.people` exists so the parser is tested
before anything is kept.

Deterministic on purpose: an Impressum is a structured legal notice, and a
pattern either finds "HRB 23195" or it does not.
"""

from __future__ import annotations

import dataclasses
import ipaddress
import re
from urllib.parse import urljoin, urlparse

from app.domain.hub.domains import registrable_domain
from app.domain.hub.domains import squash as _squash
from app.domain.hub.domains import whole_names as _whole_names
from app.domain.hub.resolution import normalize_company_name

_VAT = re.compile(r"\bDE\s?(\d{3})\s?(\d{3})\s?(\d{3})\b")
_REGISTER = re.compile(r"\b(HR[AB])\s*(?:-?\s*Nr\.?)?\s*[:.]?\s*(\d{1,7})\b")
_COURT = re.compile(
    r"Amtsgericht\s*:?\s*([A-ZÄÖÜ][\wäöüß]+"
    r"(?:\s(?:am|an der|im|in der|ob der)\s[A-ZÄÖÜ][\wäöüß]+|-[A-ZÄÖÜ][\wäöüß]+)?)"
)
_PHONE_LABEL = re.compile(r"^(?:Telefon|Tel\.?|Fon|Phone)\s*\.?:?\s*(.*)$", re.IGNORECASE)
_PHONE = re.compile(r"(?:\+\s?)?\(?\d[\d\s()/.\-–]{5,}\d")
_EMAIL = re.compile(r"([\w.+-]+)\s*(?:@|\(at\)|\[at\])\s*([\w-]+(?:\.[\w-]+)+)", re.IGNORECASE)
#: Function mailboxes — the company's channel, not a person's.
_GENERIC_LOCAL = re.compile(
    r"^(?:info|kontakt|contact|office|jobs|job|bewerbung|bewerbungen|karriere|"
    r"mail|post|service|hallo|hello|team|empfang|zentrale|anfrage|personal)$",
    re.IGNORECASE,
)
_LEGAL_MARKER = re.compile(
    r"\bHR[AB]\b|\bUSt|Umsatzsteuer|Vertreten durch|Geschäftsführ|Inhaber|"
    r"Amtsgericht|Registergericht|Handelsregister",
    re.IGNORECASE,
)
_PEOPLE_LABEL = re.compile(
    r"^(Geschäftsführer(?:in)?|Geschäftsführende[rn]? Gesellschafter(?:in)?|"
    r"Geschäftsführung|Inhaber(?:in)?|Vertreten durch|Vorstand|"
    r"Vertretungsberechtigte[rn]? Geschäftsführer(?:in)?)\s*:?\s*(.*)$"
)
_TITLE = r"(?:Dr\.|Prof\.|Dipl\.-[A-Za-zäöü]+\.?)"
_TOKEN = r"[A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)*"
_PERSON = re.compile(
    rf"^((?:{_TITLE}\s+)*{_TOKEN}(?:\s+(?:von|van|de|zu|der)?\s*{_TOKEN}){{1,3}})$"
)
#: Readable text of a JavaScript-rendered page has none of these. Below this
#: many legal markers a page is not treated as an Impressum.
_WINDOW_BEFORE = 15


@dataclasses.dataclass(frozen=True)
class ImpressumPerson:
    role: str
    name: str
    quote: str


@dataclasses.dataclass(frozen=True)
class ImpressumFacts:
    is_impressum: bool
    vat_id: str | None = None
    register_type: str | None = None
    register_number: str | None = None
    register_court: str | None = None
    phone: str | None = None
    emails: list[str] = dataclasses.field(default_factory=list)
    #: Parsed, NOT stored (see module docstring).
    people: list[ImpressumPerson] = dataclasses.field(default_factory=list)


def _lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").split("\n") if line.strip()]


def _next_value(lines: list[str], i: int, inline: str) -> str:
    return inline.strip() if inline.strip() else (lines[i + 1] if i + 1 < len(lines) else "")


def _people(lines: list[str]) -> list[ImpressumPerson]:
    out: list[ImpressumPerson] = []
    for i, line in enumerate(lines):
        if len(line) > 80:
            continue
        m = _PEOPLE_LABEL.match(line)
        if not m:
            continue
        value = _next_value(lines, i, m.group(2))
        if _PEOPLE_LABEL.match(value):
            continue  # "Vertreten durch:" / "Geschäftsführer: …" — read on its own line
        quote = line if m.group(2).strip() else f"{line} {value}"
        for part in re.split(r"\s*(?:,|&|\||\bund\b|;)\s*", value):
            part = part.strip()
            if _PERSON.match(part):
                out.append(ImpressumPerson(role=m.group(1), name=part, quote=quote[:200]))
    return out


def parse_impressum(text: str | None) -> ImpressumFacts:
    """Company facts and named people, as an Impressum page publishes them."""
    lines = _lines(text or "")
    body = "\n".join(lines)
    markers = sum(1 for line in lines if _LEGAL_MARKER.search(line))
    vat = _VAT.search(body)
    register = _REGISTER.search(body)
    if not (vat or register or markers >= 2):
        return ImpressumFacts(is_impressum=False)

    court = _COURT.search(body) if register else None
    phone = None
    for i, line in enumerate(lines):
        m = _PHONE_LABEL.match(line)
        if m:
            found = _PHONE.search(_next_value(lines, i, m.group(1)))
            if found:
                phone = found.group(0).strip()
                break
    emails: list[str] = []
    for local, domain in _EMAIL.findall(body):
        address = f"{local}@{domain}".lower()
        if _GENERIC_LOCAL.match(local) and address not in emails:
            emails.append(address)

    return ImpressumFacts(
        is_impressum=True,
        vat_id="DE" + "".join(vat.groups()) if vat else None,
        register_type=register.group(1) if register else None,
        register_number=register.group(2) if register else None,
        register_court=court.group(1) if court else None,
        phone=phone,
        emails=emails,
        people=_people(lines),
    )


def names_firm(text: str | None, firm_names: list[str]) -> bool:
    """Does this Impressum name the firm as its OPERATOR?

    Only the operator block counts: the lines just before the first legal
    marker (register, VAT, "Vertreten durch", …). A job board's Impressum
    names the board there and the agency only further down, among its ads —
    the hogapage.de trap from T0.
    """
    lines = _lines(text or "")
    first = next((i for i, line in enumerate(lines) if _LEGAL_MARKER.search(line)), None)
    if first is None:
        return False
    window = lines[max(0, first - _WINDOW_BEFORE) : first + 1]
    keys = {k for k in _whole_names(firm_names) if len(k) >= 4}
    keys |= {_squash(normalize_company_name(n)) for n in firm_names}
    keys = {k for k in keys if len(k) >= 4}
    return any(len(line) <= 100 and any(k in _squash(line) for k in keys) for line in window)


# ---------------------------------------------------------------------------
# Links — same site only, never an internal address
# ---------------------------------------------------------------------------

_LINK = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_IMPRESSUM_LINK = re.compile(r"impressum|imprint|legal[\s_-]?notice|anbieterkennzeichnung", re.IGNORECASE)


def public_host(url: str) -> bool:
    """http(s), default port, a name — not an IP literal, not localhost."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or parts.port not in (None,):
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        ipaddress.ip_address(host)
        return False  # any IP literal: a business site has a name
    except ValueError:
        return "." in host


def safe_url(url: str, domain: str) -> bool:
    """A public URL on the agency's own registrable domain."""
    if not public_host(url):
        return False
    return registrable_domain(urlparse(url).hostname) == domain


def find_impressum_link(html: str | None, base_url: str, domain: str) -> str | None:
    """The homepage's link to its Impressum, on the same site only.

    Measured: bbrecruiting.de links "Impressum" to http://localhost:8093/ —
    a link is followed only when `safe_url` holds.
    """
    for href, label in _LINK.findall(html or ""):
        if _IMPRESSUM_LINK.search(href) or _IMPRESSUM_LINK.search(re.sub(r"<[^>]+>", " ", label)):
            url = urljoin(base_url, href.strip())
            if safe_url(url, domain):
                return url
    return None
