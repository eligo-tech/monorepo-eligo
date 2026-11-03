"""Agency or client — and how good a lead — decided by plain code.

A private-recruiter ad (`pav=true`) names ONE firm, and the source carries no
field saying whether that firm is the agency or the agency's client. Measured
2026-11-02 on 600 live ads from 142 firms: the signals below mark 82% as
agencies; of the remaining 18%, about half are clients (KHS, SoftwareOne,
Tipico, Stadt Frankfurt) and half agencies the rules cannot see yet.

So the verdict is three-valued and never a guess: `agency` when only agency
signals fire, `client` when only client signals fire, `unclear` otherwise.
Every verdict and every ranking point carries its evidence (CLAUDE.md:
deterministic code decides, nothing is displayed without its source).

Pure functions, no I/O. `agencies.py` gathers the facts; this decides.
"""

from __future__ import annotations

import dataclasses
import re

from app.domain.hub.resolution import normalize_company_name

AGENCY = "agency"
CLIENT = "client"
UNCLEAR = "unclear"
VERDICTS = (AGENCY, UNCLEAR, CLIENT)

#: Above this many open ads (all branches) a firm is a chain — DIS, Manpower,
#: Brunel — not the small or freelance agency the finder is for.
CHAIN_OPEN_POSTINGS = 50
#: Distinct occupational fields that only a generalist intermediary covers.
FIELD_SPREAD = 3

#: Words that end the firm and start the branch: "Brunel GmbH NL Essen".
#: German register terms only — "office" or "büro" would cut "Home Office
#: Solutions" to "home", and the opt-out list keys on this.
_SITE_TOKENS = {
    "niederlassung", "zweigniederlassung", "nl", "standort", "filiale",
    "geschaeftsstelle",
}
STAFFING_NAME = _STAFFING_NAME = re.compile(
    r"personal|personnel|perso|recruit|consult|beratung|vermittlung|search|"
    r"headhunt|talent|karriere|staffing|career|resources|experts?\b|placement|"
    r"agentur|zeitarbeit|\bhr\b|\bjobs?\b|\btemp\b|human",
    re.IGNORECASE,
)
_PUBLIC_BODY = re.compile(
    r"\b(?:stadt|landkreis|kreisverwaltung|gemeinde|universit\w*|hochschule|"
    r"klinikum|landratsamt|ministerium|bezirksamt|senatsverwaltung)\b",
    re.IGNORECASE,
)
#: An intermediary writing about the firm it recruits FOR. Strict on purpose:
#: the loose "unsere Kunden" matched "unser Kundendienstteam" and employers
#: describing their own customers.
_CLIENT_PHRASE = re.compile(
    r"\bfür (?:unseren|einen|unsere) (?:kunden|mandanten|klienten)\b|"
    r"\bunser(?:em)? (?:kunde|mandant|klient)\b|"
    r"\bunseres (?:kunden|mandanten|klienten)\b|"
    r"\bim auftrag (?:unseres|unserer|eines|einer) (?:kunden|mandanten|klienten)\b",
    re.IGNORECASE,
)
#: An ad for a recruiter AT the agency — the agency is growing.
RECRUITER_ROLE = re.compile(
    r"recruit|personalberat|personaldisponent|personalvermittl|headhunt|"
    r"talent acquisition|personalreferent",
    re.IGNORECASE,
)
_EMAIL_DOMAIN = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
_FREEMAIL = {
    "gmail.com", "googlemail.com", "web.de", "gmx.de", "gmx.net", "t-online.de",
    "outlook.com", "outlook.de", "hotmail.com", "hotmail.de", "yahoo.de",
    "yahoo.com", "icloud.com", "aol.com", "freenet.de", "mail.de",
}
#: Legal forms of a one- or two-person business.
SMALL_LEGAL_FORMS = re.compile(r"^(?:UG|e\.?\s?K|GbR)", re.IGNORECASE)


def group_key(name: str | None) -> str:
    """One agency across its branches: the normalized name, branch cut off.

    Cut only at a REAL branch suffix — a register term with a place after it
    ("Brunel GmbH NL Essen") and at least four letters before it. "Mein
    Standort GmbH" and "Die Filiale GmbH" are names, not branches. Only a
    trailing parenthesis is a place ("Piening GmbH (Saarbrücken)"); a leading
    one is part of the name ("(BAP) Personal GmbH").

    For private recruiters only. Employers are never folded: "Lebenshilfe
    (Kreis Viersen)" and "Lebenshilfe (Kreis Kleve)" are separate entities.
    """
    text = re.sub(r"\s*\([^)]*\)\s*$", " ", name or "")
    tokens = normalize_company_name(text).split()
    for i, token in enumerate(tokens):
        if i and token in _SITE_TOKENS and i < len(tokens) - 1:
            if len("".join(tokens[:i])) >= 4:
                tokens = tokens[:i]
            break
    return " ".join(tokens)


