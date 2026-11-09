"""Job family — is an ad a tech role? `hub_job_postings.job_family`.

Deterministic, no model (ARCHITECTURE.md RULE 5): a label a recruiter filters
on must give the same answer every time and be explainable by a rule.

**Tech** = software, data, ML/AI, IT operations and security, plus the
product and design roles of digital products (product manager/owner, UX/UI,
product designer) — decided 2026-11-09. Not tech: mechanical, electrical,
automation (PLC) and sales engineers, building architects, business
developers, HR "Personalentwickler", IT sales and IT recruiting.

An ad is tech when, and only when, no exclusion matches and either
  * the Bundesagentur filed it under one of its four IT fields
    (`TECH_FIELDS`, 25,331 open ads on 2026-11-09), or
  * its title names a tech role (`_TITLE`).

Every other ad is `other`: classified, not tech. NULL means "not classified
yet" and is the nightly backfill's queue (`backfill`).
"""

from __future__ import annotations

import re

from sqlalchemy import bindparam, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.hub.models import HubJobPosting

TECH = "tech"
OTHER = "other"

#: The Bundesagentur's IT occupational fields (`berufsfeld`).
TECH_FIELDS = frozenset({
    "Informatik",
    "IT-Netzwerktechnik, -Administration, -Organisation",
    "Softwareentwicklung und Programmierung",
    "IT-Systemanalyse, -Anwendungsberatung und -Vertrieb",
})

# German compounds glue the qualifier on ("Softwareentwickler",
# "Java-Entwickler"), so qualifiers match as prefixes, not whole words.
_DEV_QUALIFIER = (
    r"software|anwendungs|applikations|web|app|frontend|front-end|backend|back-end|full[- ]?stack|"
    r"java|python|\.net|c\+\+|c#|php|javascript|typescript|react|angular|node|golang|go|rust|ruby|"
    r"kotlin|swift|ios|android|mobile|sap|abap|salesforce|datenbank|database|embedded|firmware|"
    r"spiele|game|ki|ai|ml|cloud|devops|it|bi|daten|data|plattform|platform|systementwickl|"
    r"programm|unity|unreal|shopify|wordpress|magento|odoo|dynamics|power ?bi|qlik|tableau"
)
_TITLE = re.compile(
    r"(?:"
    # developers and programmers
    rf"(?:{_DEV_QUALIFIER})[- ]?(?:entwickler|developer|programmierer|engineer)"
    r"|\bdeveloper\b|\bentwickler(?:in)?\s*(?:\(|für|for|-)?\s*(?:software|web|app|frontend|backend|java|python|sap)"
    r"|programmierer|\bprogrammer\b|softwareentwicklung|software development|softwarearchitekt|software architect"
    # engineers with a tech qualifier only
    r"|(?:software|data|daten|machine learning|ml|ai|ki|devops|site reliability|platform|plattform|cloud|"
    r"backend|frontend|full[- ]?stack|mobile|ios|android|security|network|netzwerk|qa|"
    r"test automation|solutions?|forward[- ]deployed|prompt|analytics|systems? software|"
    r"embedded software|firmware|api|automation test|computer vision|nlp|llm)\s*engineer"
    r"|\bsre\b|\bdevops\b|\bdevsecops\b|\bmlops\b|\bkubernetes\b"
    # data and ML/AI
    r"|data scien|data analy|datenanaly|data architect|datenarchitekt|business intelligence|\bbi[- ](?:analyst|developer|berater|consultant|entwickler)"
    r"|machine learning|deep learning|künstliche intelligenz|\bki[- ](?:engineer|entwickler|experte|spezialist|manager|berater)"
    r"|\bai[- ](?:engineer|researcher|specialist|architect|developer|scientist)|research scientist|applied scientist"
    # IT operations, consulting, architecture, security
    r"|\bIT[- ](?:administrator|admin|support|supporter|consultant|berater|projektleiter|projektmanager|project manager|"
    r"spezialist|specialist|architekt|architect|manager|leiter|security|sicherheit|systemadministrator|system|"
    r"service|servicetechniker|techniker|koordinator|mitarbeiter|fachkraft|operations|infrastruktur|infrastructure|"
    r"analyst|auditor|trainee|werkstudent|praktikant|helpdesk|engineer|lead|head|director|business|product)"
    r"|fachinformatiker|informatiker|\binformatik\b|wirtschaftsinformati|medieninformati|bioinformati"
    r"|systemadministrat|system administrator|sysadmin|netzwerkadministrat|network administrator|datenbankadministrat|database administrator"
    r"|linux[- ]admin|windows[- ]admin|systemintegrator|it-systemelektroniker|systemelektroniker für informations"
    r"|(?:cloud|solutions?|software|enterprise|it|daten|data|security|sicherheits|system|lösungs)[- ]?archite[ck]t"
    r"|cyber ?security|cybersicherheit|informationssicherheit|information security|security analyst|soc analyst|"
    r"penetration tester|pentester|\bciso\b"
    r"|softwaretester|software tester|testautomatisier|test automation|software qa|qa automation"
    r"|sap[- ](?:berater|consultant|entwickler|developer|basis|inhouse|administrator|architekt|architect|modulbetreuer|spezialist|specialist|analyst)"
    r"|scrum master|agile coach|\bcto\b|chief technology|head of engineering|engineering manager|vp engineering|tech lead|technical lead"
    r"|webmaster|webentwickl|web developer|frontend|front-end|backend|back-end|full[- ]?stack"
    r"|\bcloud\b|datacenter|data center|rechenzentrum|embedded software|embedded systems?\b"
    # product and design of digital products
    r"|product manager|product owner|product lead|head of product|\bvp,? product|chief product|technical product|"
    r"produktmanager(?:in)?\s*(?:\(|-)?\s*(?:digital|software|it|online|app|e-commerce|saas|plattform|platform)"
    r"|digital product|\bux\b|\bui\b|\bui/ux\b|\bux/ui\b|user experience|user interface|interaction design|"
    r"product design|produktdesigner(?:in)?\s*(?:\(|-)?\s*(?:digital|ux|ui)|web ?design|ux[- ]writer|design system"
    r")",
    re.IGNORECASE,
)
#: IT as a word must be capitals ("IT-Support"), not the English "it"; and
#: the employer's trade ("ein IT-Unternehmen") does not make a role IT.
_IT_WORD = re.compile(r"\bIT\b(?![- ]?(?:Unternehmen|Dienstleister|Branche|Firma|Haus|Konzern|Umfeld|Systemhaus))")
#: Roles that share a tech word but are not tech roles. Role words only —
#: a domain word ("Softwareentwickler Maschinenbau") must not exclude.
_EXCLUDE = re.compile(
    r"business develop|geschäftsentwickl|personalentwickl|organisationsentwickl|immobilienentwickl|"
    r"projektentwickl|real estate|property develop|stadtentwickl|schulentwickl|product developer|"
    r"\bsales\b|vertrieb|verkäufer|account (?:executive|manager)|key account|recruit|personalberat|"
    r"human resources|talent acquisition|kaufmann|kauffrau|kaufleute|"
    r"jurist|rechtsanwält|rechtsanwalt|syndikus|legal counsel|\bit[- ]recht|buchhalter|accountant|einkäufer|"
    r"\beinkauf\b|procurement|commercial manager|interne kommunikation|unternehmenskommunikation|marketing|"
    r"sps[- ]?programmier|\bplc\b|\bcnc\b|roboter[- ]?programmier|\bcontracting\b",
    re.IGNORECASE,
)


