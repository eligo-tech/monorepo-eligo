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
from app.domain.hub.resolution import fold_umlauts, normalize_company_name

#: Candidates kept per agency, and example ads per candidate.
MAX_CANDIDATES = 3
MAX_EXAMPLES = 3

_EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
_URL = re.compile(r"(?:https?://|\bwww\.)([\w-]+(?:\.[\w-]+)+)", re.IGNORECASE)
#: A whole link, so an address in its query string is not read as a second
#: domain ("…/apply?mail=a@other.de").
_WHOLE_URL = re.compile(r"(?:https?://|\bwww\.)\S+", re.IGNORECASE)

#: Top-level domains an ad in this corpus links to. A trailing label that is
#: not one is the next sentence glued on — "info@firma.de.Wir freuen uns" must
#: give firma.de, not "de.wir". Closed on purpose: an unknown TLD drops a
#: candidate, which is cheaper than showing an invented one.
_TLDS = {
    "de", "com", "net", "org", "eu", "info", "biz", "at", "ch", "li", "lu", "nl",
    "be", "fr", "it", "es", "pt", "pl", "cz", "sk", "hu", "dk", "se", "no", "fi",
    "uk", "ie", "us", "io", "co", "ai", "me", "tv", "cc", "jobs", "online",
    "digital", "team", "work", "works", "careers", "career", "agency", "expert",
    "experts", "consulting", "solutions", "services", "group", "gmbh", "berlin",
    "hamburg", "koeln", "cologne", "bayern", "nrw", "ruhr", "saarland", "global",
    "network", "partners", "health", "care", "tech", "app", "dev", "world",
}

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
    # ELI-30: boards measured in 1,000 employers' ads (2026-11-11).
    "azubi.de", "gute-jobs.de", "ausbildung.de", "studyflix.de", "jobs4us.de",
    "awo-jobs.de", "genau-mein-job.de", "kalaydo.de", "jobblitz.de",
    "jobs-oberlausitz.de", "karriere-suedwestfalen.de", "ams.at", "hokify.at",
}

#: Regional ad papers' boards: hamburger-jobanzeiger.de, aachener-jobanzeiger.de …
_BOARD_LABEL = re.compile(r"jobanzeiger$")

#: Words too generic to tie a domain to a firm ("Personal Partner GmbH" must
#: not claim personalwerk.de, "Berlin Pflege Plus" must not claim
#: charite-berlin.de): structure words, sectors, and the places a firm sits in.
_GENERIC = re.compile(
    r"^(?:gruppe|group|service|services|partner|partners|management|solutions|"
    r"deutschland|germany|holding|international|europe|europa|plus|more|team|"
    r"work|staff|pflege|care|medical|medizin|health|gesundheit|technik|tech|"
    r"engineering|industrie|industry|logistik|office|consult|digital|"
    r"berlin|hamburg|muenchen|koeln|frankfurt|stuttgart|duesseldorf|dortmund|"
    r"essen|leipzig|bremen|dresden|hannover|nuernberg|duisburg|bochum|wuppertal|"
    r"bielefeld|bonn|muenster|mannheim|karlsruhe|augsburg|wiesbaden|kiel|"
    r"sachsen|bayern|hessen|thueringen|brandenburg|niedersachsen|westfalen|"
    r"rhein|ruhr|nord|sued|west|ost|mitte|rheinland|pfalz|baden|wuerttemberg)$"
)


def registrable_domain(host: str | None) -> str | None:
    """`bewerbung.dis-ag.com` → `dis-ag.com`; `jobs.x.co.uk` → `x.co.uk`."""
    if not host:
        return None
    labels = [p for p in host.lower().strip(".").split(".") if p]
    if labels and labels[0] == "www":
        labels = labels[1:]
    while labels and labels[-1] not in _TLDS:  # a glued-on next sentence
        labels = labels[:-1]
    if len(labels) < 2:
        return None
    take = 3 if ".".join(labels[-2:]) in _MULTI_SUFFIX and len(labels) >= 3 else 2
    return ".".join(labels[-take:])


def extract_domains(text: str | None) -> set[str]:
    """Every registrable domain an ad text names in an address or a link."""
    if not text:
        return set()
    hosts = _URL.findall(text) + _EMAIL.findall(_WHOLE_URL.sub(" ", text))
    return {d for h in hosts if (d := registrable_domain(h))}


