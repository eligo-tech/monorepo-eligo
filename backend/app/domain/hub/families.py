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

Every other ad is `other`: classified, not tech. `job_family_rules` records
which rules version labelled the ad; NULL or older is the nightly backfill's
queue (`backfill`), so a rule change reaches every open ad.
"""

from __future__ import annotations

import re

from sqlalchemy import bindparam, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.hub.models import JOB_FAMILY_RULES, UNCLASSIFIED, HubJobPosting

TECH = "tech"
OTHER = "other"

#: The Bundesagentur's IT occupational fields (`berufsfeld`).
TECH_FIELDS = frozenset({
    "Informatik",
    "IT-Netzwerktechnik, -Administration, -Organisation",
    "Softwareentwicklung und Programmierung",
    "IT-Systemanalyse, -Anwendungsberatung und -Vertrieb",
})

#: Ashby, Greenhouse and Lever boards belong to (mostly) tech companies: a
#: plain "Product Manager" there is a digital-product role.
TECH_BOARDS = frozenset({"ashby", "greenhouse", "lever"})
#: Bumped (in models.py) whenever the rules change: the backfill re-labels
#: every ad labelled under an older version (`job_family_rules`).
RULES_VERSION = JOB_FAMILY_RULES

_I = re.IGNORECASE

#: The ROLE is not tech, whatever domain it serves — checked first, always
#: wins. Role words only: a domain word ("Data Engineer Marketing", "SAP
#: Berater Einkauf") must never exclude.
_ROLE_NOT_TECH = re.compile(
    r"\b(?:sales|vertriebs?)[- ]?(?:manager|mitarbeiter\w*|leiter\w*|leitung|ingenieur\w*|engineer|representative|"
    r"rep|berater\w*|consultant|assistent\w*|innendienst|außendienst|director|lead|executive|specialist|spezialist\w*|"
    r"beauftragte\w*|team)\b|\bpre-?sales[- ](?:engineer|consultant|manager|specialist|spezialist\w*)|\binside sales\b|\bmitarbeiter\w* (?:im )?vertrieb\b|"
    r"account (?:executive|manager)|key account|\bverkäufer|\baußendienst|"
    r"business develop|geschäftsentwickl|"
    r"\brecruiter|\brecruiting[- ](?:manager|specialist|spezialist|partner|coordinator|koordinator|lead)|"
    r"personalberater|personalreferent|talent acquisition|human resources|\bhr[- ](?:business partner|manager|"
    r"generalist|referent|specialist)|personalentwickl|organisationsentwickl|"
    r"\beinkäufer|\bbuyer\b|einkaufs(?:leiter|referent|sachbearbeiter|manager)|strategische[rn]? einkauf|"
    r"procurement (?:manager|specialist|lead)|"
    r"buchhalter|accountant|\bjurist(?:in)?\b|\brechtsanwält|\brechtsanwalt(?:in)?\b|syndikus|legal counsel|\bit[- ]recht|"
    r"commercial manager|interne kommunikation|unternehmenskommunikation|auftragsmanagement|"
    r"\bmarketing[- ](?:manager|specialist|spezialist|lead|leiter\w*|leitung|assistent\w*|referent\w*|director|"
    r"coordinator|koordinator\w*)|online[- ]marketing|social media|"
    r"immobilienentwickl|projektentwickl|real estate|property develop|stadtentwickl|schulentwickl|"
    r"\bprodukt-?entwickler|product developer|recipe|rezept|kitchen developer|culinary|talent developer|"
    r"kaufmann|kauffrau|kaufleute|\bcontracting\b|"
    r"(?:steuerungs|\bnc|\bcnc|\bcam|\bsps|\bplc|roboter|maschinen)[- ]?programm|\bplc\b|\bcnc\b|"
    r"programmierer\w*\s*(?:\([^)]*\)\s*)?(?:cnc|cam|nc|sps)\b",
    _I,
)
#: The IT-commercial apprenticeship is filed under IT, despite "Kaufmann".
_IT_KAUFMANN = re.compile(r"kauf(?:mann|frau|leute)\w*\s+(?:\([^)]*\)\s*)?für\s+IT[- ]?System|IT[- ]?System(?:kauf|-kauf)", _I)

_QUALIFIER = (
    r"software|anwendungs|applikations|web|apps?|frontend|front-end|backend|back-end|full[- ]?stack|java|javascript|"
    r"typescript|python|php|ruby|rust|golang|go|kotlin|swift|scala|c\+\+|c#|\.net|dotnet|react|angular|vue|"
    r"node(?:\.js)?|ios|android|mobile|sap|abap|salesforce|datenbank|database|embedded|firmware|spiele|game|"
    r"ki|ai|ml|machine learning|cloud|devops|bi|daten|data|plattform|platform|unity|unreal|shopify|wordpress|"
    r"magento|odoo|dynamics|power ?bi|qlik|tableau|security|network|netzwerk|qa|test automation|solutions?|"
    r"forward[- ]deployed|prompt|analytics|api|computer vision|nlp|llm|site reliability|marketing automation|martech|pki"
)
_ROLE_NOUN = r"entwickler(?:in)?|developer|programmierer(?:in)?|programmer|engineer|ingenieur(?:in)?"
#: Tech whatever the domain words around it.
_STRONG = re.compile(
    r"(?:"
    # "<qualifier>[ <one word>] <role>" — the qualifier a whole word, so
    # "Logo Developer" and "Ski Engineer" are not "go" and "ki"
    rf"\b(?:{_QUALIFIER})(?:[- ][\w.+#]+)?[- ]?(?:{_ROLE_NOUN})"
    # software anywhere next to a builder role ("Entwickler Rechtsanwaltssoftware")
    r"|software\w*\b.*\b(?:entwickler|developer|engineer|programmier|architekt|architect|tester|ingenieur)"
    r"|\b(?:entwickler|developer|engineer|programmier|ingenieur)\w*\b.*software"
    # SAP before or after the role
    r"|\bsap\b[- ](?:[\w/]+[- ]){0,2}?(?:berater|consultant|entwickler|developer|basis|inhouse|administrator|"
    r"architekt|architect|modulbetreuer|spezialist|specialist|analyst|experte|expert)"
    r"|\b(?:berater|consultant|entwickler|developer|architekt|architect|spezialist|specialist|analyst|experte|expert)"
    r"(?:in)?\b(?:\s+\S+){0,2}?\s+sap\b"
    r"|fachinformatiker|\binformatiker|\binformatik\b|wirtschaftsinformati|medieninformati|bioinformati"
    r"|\bsre\b|\bdevops\b|\bdevsecops\b|\bmlops\b|\bkubernetes\b"
    r"|data scien|data analy|datenanaly|data architect|datenarchitekt|business intelligence"
    r"|machine learning|deep learning|künstliche intelligenz|computer vision"
    r"|\bki[- ](?:engineer|entwickler|experte|spezialist|manager|berater)"
    r"|\bai[- ](?:engineer|researcher|specialist|architect|developer|scientist)"
    r"|systemadministrat|system administrator|sysadmin|netzwerkadministrat|network administrator|"
    r"datenbankadministrat|database administrator|linux[- ]admin|windows[- ]admin|systemintegrat|"
    r"it-systemelektroniker|systemelektroniker für informations"
    r"|\b(?:cloud|solutions?|software|enterprise|daten|data|security|sicherheits|lösungs)[- ]?archite[ck]t"
    r"|cyber ?security|cybersicherheit|informationssicherheit|information security|security analyst|soc analyst"
    r"|penetration ?test|pentest|ethical hacker|\bciso\b"
    r"|softwaretest|software tester|testautomatisier|test automation|software qa|qa automation"
    r"|scrum master|agile coach|\bcto\b|chief technology|head of engineering|engineering manager|"
    r"vp,? engineering|tech lead|technical lead"
    r"|webmaster|webentwickl|\bfrontend|\bfront-end|\bbackend|\bback-end|full[- ]?stack"
    r"|\bcloud\b|datacenter|data center|rechenzentrum|embedded software|embedded systems?\b"
    # design and product roles that only exist for digital products
    r"|\bux\b|\bui\b|ui/ux|ux/ui|user experience|user interface|interaction design|ux[- ]writer|design system|"
    r"web ?design|product owner|digital product|technical product manager"
    r")",
    _I,
)
#: Product, design and research roles of ANY industry — tech only on a tech
#: board or with a digital qualifier ("Product Manager Platform"; not
#: "Product Manager Lebensmittel").
_PRODUCT = re.compile(
    r"product manager|product lead|head of product|\bvp,? product|chief product|produktmanager|"
    r"product designer|produktdesigner|research scientist|applied scientist",
    _I,
)
_DIGITAL = re.compile(
    r"\b(?:digital\w*|software|apps?|platform|plattform|saas|online|e-?commerce|data|daten|ai|ki|ml|web|mobile|"
    r"cloud|api|machine learning|growth)\b",
    _I,
)
#: A bare builder title: "Senior Developer (m/w/d)".
_BARE = re.compile(
    r"^(?:(?:senior|junior|lead|principal|staff|werkstudent\w*|praktikant\w*|trainee)[\s/]*)*"
    r"(?:developer|programmer|programmierer\w*|entwickler\w*)$",
    _I,
)
#: IT as a word must be capitals ("IT-Support"), not the English "it"; and
#: the employer's trade ("ein IT-Unternehmen") does not make a role IT.
_IT_WORD = re.compile(r"\bIT\b(?![- ]?(?:Unternehmen|Dienstleister|Branche|Firma|Haus|Konzern|Umfeld|Systemhaus))")


def _strip_tags(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\([^)]*\)|\b[mwdfx]/[mwdfx](?:/[mwdfx])?\b", " ", title)).strip(" -–|,")


def job_family(title: str | None, berufsfeld: str | None = None, *, source: str | None = None) -> str:
    """`tech` or `other` — never None: an ad passed through here is classified.

    In order: the IT-commercial apprenticeship is tech; a non-tech ROLE is
    other; the Bundesagentur's IT fields, a capital "IT", or a strong tech
    pattern are tech; a product/design/research role is tech on a tech board
    or with a digital qualifier; a bare "Developer" is tech."""
    text = title or ""
    if _IT_KAUFMANN.search(text):
        return TECH
    if _ROLE_NOT_TECH.search(text):
        return OTHER
    if berufsfeld in TECH_FIELDS or _IT_WORD.search(text) or _STRONG.search(text):
        return TECH
    if _PRODUCT.search(text) and (source in TECH_BOARDS or _DIGITAL.search(text) or _IT_WORD.search(text)):
        return TECH
    if _BARE.match(_strip_tags(text)):
        return TECH
    return OTHER


async def backfill(session: AsyncSession, *, limit: int) -> dict[str, int]:
    """(Re)label up to `limit` open ads — never labelled, or labelled under
    older rules; how many remain. Spread over nights like the vacancy key: one
    UPDATE of 700k rows would be a disk-IO burst on a database short of budget.
    The predicate is the queue index's own text, so the planner uses it."""
    queue = text(UNCLASSIFIED)
    rows = (await session.execute(
        select(HubJobPosting.id, HubJobPosting.title, HubJobPosting.berufsfeld, HubJobPosting.source)
        .where(queue)
        .order_by(HubJobPosting.id)
        .limit(limit)
    )).all()
    if rows:
        table = HubJobPosting.__table__
        connection = await session.connection()
        await connection.execute(
            update(table)
            .where(table.c.id == bindparam("b_id"))
            .values(job_family=bindparam("b_family"), job_family_rules=RULES_VERSION),
            [{"b_id": r.id, "b_family": job_family(r.title, r.berufsfeld, source=r.source)} for r in rows],
        )
    await session.commit()
    remaining = await session.scalar(select(func.count(HubJobPosting.id)).where(queue))
    return {"classified": len(rows), "remaining": int(remaining or 0)}