def _squash(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize_company_name(value))


def text_signals(text: str | None, firm_name: str) -> tuple[set[str], set[str]]:
    """What one ad text says about who placed it: (signals, matching domains)."""
    signals: set[str] = set()
    domains: set[str] = set()
    if not text:
        return signals, domains
    if _CLIENT_PHRASE.search(text):
        signals.add("client_phrase")
    tokens = normalize_company_name(firm_name).split()
    firm = tokens[0] if tokens else ""
    if _STAFFING_NAME.fullmatch(firm) and len(tokens) > 1:
        # "Personal Partner GmbH": the first word is generic and would claim
        # personalwerk.de. Use the first two.
        firm = firm + tokens[1]
    if len(firm) >= 3:
        for domain in {d.lower().rstrip(".") for d in _EMAIL_DOMAIN.findall(text)}:
            if domain in _FREEMAIL or "." not in domain:
                continue
            label = _squash(domain.rsplit(".", 2)[-2])
            if label.startswith(firm) or (len(firm) >= 4 and firm in label):
                domains.add(domain)
    if domains:
        signals.add("mail_domain")
    return signals, domains


@dataclasses.dataclass
class AgencyFacts:
    """Everything the corpus knows about one agency group, as counts."""

    group_key: str
    names: list[str]
    open_postings: int
    sole_trader: bool = False
    new_7d: int = 0
    new_28d: int = 0
    fields: dict[str, int] = dataclasses.field(default_factory=dict)
    recruiter_roles: int = 0
    recruiter_posting_ids: list[str] = dataclasses.field(default_factory=list)
    phrase_postings: int = 0
    mail_domains: set[str] = dataclasses.field(default_factory=set)
    employer_overlap: bool = False


def _reason(code: str, points: int | None = None, **evidence) -> dict:
    out: dict = {"code": code, "evidence": evidence}
    if points is not None:
        out["points"] = points
    return out


def classify(facts: AgencyFacts) -> tuple[str, list[dict]]:
    """`agency` / `client` / `unclear`, with every signal that fired."""
    agency: list[dict] = []
    staffing = [n for n in facts.names if _STAFFING_NAME.search(n)]
    if staffing:
        agency.append(_reason("name", name=staffing[0]))
    if facts.phrase_postings:
        agency.append(_reason("client_phrase", postings=facts.phrase_postings))
    if facts.mail_domains:
        agency.append(_reason("mail_domain", domains=sorted(facts.mail_domains)))
    if len(facts.fields) >= FIELD_SPREAD:
        agency.append(_reason("field_spread", fields=len(facts.fields)))

    client: list[dict] = []
    if facts.employer_overlap:
        client.append(_reason("also_employer"))
    public = [n for n in facts.names if _PUBLIC_BODY.search(n)]
    if public:
        client.append(_reason("public_body", name=public[0]))

    if agency and not client:
        return AGENCY, agency
    if client and not agency:
        return CLIENT, client
    return UNCLEAR, agency + client


def score(facts: AgencyFacts) -> tuple[int, list[dict]]:
    """How good a lead: small, active, growing. Points with their evidence."""
    why: list[dict] = []
    n = facts.open_postings
    size = 3 if 1 <= n <= 5 else 2 if 6 <= n <= 20 else 1 if 21 <= n <= CHAIN_OPEN_POSTINGS else 0
    if size:
        why.append(_reason("size", size, open_postings=n))
    if facts.sole_trader:
        why.append(_reason("sole_trader", 2))
    if facts.new_7d:
        why.append(_reason("new_7d", 2, postings=facts.new_7d))
    if facts.new_28d >= 3:
        why.append(_reason("new_28d", 1, postings=facts.new_28d))
    if facts.recruiter_roles:
        why.append(
            _reason(
                "hiring_recruiters",
                2,
                postings=facts.recruiter_roles,
                posting_ids=facts.recruiter_posting_ids[:5],
            )
        )
    return sum(r["points"] for r in why), why
