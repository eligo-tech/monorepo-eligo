"""An agency's website, as its own ads suggest it — candidates, never facts.

Measured on 200 live private-recruiter ads (T0, 2026-11-02): 76% carry a
domain, and about two thirds of those are the agency's own. The rest are job
boards and ATS vendors (finest-jobs.com, hogapage.de, coveto.de,
bewerbung.jobs, recruiting-agents.com) or the CLIENT's site (autobahn.de).

So this module only RANKS candidates, each with its evidence. Nothing here is
written to `hub_companies.website_domain`: a candidate becomes the website
only when the Impressum fetched from it names the firm as its operator (PR7).
Even "the page mentions the firm" is not enough — hogapage.de's job page names
the agency it advertises for.

Pure functions, no I/O: `agencies.refresh_profiles` feeds it ad texts.
"""

from __future__ import annotations

import re

from app.domain.hub.agency_rank import STAFFING_NAME as _STAFFING_NAME
from app.domain.hub.resolution import normalize_company_name

#: Candidates kept per agency, and example ads per candidate.
MAX_CANDIDATES = 3
MAX_EXAMPLES = 3

_EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
_URL = re.compile(r"(?:https?://|\bwww\.)([\w-]+(?:\.[\w-]+)+)", re.IGNORECASE)

#: Two-label public suffixes this corpus actually meets.
_MULTI_SUFFIX = {
    "co.uk", "org.uk", "ac.uk", "com.au", "co.at", "or.at", "gv.at", "ac.at",
    "com.tr", "co.nz", "com.pl", "com.br", "co.za",
}

_FREEMAIL = {
    "gmail.com", "googlemail.com", "web.de", "gmx.de", "gmx.net", "gmx.at",
    "gmx.ch", "t-online.de", "outlook.com", "outlook.de", "hotmail.com",
    "hotmail.de", "live.de", "live.com", "yahoo.de", "yahoo.com", "icloud.com",
    "me.com", "aol.com", "freenet.de", "mail.de", "posteo.de", "mailbox.org",
    "arcor.de", "online.de", "email.de", "protonmail.com", "proton.me",
}

#: Job boards, ATS vendors, aggregators and platforms — they carry an
#: agency's ad, they are not its website. Seeded from what T0 actually hit.
_NOT_A_FIRM = {
    "finest-jobs.com", "hogapage.de", "coveto.de", "recruiting-agents.com",
    "arbeitsagentur.de", "stepstone.de", "stepstone.com", "indeed.com", "indeed.de",
    "monster.de", "jobware.de", "stellenanzeigen.de", "meinestadt.de", "kimeta.de",
    "jobexport.de", "persy.jobs", "get-in-it.de", "heyjobs.co", "heyjobs.de",
    "jobteaser.com", "gehalt.de", "kununu.com", "glassdoor.de", "glassdoor.com",
    "xing.com", "linkedin.com", "facebook.com", "instagram.com", "youtube.com",
    "google.com", "goo.gl", "bit.ly", "workwise.io", "join.com", "softgarden.io",
    "softgarden.de", "personio.de", "personio.com", "rexx-systems.com",
    "onlyfy.jobs", "smartrecruiters.com", "greenhouse.io", "lever.co",
    "recruitee.com", "dvinci-easy.com", "dvinci.de", "concludis.de", "prescreen.io",
    "jobbase.io", "talention.de", "umantis.com", "successfactors.com",
    "successfactors.eu", "workday.com", "myworkdayjobs.com", "jobs.de",
    "interamt.de", "bund.de", "medi-jobs.de", "pflegejobs.de", "jobvector.de",
    "absolventa.de", "stellenwerk.de", "yourfirm.de", "staufenbiel.de",
}

#: Words too generic to tie a domain to a firm ("Personal Partner GmbH" must
#: not claim personalwerk.de).
_GENERIC = re.compile(r"^(?:gruppe|group|service|services|partner|management|solutions|deutschland|germany|holding|international)$")


def registrable_domain(host: str | None) -> str | None:
    """`bewerbung.dis-ag.com` → `dis-ag.com`; `jobs.x.co.uk` → `x.co.uk`."""
    if not host:
        return None
    labels = [p for p in host.lower().strip(".").split(".") if p]
    if labels and labels[0] == "www":
        labels = labels[1:]
    if len(labels) < 2 or not labels[-1].isalpha() or len(labels[-1]) < 2:
        return None
    take = 3 if ".".join(labels[-2:]) in _MULTI_SUFFIX and len(labels) >= 3 else 2
    return ".".join(labels[-take:])


def extract_domains(text: str | None) -> set[str]:
    """Every registrable domain an ad text names in an address or a link."""
    if not text:
        return set()
    hosts = _EMAIL.findall(text) + _URL.findall(text)
    return {d for h in hosts if (d := registrable_domain(h))}


def _usable(domain: str) -> bool:
    return (
        domain not in _FREEMAIL
        and domain not in _NOT_A_FIRM
        and not domain.endswith(".jobs")  # a TLD for job boards
    )


def _squash(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value)


def _firm_tokens(names: list[str]) -> set[str]:
    """Distinctive words of the firm's name, ≥4 letters, generic ones dropped —
    plus the first two words joined ("tw con" → "twcon")."""
    out: set[str] = set()
    for name in names:
        tokens = normalize_company_name(name).split()
        for t in tokens:
            if len(t) >= 4 and not _STAFFING_NAME.search(t) and not _GENERIC.match(t):
                out.add(_squash(t))
        if len(tokens) >= 2:
            joined = _squash("".join(tokens[:2]))
            if len(joined) >= 4:
                out.add(joined)
    return out


def domain_candidates(
    ads: list[tuple[str, str | None]],
    *,
    firm_names: list[str],
    employer_names: set[str] | None = None,
) -> list[dict]:
    """The agency's likely website, best first, each with its evidence.

    `ads` are (posting id, ad text). Ranked by: the domain carries a
    distinctive word of the firm's name, then how many ads use it. A domain
    whose name is a known EMPLOYER's is flagged `likely_client`.
    """
    seen: dict[str, list[str]] = {}
    for posting_id, text in ads:
        collect(seen, posting_id, text)
    return rank(seen, firm_names=firm_names, employer_names=employer_names)


def collect(seen: dict[str, list[str]], posting_id: str, text: str | None) -> None:
    """Add one ad's usable domains to `seen` (domain → posting ids). Streaming
    form, so a rebuild never holds every ad text at once."""
    for domain in extract_domains(text):
        if _usable(domain):
            ids = seen.setdefault(domain, [])
            if posting_id not in ids:
                ids.append(posting_id)


def rank(
    seen: dict[str, list[str]],
    *,
    firm_names: list[str],
    employer_names: set[str] | None = None,
) -> list[dict]:
    """Rank collected domains — see `domain_candidates`."""
    tokens = _firm_tokens(firm_names)
    employers = employer_names or set()
    ranked = []
    for domain, ids in seen.items():
        label = domain.split(".")[0]
        squashed = _squash(label)
        ranked.append(
            {
                "domain": domain,
                "ads": len(ids),
                "name_match": any(t in squashed for t in tokens),
                "likely_client": label in employers
                or label.replace("-", " ") in employers
                or squashed in employers,
                "posting_ids": [str(i) for i in ids[:MAX_EXAMPLES]],
            }
        )
    ranked.sort(key=lambda c: (not c["name_match"], -c["ads"], c["domain"]))
    return ranked[:MAX_CANDIDATES]
