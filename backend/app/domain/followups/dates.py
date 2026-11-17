"""Read a follow-up date out of a German note (ELI-44). Pure, deterministic.

"Aktuell brauchen sie nichts, ich soll mich Anfang Februar wieder melden."
The recruiter has just written the date down; making them type it into a
calendar again is the manual step the ticket asks to remove. This module
finds such phrases and resolves each to a calendar date relative to the
NOTE's date (never "today" — a note filed late still means what it said).

It only SUGGESTS. Nothing here writes; the UI offers "Wiedervorlage am …
anlegen?" and a person confirms with one click (agents propose, people
decide). No model call: the phrases are a closed set and a rule that is
wrong is wrong the same way every time, which a test can pin down.

Rules:
  * Anfang = first working day of the month, Mitte = the 15th, Ende = the
    last working day. A month named without a year whose date has already
    passed means next year ("Anfang Februar" in November → next February).
  * A COMPUTED date that falls on a weekend or on 1.1. / 25.12. / 26.12.
    (holidays in all of DACH) moves to the next working day. A date written
    out ("am 21.11.", "am 3. Februar") is kept as written.
  * Never before the note's date: a resolved date in the past moves to the
    next occurrence (next year, next month, next week), and an explicit
    date with a year that is already past is not a follow-up at all.
  * Several phrases: each is offered, in the order they appear, each date
    once, at most `MAX_SUGGESTIONS`. Overlapping matches keep the longer.

Not read (deliberately): school holidays ("nach den Sommerferien" differs
per Bundesland), bare month names without a preposition ("Februar ist
schlecht"), and ranges beyond their first value ("in 2-3 Wochen" → 2).
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass

#: Offered at most per note: a note naming five dates is not five to-dos.
MAX_SUGGESTIONS = 3

#: Fixed holidays shared by Germany, Austria and Switzerland.
_HOLIDAYS = frozenset({(1, 1), (12, 25), (12, 26)})


@dataclass(frozen=True)
class DateSuggestion:
    due_date: dt.date
    #: The phrase as written in the note — what the UI quotes back.
    phrase: str
    start: int
    end: int


# --- calendar helpers --------------------------------------------------------


def _working(d: dt.date) -> bool:
    return d.weekday() < 5 and (d.month, d.day) not in _HOLIDAYS


def _roll(d: dt.date) -> dt.date:
    """The next working day, or `d` itself."""
    while not _working(d):
        d += dt.timedelta(days=1)
    return d


def _first_working(year: int, month: int) -> dt.date:
    return _roll(dt.date(year, month, 1))


def _last_working(year: int, month: int) -> dt.date:
    d = dt.date(year, month, calendar.monthrange(year, month)[1])
    while not _working(d):
        d -= dt.timedelta(days=1)
    return d


def _part(part: str | None, year: int, month: int) -> dt.date:
    part = (part or "anfang").lower()
    if part == "mitte":
        return _roll(dt.date(year, month, 15))
    if part == "ende":
        return _last_working(year, month)
    return _first_working(year, month)


def _add_months(d: dt.date, months: int) -> dt.date:
    year, month0 = divmod(d.month - 1 + months, 12)
    year += d.year
    return dt.date(year, month0 + 1, min(d.day, calendar.monthrange(year, month0 + 1)[1]))


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _monday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def _easter(year: int) -> dt.date:
    """Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    lv = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lv) // 451
    month = (h + lv - 7 * m + 114) // 31
    day = (h + lv - 7 * m + 114) % 31 + 1
    return dt.date(year, month, day)


def _year(raw: str | None) -> int | None:
    if not raw:
        return None
    value = int(raw)
    return 2000 + value if value < 100 else value


# --- vocabulary --------------------------------------------------------------