def job_family(title: str | None, berufsfeld: str | None = None) -> str:
    """`tech` or `other` — never None: an ad passed through here is classified."""
    text = title or ""
    if _EXCLUDE.search(text):
        return OTHER
    if berufsfeld in TECH_FIELDS or _IT_WORD.search(text):
        # "IT" in capitals as a word names the domain in German titles
        # ("Projektmanager Digitalisierung & IT"); the case-insensitive
        # patterns below never decide on "it" alone.
        return TECH
    match = _TITLE.search(text)
    if match is None or match.group(0)[:2].lower() == "it":
        return OTHER
    return TECH


async def backfill(session: AsyncSession, *, limit: int) -> dict[str, int]:
    """Classify up to `limit` open ads that have no family yet; how many remain.
    Spread over nights like the vacancy key: one UPDATE of 700k rows would be a
    disk-IO burst on a database short of budget."""
    rows = (await session.execute(
        select(HubJobPosting.id, HubJobPosting.title, HubJobPosting.berufsfeld)
        .where(HubJobPosting.is_active, HubJobPosting.job_family.is_(None))
        .order_by(HubJobPosting.id)
        .limit(limit)
    )).all()
    if rows:
        table = HubJobPosting.__table__
        connection = await session.connection()
        await connection.execute(
            update(table)
            .where(table.c.id == bindparam("b_id"), table.c.job_family.is_(None))
            .values(job_family=bindparam("b_family")),
            [{"b_id": r.id, "b_family": job_family(r.title, r.berufsfeld)} for r in rows],
        )
    await session.commit()
    remaining = await session.scalar(
        select(func.count(HubJobPosting.id)).where(HubJobPosting.is_active, HubJobPosting.job_family.is_(None))
    )
    return {"classified": len(rows), "remaining": int(remaining or 0)}
