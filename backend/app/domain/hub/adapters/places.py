"""Reading a free-text job location ("Munich, Bavaria, Germany") as a DACH place.

Greenhouse and Lever give locations as text a recruiter typed, not as an
address. A wrong country silently merges two companies (identity is name +
town), so a miss is preferred to a guess. A part ("Berlin, Germany" in
"London; Berlin, Germany") is split into segments at commas and " - ":

  0. a part naming a place outside DACH anywhere — a US state ("Vienna, VA",
     "Geneva, IL"), "US", "Canada", another country — is not a DACH place;
  1. a part naming a DACH country or one of its regions is in that country,
     and its first other segment is the town. A bare code ("DE", "AT") counts
     only next to a known city of that country ("Berlin, DE"; not
     "Wilmington, DE"); a town that is a known city of ANOTHER DACH country
     is refused ("Basel, Germany");
  2. otherwise a known DACH city places the part, when every other segment
     is an address line (has a digit), a work-mode note ("Remote") or the
     same country's city ("Salzburg, Salzburg");
  3. anything else is not a DACH place.

A postcode is taken only at the start of a segment ("10245 Berlin") and only
with the country's length (5 digits DE, 4 AT/CH) — "Program 2025" is no
postcode.
"""

from __future__ import annotations

import re
from typing import Any

DE, AT, CH = "DEUTSCHLAND", "OESTERREICH", "SCHWEIZ"

_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "é": "e", "è": "e"})

#: A segment that names the country (or a region only that country has).
_COUNTRY_WORDS = {
    DE: {
        "germany", "deutschland", "de", "deu", "bavaria", "bayern", "baden-wuerttemberg",
        "baden wuerttemberg", "hesse", "hessen", "north rhine-westphalia", "nordrhein-westfalen", "nrw",
        "lower saxony", "niedersachsen", "saxony", "sachsen", "saxony-anhalt", "sachsen-anhalt",
        "thuringia", "thueringen", "rhineland-palatinate", "rheinland-pfalz", "saarland",
        "schleswig-holstein", "mecklenburg-vorpommern", "brandenburg", "berlin-brandenburg",
    },
    AT: {
        "austria", "oesterreich", "at", "aut", "styria", "steiermark", "tyrol",
        "tirol", "upper austria", "oberoesterreich", "lower austria", "niederoesterreich",
        "carinthia", "kaernten", "vorarlberg", "burgenland",
    },
    CH: {
        "switzerland", "schweiz", "suisse", "svizzera", "ch", "che",
        "vaud", "ticino", "canton of zurich", "canton of zug",
    },
}

#: Cities read on their own ("Berlin"), and the first segment in a DACH part.
_CITIES = {
    DE: {
        "berlin", "munich", "muenchen", "hamburg", "frankfurt", "frankfurt am main", "cologne", "koeln",
        "duesseldorf", "dusseldorf", "stuttgart", "leipzig", "dresden", "hannover", "hanover",
        "nuremberg", "nuernberg", "bremen", "essen", "dortmund", "karlsruhe", "mannheim", "heidelberg",
        "bonn", "potsdam", "freiburg", "aachen", "muenster", "augsburg", "wiesbaden", "mainz",
        "darmstadt", "regensburg", "ulm", "kiel", "rostock", "jena", "erlangen", "ingolstadt",
        "wolfsburg", "braunschweig",
    },
    AT: {"vienna", "wien", "graz", "linz", "salzburg", "innsbruck", "klagenfurt"},
    CH: {
        "zurich", "zuerich", "geneva", "geneve", "basel", "bern", "berne", "lausanne", "zug",
        "lucerne", "luzern", "winterthur", "st. gallen", "st gallen", "lugano",
    },
}
_CITY_COUNTRY = {city: country for country, cities in _CITIES.items() for city in cities}
#: Bare codes: a country only next to a known city of that country.
_CODES = {"de", "deu", "at", "aut", "ch", "che"}
_NOT_A_TOWN = re.compile(r"\b(remote|home ?office|hybrid|anywhere|europe|emea|dach|worldwide|onsite|on-site)\b", re.I)
_PART_SPLIT = re.compile(r"\s*(?:;|\||/| or | & |\n)\s*", re.IGNORECASE)
_DASH = re.compile(r"\s+[-–]\s+")
_CODE_PREFIX = re.compile(r"^(DE|AT|CH)[-_ ]+(\S.*)$")
_PARENS = re.compile(r"\(([^)]*)\)")
#: Notes after a town that are not part of its name ("(Oder)" is).
_NOTE = re.compile(r"\((?!oder\))[^)]*\)|\b(hybrid|onsite|on-site|office|hq|headquarters|campus)\b", re.I)
_LEADING_POSTCODE = re.compile(r"^(\d{4,5})\s+\S")
_POSTCODE_LENGTH = {DE: 5, AT: 4, CH: 4}