_MONTH_WORDS: dict[int, str] = {
    1: r"januar|jan|jänner|jaenner",
    2: r"februar|feb",
    3: r"märz|maerz|mär|mrz",
    4: r"april|apr",
    5: r"mai",
    6: r"juni|jun",
    7: r"juli|jul",
    8: r"august|aug",
    9: r"september|sept|sep",
    10: r"oktober|okt",
    11: r"november|nov",
    12: r"dezember|dez",
}
_MONTH = r"(?P<month>" + "|".join(_MONTH_WORDS.values()) + r")\.?(?![\w])"
_MONTH_EXACT = {m: re.compile(rf"(?:{words})\.?", re.IGNORECASE) for m, words in _MONTH_WORDS.items()}

_NUMBERS = {
    "ein": 1, "eine": 1, "einem": 1, "einer": 1, "einen": 1,
    "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5, "sechs": 6,
    "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11, "zwölf": 12, "zwoelf": 12,
}
_NUM = r"\d{1,3}|" + "|".join(sorted(_NUMBERS, key=len, reverse=True))
_NEXT = r"(?:nächste|naechste|kommende)[nrs]?"
_WEEKDAYS = ["montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"]


#: Written out in full: a dot after one ends the sentence, not the word.
_FULL_MONTHS = frozenset({
    "januar", "jänner", "jaenner", "februar", "märz", "maerz", "april", "mai", "juni",
    "juli", "august", "september", "oktober", "november", "dezember",
})


def _month_number(word: str) -> int:
    for number, pattern in _MONTH_EXACT.items():
        if pattern.fullmatch(word):
            return number
    raise ValueError(word)  # unreachable: the word came from `_MONTH`


def _number(word: str) -> int:
    return int(word) if word.isdigit() else _NUMBERS[word.lower()]


# --- rules: (pattern, resolver(match, note date) -> date | None) -------------

Resolver = Callable[[re.Match[str], dt.date], dt.date | None]


def _named_month(m: re.Match[str], ref: dt.date) -> dt.date:
    """"Anfang Februar", "im März", "ab Mai 2027"."""
    month = _month_number(m["month"])
    part = m.groupdict().get("part")
    year = _year(m["year"])
    if year is not None:
        return _part(part, year, month)
    d = _part(part, ref.year, month)
    return d if d >= ref else _part(part, ref.year + 1, month)


def _day_month_name(m: re.Match[str], ref: dt.date) -> dt.date | None:
    """"am 3. Februar" — kept as written."""
    return _explicit(int(m["day"]), _month_number(m["month"]), _year(m["year"]), ref)


def _numeric(m: re.Match[str], ref: dt.date) -> dt.date | None:
    """"am 3.2.", "03.02.2027", "3.2.27" — kept as written."""
    return _explicit(int(m["day"]), int(m["mon"]), _year(m["year"]), ref)


def _explicit(day: int, month: int, year: int | None, ref: dt.date) -> dt.date | None:
    try:
        if year is not None:
            d = dt.date(year, month, day)
            return d if d >= ref else None
        d = dt.date(ref.year, month, day)
        return d if d >= ref else dt.date(ref.year + 1, month, day)
    except ValueError:
        return None  # 40.13., or 29.2. in a common year


def _calendar_week(m: re.Match[str], ref: dt.date) -> dt.date | None:
    week = int(m["week"])
    year = _year(m["year"])
    try:
        if year is not None:
            return dt.date.fromisocalendar(year, week, 1)
        iso_year, iso_week, _ = ref.isocalendar()
        d = dt.date.fromisocalendar(iso_year, week, 1)
        if d >= ref:
            return d
        if week == iso_week:  # "diese KW" said mid-week: the week is now
            return ref
        return dt.date.fromisocalendar(iso_year + 1, week, 1)
    except ValueError:
        return None  # KW 0, KW 54, KW 53 in a 52-week year


def _in_n(m: re.Match[str], ref: dt.date) -> dt.date:
    n = _number(m["n"])
    unit = m["unit"].lower()
    if unit.startswith("tag"):
        return _roll(ref + dt.timedelta(days=n))
    if unit.startswith("woche"):
        return _roll(ref + dt.timedelta(weeks=n))
    if unit.startswith("monat"):
        return _roll(_add_months(ref, n))
    return _roll(_add_months(ref, 12 * n))


