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
#: Austria (ELI-30): UID "ATU" + 8 digits; Firmenbuch number = digits + a
#: check letter ("FN 56945v", "Firmenbuch: Innsbruck FN 56945v",
#: "Firmenbuch: 36141z"). Switzerland: UID "CHE-123.456.789".
_VAT_AT = re.compile(r"\bATU\s?(\d{8})\b")
_VAT_CH = re.compile(r"\bCHE[-\s]?(\d{3})\.?(\d{3})\.?(\d{3})\b")
_FIRMENBUCH = re.compile(
    r"\b(?:FN|Firmenbuch(?:nummer)?\s*:?)\s*(?:([A-ZÄÖÜ][a-zäöüß]+)\s+)?(?:FN\s*)?(\d{1,6})\s?([a-z])\b"
)
#: "Handelsgericht Wien", "Handelgericht: Korneuburg" (sic, measured),
#: "Firmenbuchgericht: Landesgericht Krems/Donau".
_COURT_AT = re.compile(
    r"(?:Firmenbuchgericht|Landesgericht|Handelsgericht|Handelgericht)\s*:?\s*"
    r"(?:Landesgericht\s+|Handelsgericht\s+)?([A-ZÄÖÜ][\wäöüß]+)"
)
_COURT = re.compile(
    r"Amtsgericht\s*:?\s*([A-ZÄÖÜ][\wäöüß]+"
    r"(?:\s(?:am|an der|im|in der|ob der)\s[A-ZÄÖÜ][\wäöüß]+|-[A-ZÄÖÜ][\wäöüß]+)?)"
)
#: "Telefax" starts with "Tel" — the label must end where the word does.
#: "t: +43 …" / "T 0731 …" — a lone T, as several measured sites write it.
_PHONE_LABEL = re.compile(r"^(?:Telefon|Tel\.|Tel\b|Fon\b|Phone|T\b)\s*\.?:?\s*(.*)$", re.IGNORECASE)
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
    r"Amtsgericht|Registergericht|Handelsregister|"
    r"\bUID\b|\bATU\d|Firmenbuch|Handelsgericht|Landesgericht|\bFN\s?\d",
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
        values = [value]
        if not m.group(2).strip():
            # "Geschäftsführer:" then one name per line.
            for follow in lines[i + 2 : i + 5]:
                if not _PERSON.match(follow):
                    break
                values.append(follow)
        quote = line if m.group(2).strip() else " ".join([line, *values])
        for value_line in values:
            for part in re.split(r"\s*(?:,|&|\||\bund\b|;)\s*", value_line):
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
    vat_id = "DE" + "".join(vat.groups()) if vat else None
    if vat_id is None and (at := _VAT_AT.search(body)):
        vat_id = "ATU" + at.group(1)
    if vat_id is None and (ch := _VAT_CH.search(body)):
        vat_id = "CHE" + "".join(ch.groups())
    register = _REGISTER.search(body)
    firmenbuch = None if register else _FIRMENBUCH.search(body)
    if not (vat_id or register or firmenbuch or markers >= 2):
        return ImpressumFacts(is_impressum=False)

    # The court beside THIS register — a GmbH & Co. KG also names its general
    # partner's court further down.
    court = None
    if register:
        nearby = body[max(0, register.start() - 80) : register.end() + 80]
        court = _COURT.search(nearby) or _COURT.search(body)
    elif firmenbuch:
        court = _COURT_AT.search(body)
        if court is None and firmenbuch.group(1):
            court = firmenbuch  # "Firmenbuch: Innsbruck FN 56945v" — group 1 is the court
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
        vat_id=vat_id,
        register_type=register.group(1) if register else ("FN" if firmenbuch else None),
        register_number=(
            register.group(2) if register else (firmenbuch.group(2) + firmenbuch.group(3) if firmenbuch else None)
        ),
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
    markers = [i for i, line in enumerate(lines) if _LEGAL_MARKER.search(line)][:6]
    if not markers:
        return False
    # The lines before each of the first legal markers: one stray
    # "Geschäftsführung" in the navigation must not be the only window.
    window = {j for i in markers for j in range(max(0, i - _WINDOW_BEFORE), i + 1)}
    multiword = {k for k in _whole_names(firm_names) if len(k) >= 4}
    multiword |= {_squash(normalize_company_name(n)) for n in firm_names}
    multiword = {k for k in multiword if len(k) >= 4}
    for j in sorted(window):
        line = lines[j]
        if len(line) > 100:
            continue
        squashed = _squash(line)
        # A company line ("FOCUS search GmbH") may name the firm anywhere in
        # it; any other line must START with a distinctive name — "Erika
        # Schmidt" is a person, not Schmidt Personal GmbH.
        if _LEGAL_FORM.search(line.lower()):
            if any(k in squashed for k in multiword):
                return True
        elif any(squashed.startswith(k) and (len(k) >= 8 or k in _joined(firm_names)) for k in multiword):
            return True
    return False


_LEGAL_FORM = re.compile(
    r"\b(?:gmbh|mbh|gesmbh|ag|ug|kg|ohg|gbr|e\.\s?k\.?|se|kgaa|e\.\s?v\.|partg)\b"
    r"|\bm\.\s?b\.\s?h\b"  # Austrian "Gesellschaft m.b.H."
)


def _joined(firm_names: list[str]) -> set[str]:
    """First two words joined — a multi-word name, safe to match at a line start."""
    out = set()
    for name in firm_names:
        words = [_squash(w) for w in name.split() if _squash(w)]
        if len(words) >= 2:
            out.add(words[0] + words[1])
    return out


# ---------------------------------------------------------------------------
# Links — same site only, never an internal address
# ---------------------------------------------------------------------------

_LINK = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_IMPRESSUM_LINK = re.compile(r"impressum|imprint|legal[\s_-]?notice|anbieterkennzeichnung", re.IGNORECASE)


def public_host(url: str) -> bool:
    """http(s), default port, a name — not an IP literal, not localhost."""
    parts = urlparse(url)
    try:
        port = parts.port  # raises on ":abc" or ":99999"
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or port is not None:
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