def _usable(domain: str) -> bool:
    return (
        domain not in _FREEMAIL
        and domain not in _NOT_A_FIRM
        and not domain.endswith(".jobs")  # a TLD for job boards
        and not _BOARD_LABEL.search(domain.split(".")[0])
    )


def _squash(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", fold_umlauts(value).lower())


_ARTICLE = re.compile(r"^(?:die|der|das|the)\s+")


def _name_key(name: str) -> str:
    """A company name as a domain label would spell it: "die autobahn" → "autobahn"."""
    return _squash(_ARTICLE.sub("", name))


def employer_keys(names) -> set[str]:
    """How employers' names could appear as a domain label: the whole name
    without article, and its first word — "die autobahn des bundes" gives
    "autobahndesbundes" and "autobahn". Computed once per rebuild."""
    keys: set[str] = set()
    for name in names:
        bare = _ARTICLE.sub("", name)
        keys.add(_squash(bare))
        first = bare.split()[0] if bare.split() else ""
        if len(first) >= 4 and not _GENERIC.match(first):
            keys.add(_squash(first))
    return {k for k in keys if len(k) >= 4}


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
    own_names: set[str] | None = None,
) -> list[dict]:
    """The agency's likely website, best first, each with its evidence.

    `ads` are (posting id, ad text). Ranked by: the domain carries a
    distinctive word of the firm's name, then how many ads use it. A domain
    whose name is a known EMPLOYER's is flagged `likely_client`.
    """
    seen: dict[str, dict] = {}
    for posting_id, text in ads:
        collect(seen, posting_id, text)
    return rank(
        seen,
        firm_names=firm_names,
        client_keys=employer_keys(employer_names or set()),
        own_names=own_names,
    )


def collect(seen: dict[str, dict], posting_id: str, text: str | None) -> None:
    """Add one ad's usable domains to `seen` (domain → count + first example
    ids). Streaming and bounded, so a chain with thousands of ads costs a
    counter, not a list."""
    for domain in extract_domains(text):
        if _usable(domain):
            entry = seen.setdefault(domain, {"ads": 0, "ids": []})
            entry["ads"] += 1
            if len(entry["ids"]) < MAX_EXAMPLES:
                entry["ids"].append(str(posting_id))


def _whole_names(names: list[str]) -> set[str]:
    """The firm's name as a label would spell it in full — first word, first
    two words — legal form included: "DIS AG Germany" → "dis", "disag"."""
    out: set[str] = set()
    for name in names:
        words = [_squash(w) for w in name.split() if _squash(w)]
        if words and not _GENERIC.match(words[0]):  # "Berlin Personal" ≠ berlin.de
            out.add(words[0])
            if len(words) >= 2:
                out.add(words[0] + words[1])
    return {w for w in out if len(w) >= 3}


def _matches(label: str, tokens: set[str], whole: set[str] = frozenset()) -> bool:
    """A label that spells the firm's name exactly ("dis-ag", "bbrecruiting"),
    a firm word at the START of the label or of a hyphen part
    ("woltersdorf-pb"), or a long word anywhere in it."""
    if _squash(label) in whole:
        return True
    parts = [_squash(p) for p in label.split("-")] + [_squash(label)]
    return any(
        any(part.startswith(t) for part in parts) or (len(t) >= 7 and t in _squash(label))
        for t in tokens
    )


def rank(
    seen: dict[str, dict],
    *,
    firm_names: list[str],
    client_keys: set[str] | None = None,
    own_names: set[str] | None = None,
) -> list[dict]:
    """Rank collected domains — see `domain_candidates`.

    `client_keys` come from `employer_keys()`; `own_names` are the agency's
    normalized names. A domain spelled like an employer is flagged
    `likely_client` — unless that employer is the agency itself.
    """
    tokens = _firm_tokens(firm_names)
    whole = _whole_names(firm_names)
    own = employer_keys(own_names or set()) | {_name_key(n) for n in (own_names or set())}
    employers = (client_keys or set()) - own
    ranked = []
    for domain, entry in seen.items():
        label = domain.split(".")[0]
        ranked.append(
            {
                "domain": domain,
                "ads": entry["ads"],
                "name_match": _matches(label, tokens, whole),
                "likely_client": _squash(label) in employers,
                "posting_ids": entry["ids"],
            }
        )
    ranked.sort(key=lambda c: (not c["name_match"], -c["ads"], c["domain"]))
    return ranked[:MAX_CANDIDATES]


# Shared with the Impressum adapter.
squash = _squash
whole_names = _whole_names