def _half_year(m: re.Match[str], ref: dt.date) -> dt.date:
    return _roll(_add_months(ref, 6))


def _week(m: re.Match[str], ref: dt.date) -> dt.date:
    """"nächste Woche" (its Monday), "Ende der Woche" (Friday), "Mitte
    nächster Woche" (Wednesday)."""
    offset = {"anfang": 0, "mitte": 2, "ende": 4}[(m["part"] or "anfang").lower()]
    which = (m["which"] or "").lower()
    if which.startswith(("über", "ueber")):
        weeks = 2
    elif which:
        weeks = 1
    else:
        weeks = 0
    d = _monday(ref) + dt.timedelta(weeks=weeks, days=offset)
    return d if d >= ref else d + dt.timedelta(weeks=1)


def _relative_month(m: re.Match[str], ref: dt.date) -> dt.date:
    """"nächsten Monat", "Mitte nächsten Monats"."""
    return _part(m["part"], *_next_month(ref.year, ref.month))


def _this_month(m: re.Match[str], ref: dt.date) -> dt.date:
    """"Ende des Monats", "Monatsende"."""
    part = m.groupdict().get("part") or "ende"
    d = _part(part, ref.year, ref.month)
    return d if d >= ref else _part(part, *_next_month(ref.year, ref.month))


