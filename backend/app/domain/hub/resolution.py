"""Entity resolution — deterministic company identity.

The same rule the matcher lives by (§2.2: hard criteria are decided in plain
code, never by a model) applied to identity: a company is the *same* company
only when a deterministic key says so. The ladder, strongest rung first:

    1. ``vat``        — EU VAT identification number
    2. ``register``   — register court + Handelsregister number
    3. ``domain``     — normalized website domain (registrable part)
    4. ``name_place`` — normalized legal name + postal code / city

Rungs 1–2 are authoritative identifiers. Rung 3 is strong but not proof (two
brands can share a domain). Rung 4 is the weakest and is what most job-board
records land on, which is exactly why ``HubCompany.resolution_basis`` is stored:
a row identified only by name+place is visibly weaker than one identified by VAT.

Anything *below* this ladder — fuzzy string similarity, an LLM's opinion that
two names look alike — is deliberately not here. Such matches belong in a human
review queue, never in an automatic merge.
"""

from __future__ import annotations

import re
import unicodedata

# German legal-form tokens, plus the common international ones. Stripped from
# the blocking key so "Muster GmbH & Co. KG" and "Muster KG" collapse together.
_LEGAL_FORM_TOKENS = {
    "gmbh", "mbh", "ggmbh", "ug", "haftungsbeschraenkt", "ag", "kgaa", "kg",
    "ohg", "gbr", "gmbhcokg", "se", "ev", "ek", "eg", "kdoer", "partg", "mbb",
    "co", "und", "ltd", "limited", "inc", "llc", "plc", "sa", "sarl", "srl",
    "spa", "bv", "nv", "aps", "ab", "oy", "as", "gesellschaft", "mit",
    "beschraenkter", "haftung",
}

# Longest-first so ".co.uk" wins over ".uk" when trimming to the registrable part.
_MULTIPART_SUFFIXES = (
    "co.uk", "org.uk", "ac.uk", "gov.uk", "co.at", "or.at", "ac.at",
    "com.au", "net.au", "org.au", "co.nz", "co.jp", "com.br", "co.za",
)

_UMLAUT_MAP = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"}
)

# EU member-state VAT prefixes (EL = Greece, XI = Northern Ireland post-Brexit).
# Checking the prefix against a real list stops arbitrary two-letter strings
# ("NOPE") being accepted as VAT ids on shape alone.
_VAT_PREFIXES = frozenset(
    """AT BE BG CY CZ DE DK EE EL ES FI FR HR HU IE IT LT LU LV MT NL PL PT
    RO SE SI SK XI""".split()
)
_VAT_RE = re.compile(r"^([A-Z]{2})([A-Z0-9]{2,13})$")
_REGISTER_NUMBER_RE = re.compile(r"^HR[AB]\s*\d+(\s*[A-Z]{1,3})?$", re.IGNORECASE)


def fold_umlauts(value: str) -> str:
    """German-aware folding: ``ä→ae``, ``ß→ss``.

    Plain Unicode NFKD would turn "Müller" into "Muller", which does not match
    the "Mueller" spelling the same company uses elsewhere. Fold first, then
    strip any remaining accents.
    """
    folded = value.translate(_UMLAUT_MAP)
    decomposed = unicodedata.normalize("NFKD", folded)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_company_name(raw: str | None) -> str:
    """Blocking key for a company name: casefolded, folded, legal form stripped.

    Returns "" for input that normalizes away entirely, which callers must treat
    as *unresolvable* rather than as a match — otherwise every nameless record
    would collapse into one company.
    """
    if not raw:
        return ""
    text = fold_umlauts(raw).lower()
    # Keep alphanumerics and spaces; "&", ".", "-" become separators.
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [t for t in text.split() if t and t not in _LEGAL_FORM_TOKENS]
    return " ".join(tokens)