#: US state codes (DE — Delaware — is handled as a bare code instead).
_US_CODES = set(
    "AL AK AZ AR CA CO CT FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
    "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)
#: Places outside DACH that recruiters write next to a DACH-sounding town.
_FOREIGN = {
    "us", "usa", "u.s", "u.s.a", "united states", "united states of america", "america", "uk", "u.k",
    "united kingdom", "england", "scotland", "wales", "northern ireland", "canada", "ontario", "quebec",
    "british columbia", "alberta", "mexico", "brazil", "argentina", "chile", "colombia", "australia",
    "new zealand", "india", "pakistan", "china", "hong kong", "japan", "korea", "south korea", "taiwan",
    "singapore", "malaysia", "indonesia", "thailand", "vietnam", "philippines", "israel", "turkey",
    "united arab emirates", "uae", "egypt", "nigeria", "kenya", "south africa", "france", "netherlands",
    "belgium", "luxembourg", "ireland", "spain", "portugal", "italy", "poland", "czech republic",
    "czechia", "slovakia", "hungary", "romania", "bulgaria", "serbia", "croatia", "slovenia", "greece",
    "cyprus", "malta", "denmark", "sweden", "norway", "finland", "iceland", "estonia", "latvia",
    "lithuania", "ukraine", "liechtenstein",
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware",
    "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi", "missouri",
    "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
    "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
}


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().translate(_FOLD)).strip(" .()-")


def _country_word(segment: str) -> tuple[str, bool] | None:
    """(country, is_bare_code) for a segment naming a DACH country/region."""
    folded = _fold(segment)
    for country, words in _COUNTRY_WORDS.items():
        if folded in words:
            return country, folded in _CODES
    return None


def _foreign(segment: str) -> bool:
    raw = segment.strip()
    texts = [raw, *_PARENS.findall(raw)]
    return any(_fold(t) in _FOREIGN or t.strip() in _US_CODES for t in texts)


def _town(segment: str) -> str | None:
    """A segment as a town name: notes and a leading postcode removed."""
    town = re.sub(r"^\d{4,5}\s+", "", _NOTE.sub(" ", segment)).strip(" ,-")
    return re.sub(r"\s+", " ", town) or None


def _known_city(segment: str | None) -> str | None:
    return _CITY_COUNTRY.get(_fold(_town(segment or "") or ""))


def _one(part: str) -> dict[str, Any] | None:
    coded = _CODE_PREFIX.match(part.strip())
    text = f"{coded.group(2)}, {coded.group(1)}" if coded else part
    segments = [s for s in (x.strip() for x in _DASH.sub(",", text).split(",")) if s]
    if not segments or any(_foreign(s) for s in segments):
        return None
    named: dict[int, tuple[str, bool]] = {}  # segment index → (country, bare code?)
    for i, seg in enumerate(segments):
        word = _country_word(seg) or next(
            (w for w in (_country_word(inner) for inner in _PARENS.findall(seg)) if w), None)
        if word:
            named[i] = word
    countries = {c for c, _ in named.values()}
    if len(countries) > 1:
        return None
    if countries:
        country = countries.pop()
        town_seg = next((s for i, s in enumerate(segments) if i not in named or _known_city(s)), None)
        if all(bare for _, bare in named.values()) and _known_city(town_seg) != country:
            return None  # "Wilmington, DE": a bare code needs a known city
    else:
        cities = [s for s in segments if _known_city(s)]
        if not cities:
            return None
        town_seg = cities[-1]
        country = _known_city(town_seg)
        for seg in segments:
            if seg is town_seg or re.search(r"\d", seg) or _NOT_A_TOWN.search(seg) or _known_city(seg) == country:
                continue
            return None  # "Ontario - Hamburg": another place is named
    town = _town(town_seg) if town_seg else None
    if town and _NOT_A_TOWN.search(town):
        town = None
    known = _CITY_COUNTRY.get(_fold(town or ""))
    if known and known != country:
        return None  # "Basel, Germany": contradictory — not guessed
    postcode = None
    for seg in segments:
        lead = _LEADING_POSTCODE.match(seg)
        if lead and len(lead.group(1)) == _POSTCODE_LENGTH[country]:
            postcode = lead.group(1)
            break
    return {"country": country, "city": town, "postal_code": postcode,
            "street": None, "region": None, "label": part.strip()[:200]}


def dach_place(*texts: str | None) -> dict[str, Any] | None:
    """The first DACH place named in these location texts, in order; a place
    with a town wins over one naming only the country."""
    found: dict[str, Any] | None = None
    for text in texts:
        for part in _PART_SPLIT.split(text or ""):
            place = _one(part)
            if place and place["city"]:
                return place
            found = found or place
    return found