def _next_quarter(m: re.Match[str], ref: dt.date) -> dt.date:
    first_month = 3 * ((ref.month - 1) // 3) + 4
    year = ref.year + (first_month > 12)
    return _first_working(year, (first_month - 1) % 12 + 1)


def _new_year(m: re.Match[str], ref: dt.date) -> dt.date:
    """"Anfang nächsten Jahres", "nach Neujahr", "nach Weihnachten"."""
    if m["next"]:
        return _first_working(ref.year + 1, 1)
    d = _first_working(ref.year, 1)
    return d if d >= ref else _first_working(ref.year + 1, 1)


def _after_easter(m: re.Match[str], ref: dt.date) -> dt.date:
    """The Tuesday after Easter Monday — the first working day after Easter."""
    d = _easter(ref.year) + dt.timedelta(days=2)
    return d if d >= ref else _easter(ref.year + 1) + dt.timedelta(days=2)


def _tomorrow(m: re.Match[str], ref: dt.date) -> dt.date:
    days = 2 if m[0].lower().startswith(("über", "ueber")) else 1
    return _roll(ref + dt.timedelta(days=days))


def _weekday(m: re.Match[str], ref: dt.date) -> dt.date:
    """"am Freitag": the next one after the note's date."""
    target = _WEEKDAYS.index(m["wd"].lower())
    return ref + dt.timedelta(days=(target - ref.weekday()) % 7 or 7)


_YEAR = r"(?:\s+(?P<year>20\d{2}))?"
_F = re.IGNORECASE

_RULES: list[tuple[re.Pattern[str], Resolver]] = [
    (re.compile(rf"\b(?P<part>anfang|mitte|ende)\s+(?:des\s+)?{_MONTH}{_YEAR}", _F), _named_month),
    (re.compile(rf"\b(?:im|ab|in)\s+{_MONTH}{_YEAR}", _F), _named_month),
    (re.compile(rf"(?:\b(?:am|zum|bis\s+zum)\s+)?(?<![\d.])(?P<day>\d{{1,2}})\.\s*{_MONTH}{_YEAR}", _F), _day_month_name),
    (
        re.compile(
            r"(?:\b(?:am|zum|bis\s+zum|bis)\s+)?(?<![\d.])(?P<day>\d{1,2})\.(?P<mon>\d{1,2})\.(?P<year>\d{4}|\d{2})?(?![\d])",
            _F,
        ),
        _numeric,
    ),
    (re.compile(r"\b(?:in\s+)?(?:der\s+)?(?:kw|kalenderwoche)\s*(?P<week>\d{1,2})(?:\s*/\s*(?P<year>\d{4}))?\b", _F), _calendar_week),
    (
        re.compile(
            rf"\bin\s+(?P<n>{_NUM})(?:\s*[-–]\s*(?:{_NUM}))?\s+(?P<unit>tagen|tage|tag|wochen|woche|monaten|monate|monat|jahren|jahre|jahr)\b",
            _F,
        ),
        _in_n,
    ),
    (re.compile(r"\bin\s+einem\s+halben\s+jahr\b", _F), _half_year),
    (
        re.compile(
            r"\b(?:(?P<part>anfang|mitte|ende)\s+(?:der\s+|dieser\s+)?)?"
            r"(?P<which>übernächste[nr]?|uebernächste[nr]?|übernaechste[nr]?|uebernaechste[nr]?|nächste[nr]?|naechste[nr]?|kommende[nr]?)?"
            r"\s*woche\b",
            _F,
        ),
        _week,
    ),
    (re.compile(rf"\b(?:(?P<part>anfang|mitte|ende)\s+(?:des\s+)?)?(?:im\s+)?{_NEXT}\s+monats?\b", _F), _relative_month),
    (re.compile(r"\b(?P<part>anfang|mitte|ende)\s+(?:des|dieses|diesen)\s+monats\b|\b(?:zum\s+)?monatsende\b", _F), _this_month),
    (re.compile(rf"\b(?:anfang\s+(?:des\s+)?)?(?:im\s+)?{_NEXT}\s+quartals?\b", _F), _next_quarter),
    (
        re.compile(
            rf"\banfang\s+(?:des\s+)?(?P<next>{_NEXT})\s+jahres\b"
            r"|\b(?:anfang\s+des\s+jahres|im\s+neuen\s+jahr|nach\s+neujahr|nach\s+weihnachten|nach\s+dem\s+jahreswechsel)\b",
            _F,
        ),
        _new_year,
    ),
    (re.compile(r"\bnach\s+(?:den\s+)?(?:ostern|osterferien|osterfeiertagen)\b", _F), _after_easter),
    # "heute Morgen" is this morning, "am Morgen" a time of day.
    (
        re.compile(
            r"(?<!heute )(?<!gestern )(?<!am )(?<!guten )(?<!jeden )(?<!den )\b(?:über|ueber)?morgen\b",
            _F,
        ),
        _tomorrow,
    ),
    (re.compile(rf"\b(?:am|nächsten|naechsten|kommenden|diesen)\s+(?P<wd>{'|'.join(_WEEKDAYS)})\b", _F), _weekday),
]


def suggest_dates(text: str, reference: dt.date) -> list[DateSuggestion]:
    """The follow-up dates `text` names, resolved against `reference` (the
    note's date). In order of appearance, each date once, at most
    `MAX_SUGGESTIONS`."""
    if not text:
        return []
    found: list[tuple[int, int, dt.date]] = []
    for pattern, resolve in _RULES:
        for m in pattern.finditer(text):
            # The week rule may match a lone "woche" (no part, no which) —
            # that names no date.
            if resolve is _week and not (m["part"] or m["which"]):
                continue
            d = resolve(m, reference)
            if d is None:
                continue
            end = m.end()
            month = m.groupdict().get("month")
            if month and month.lower() in _FULL_MONTHS and not m["year"] and text[m.end("month"):end] == ".":
                end = m.end("month")
            found.append((m.start(), end, d))

    # Overlaps: the earliest start wins, the longer match on a tie.
    found.sort(key=lambda f: (f[0], -(f[1] - f[0])))
    out: list[DateSuggestion] = []
    seen: set[dt.date] = set()
    taken_to = -1
    for start, end, d in found:
        if start < taken_to:
            continue
        taken_to = end
        if d in seen:
            continue
        seen.add(d)
        out.append(DateSuggestion(due_date=d, phrase=text[start:end], start=start, end=end))
        if len(out) == MAX_SUGGESTIONS:
            break
    return out