def extract_legal_form(raw: str | None) -> str | None:
    """Return the trailing legal form as written, if recognizable ("GmbH & Co. KG")."""
    if not raw:
        return None
    match = re.search(
        r"\b(gGmbH|GmbH(?:\s*&\s*Co\.?\s*KGaA|\s*&\s*Co\.?\s*KG)?|AG|SE|KGaA|KG|OHG|"
        r"GbR|UG(?:\s*\(haftungsbeschränkt\))?|e\.?\s?V\.?|e\.?\s?K\.?|eG|KdöR)\s*$",
        raw.strip(),
        re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else None


def normalize_domain(raw: str | None) -> str | None:
    """Reduce a URL or host to its registrable domain, lowercased.

    ``https://www.Example.co.uk/karriere?x=1`` → ``example.co.uk``. Deliberately
    a small suffix table rather than a public-suffix-list dependency: the DACH
    market this ingests is overwhelmingly ``.de``/``.at``/``.ch``/``.com``, and a
    wrong split only ever costs a missed merge, never a false one.
    """
    if not raw:
        return None
    host = raw.strip().lower()
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", host)   # scheme
    host = host.split("/")[0].split("?")[0].split("#")[0]
    host = host.split("@")[-1].split(":")[0]            # userinfo, port
    host = host.removeprefix("www.").strip(".")
    if not host or "." not in host:
        return None
    if not re.fullmatch(r"[a-z0-9.-]+", host):
        return None

    for suffix in _MULTIPART_SUFFIXES:
        if host.endswith("." + suffix):
            labels = host[: -len(suffix) - 1].split(".")
            return f"{labels[-1]}.{suffix}"
    parts = host.split(".")
    return ".".join(parts[-2:])


def normalize_vat_id(raw: str | None) -> str | None:
    """Uppercase, strip separators, and syntax-check an EU VAT id.

    Syntax only — this says the string *could* be a VAT id, never that it is a
    real one. Confirming it against VIES is a verification postcondition, and
    ``HubCompany.vat_verified_at`` stays null until that check has run.
    """
    if not raw:
        return None
    value = re.sub(r"[\s.\-/]", "", raw).upper()
    match = _VAT_RE.fullmatch(value)
    if match is None or match.group(1) not in _VAT_PREFIXES:
        return None
    # A national number is always at least partly numeric; an all-alpha tail is
    # a word that happens to start with a country code, not an identifier.
    return value if any(ch.isdigit() for ch in match.group(2)) else None


def normalize_register_number(raw: str | None) -> str | None:
    """Canonicalize a Handelsregister number: ``hrb 12345`` → ``HRB 12345``."""
    if not raw:
        return None
    value = re.sub(r"\s+", " ", raw.strip()).upper()
    if not _REGISTER_NUMBER_RE.fullmatch(value):
        return None
    return re.sub(r"^(HR[AB])\s*", r"\1 ", value)


def identity_key(
    *,
    name: str | None = None,
    vat_id: str | None = None,
    register_court: str | None = None,
    register_number: str | None = None,
    website_domain: str | None = None,
    postal_code: str | None = None,
    city: str | None = None,
) -> tuple[str, str] | None:
    """Resolve the strongest available identity as ``(basis, key)``.

    Returns ``None`` when no rung applies — the caller must then route the record
    to review rather than inventing a company. A record with a name but no place
    is unresolvable on purpose: "Müller GmbH" alone is not an identity in a
    country with thousands of them.
    """
    vat = normalize_vat_id(vat_id)
    if vat:
        return "vat", f"vat:{vat}"

    register = normalize_register_number(register_number)
    if register and register_court:
        court = normalize_company_name(register_court) or register_court.lower()
        return "register", f"register:{court}:{register}"

    domain = normalize_domain(website_domain)
    if domain:
        return "domain", f"domain:{domain}"

    normalized = normalize_company_name(name)
    place = (postal_code or "").strip() or normalize_company_name(city)
    if normalized and place:
        return "name_place", f"name_place:{normalized}:{place.lower()}"

    return None
