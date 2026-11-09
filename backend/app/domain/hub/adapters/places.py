"""Reading a free-text job location ("Munich, Bavaria, Germany") as a DACH place.

Greenhouse and Lever give locations as text a recruiter typed, not as an
address. Deterministic, no guessing beyond three rules:

  1. a part naming a DACH country (or a German state, Austrian or Swiss
     canton-level region) is in that country; its first segment is the town;
  2. a part whose only or LAST segment is a well-known DACH city ("Berlin",
     "Revaler Straße 28-31, 10245 Berlin", "Munich Hybrid (NavVis GmbH)") is
     in that city's country; "DE-Berlin" and "Germany - Düsseldorf" are read
     as "Berlin, DE" and "Germany, Düsseldorf";
  3. anything else is not a DACH place — "Hamburg, NY" names a non-DACH place
     after the town, and "Remote" names none.

A postcode is taken only when the text carries one (4 digits for AT/CH, 5 for
DE). Measured on Greenhouse EU boards: ~5% of DACH locations do.
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
        "austria", "oesterreich", "at", "aut", "vienna", "wien", "styria", "steiermark", "tyrol",
        "tirol", "upper austria", "oberoesterreich", "lower austria", "niederoesterreich",
        "carinthia", "kaernten", "vorarlberg", "burgenland",
    },
    CH: {
        "switzerland", "schweiz", "suisse", "svizzera", "ch", "che", "zurich", "zuerich",
        "geneva", "geneve", "vaud", "ticino", "canton of zurich", "canton of zug",
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
_NOT_A_TOWN = re.compile(r"\b(remote|home ?office|hybrid|anywhere|europe|emea|dach|worldwide)\b", re.I)
_POSTCODE = {DE: re.compile(r"\b(\d{5})\b"), AT: re.compile(r"\b(\d{4})\b"), CH: re.compile(r"\b(\d{4})\b")}
_PART_SPLIT = re.compile(r"\s*(?:;|\||/| or | & |\n)\s*", re.IGNORECASE)
_DASH = re.compile(r"\s+[-–]\s+")
_CODE_PREFIX = re.compile(r"^(DE|AT|CH)[-_ ]+(\S.*)$")
#: Notes after a town that are not part of its name.
_NOTE = re.compile(r"\(.*?\)|\b(hybrid|onsite|on-site|office|hq|headquarters|campus)\b", re.I)


def _town(segment: str) -> str | None:
    """A segment as a town name: notes and a leading postcode removed."""
    town = re.sub(r"^\d{4,5}\s+", "", _NOTE.sub(" ", segment)).strip(" ,-")
    return re.sub(r"\s+", " ", town) or None


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().translate(_FOLD)).strip(" .()-")


def _country_of(segment: str) -> str | None:
    folded = _fold(segment)
    for country, words in _COUNTRY_WORDS.items():
        if folded in words:
            return country
    return None


def _one(part: str) -> dict[str, Any] | None:
    coded = _CODE_PREFIX.match(part.strip())
    text = f"{coded.group(2)}, {coded.group(1)}" if coded else part
    segments = [s for s in (x.strip() for x in _DASH.sub(",", text).split(",")) if s]
    if not segments:
        return None
    countries = {c for c in (_country_of(s) for s in segments) if c}
    if len(countries) > 1:
        return None  # "Basel, Germany"? contradictory — not guessed
    if countries:
        country = countries.pop()
        # The town: the first segment that is not the country or a region.
        town = next((s for s in segments if not _country_of(s) or _fold(s) in _CITY_COUNTRY), None)
    elif _fold(_town(segments[-1]) or "") in _CITY_COUNTRY:
        town = segments[-1]
        country = _CITY_COUNTRY[_fold(_town(town) or "")]
    else:
        return None
    town = _town(town) if town else None
    if town and _NOT_A_TOWN.search(town):
        town = None
    known = _CITY_COUNTRY.get(_fold(town or ""))
    if known and known != country:
        return None  # "Basel, Germany": contradictory — not guessed
    postcode = _POSTCODE[country].search(part)
    return {"country": country, "city": town or None, "postal_code": postcode.group(1) if postcode else None,
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
