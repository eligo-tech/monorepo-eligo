"""The Wiedervorlage date reader (ELI-44): German date phrases in a note.

"Aktuell brauchen sie nichts, ich soll mich Anfang Februar wieder melden" —
the recruiter wrote the date into the note and then typed it into a
calendar by hand. `suggest_dates` reads it back out, deterministically, so
the UI can OFFER "Wiedervorlage am 01.02.2027 anlegen?" for one click. It
never creates anything; a person confirms.

Every case is resolved against a fixed note date, never against today, so
the suite means the same thing next February as it does now.

Rules under test:
  * a month already past this year means next year;
  * Anfang = first working day, Mitte = the 15th, Ende = last working day;
  * a computed date that lands on a weekend moves to the next Monday
    (an explicit "am 3.2." is kept as written);
  * working days skip Saturday, Sunday and 1.1. / 25.12. / 26.12.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.domain.followups.dates import suggest_dates

#: Tuesday, 17 November 2026 — the default note date below.
TUE = dt.date(2026, 11, 17)


def first(text: str, ref: dt.date = TUE) -> dt.date | None:
    found = suggest_dates(text, ref)
    return found[0].due_date if found else None


def test_the_ticket_example() -> None:
    note = (
        "Erstkontakt, Rückruf von Frau Weber. Aktuell brauchen sie nichts, "
        "ich soll mich Anfang Februar wieder melden."
    )
    found = suggest_dates(note, TUE)
    assert [s.due_date for s in found] == [dt.date(2027, 2, 1)]
    # The phrase is what the UI quotes back: "aus der Notiz: „Anfang Februar“".
    assert found[0].phrase == "Anfang Februar"
    assert note[found[0].start:found[0].end] == "Anfang Februar"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Anfang = first working day; 1 Jan is a holiday, 2/3 Jan 2027 a weekend.
        ("Anfang Februar", dt.date(2027, 2, 1)),
        ("anfang januar", dt.date(2027, 1, 4)),
        ("Anfang Jänner", dt.date(2027, 1, 4)),
        # Mitte = the 15th.
        ("Mitte März", dt.date(2027, 3, 15)),
        ("Mitte Maerz", dt.date(2027, 3, 15)),
        # Ende = last working day: 31 Jan 2027 is a Sunday.
        ("Ende Januar", dt.date(2027, 1, 29)),
        ("Ende Feb.", dt.date(2027, 2, 26)),
        # The current month, not yet over: this year.
        ("Ende November", dt.date(2026, 11, 30)),
        # "im November" said in November: from now on, not next November.
        ("im November", dt.date(2026, 11, 18)),
        # A year named wins.
        ("Anfang Februar 2028", dt.date(2028, 2, 1)),
        ("im Februar", dt.date(2027, 2, 1)),
        ("ab März", dt.date(2027, 3, 1)),
        ("im Dezember", dt.date(2026, 12, 1)),
    ],
)
def test_month_phrases(text: str, expected: dt.date) -> None:
    assert first(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ende des Monats", dt.date(2026, 11, 30)),
        ("zum Monatsende", dt.date(2026, 11, 30)),
        ("Anfang nächsten Monats", dt.date(2026, 12, 1)),
        ("Anfang des nächsten Monats", dt.date(2026, 12, 1)),
        ("Mitte nächsten Monats", dt.date(2026, 12, 15)),
        ("nächsten Monat", dt.date(2026, 12, 1)),
        ("im kommenden Monat", dt.date(2026, 12, 1)),
        ("Anfang nächsten Jahres", dt.date(2027, 1, 4)),
        ("im neuen Jahr", dt.date(2027, 1, 4)),
        ("nach Neujahr", dt.date(2027, 1, 4)),
        ("nach Weihnachten", dt.date(2027, 1, 4)),
        ("im nächsten Quartal", dt.date(2027, 1, 4)),
    ],
)
def test_relative_month_and_year(text: str, expected: dt.date) -> None:
    assert first(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("nächste Woche", dt.date(2026, 11, 23)),
        ("naechste Woche", dt.date(2026, 11, 23)),
        ("kommende Woche", dt.date(2026, 11, 23)),
        ("übernächste Woche", dt.date(2026, 11, 30)),
        ("Ende der Woche", dt.date(2026, 11, 20)),
        ("Ende nächster Woche", dt.date(2026, 11, 27)),
        ("in 2 Wochen", dt.date(2026, 12, 1)),
        ("in zwei Wochen", dt.date(2026, 12, 1)),
        ("in einer Woche", dt.date(2026, 11, 24)),
        ("in 2-3 Wochen", dt.date(2026, 12, 1)),
        ("in 14 Tagen", dt.date(2026, 12, 1)),
        # Saturday 21 Nov → Monday.
        ("in 4 Tagen", dt.date(2026, 11, 23)),
        ("in drei Monaten", dt.date(2027, 2, 17)),
        ("in einem Monat", dt.date(2026, 12, 17)),
        ("in einem halben Jahr", dt.date(2027, 5, 17)),
        ("morgen", dt.date(2026, 11, 18)),
        ("übermorgen", dt.date(2026, 11, 19)),
        ("am Freitag", dt.date(2026, 11, 20)),
        ("nächsten Montag", dt.date(2026, 11, 23)),
        ("KW 6", dt.date(2027, 2, 8)),
        ("in KW6", dt.date(2027, 2, 8)),
        ("Kalenderwoche 50", dt.date(2026, 12, 7)),
        # Easter 2027 is 28 March: the Tuesday after Easter Monday.
        ("nach Ostern", dt.date(2027, 3, 30)),
    ],
)
def test_relative_phrases(text: str, expected: dt.date) -> None:
    assert first(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("am 3.2.", dt.date(2027, 2, 3)),
        ("am 03.02.", dt.date(2027, 2, 3)),
        ("bis zum 20.11.", dt.date(2026, 11, 20)),
        ("03.02.2027", dt.date(2027, 2, 3)),
        ("am 3.2.27", dt.date(2027, 2, 3)),
        ("am 3. Februar", dt.date(2027, 2, 3)),
        ("am 21. November", dt.date(2026, 11, 21)),  # a Saturday, as written
    ],
)
def test_explicit_dates(text: str, expected: dt.date) -> None:
    assert first(text) == expected


def test_a_month_already_past_is_next_year_in_december() -> None:
    assert first("Anfang Januar", dt.date(2026, 12, 10)) == dt.date(2027, 1, 4)
    assert first("Mitte Dezember", dt.date(2026, 12, 10)) == dt.date(2026, 12, 15)


@pytest.mark.parametrize(
    "text",
    [
        # CV history and past events are not follow-ups (review of #277).
        "Er war im März 2024 bei Siemens",
        "im Mai 2025 gewechselt",
        "Ende Januar 2026",
        "KW 1/2026 war Urlaub",
        "Gespräch am 12.11. war gut",
        "Gespräch vom 3.11.",
        "KW 46 telefoniert",
        "im Oktober war er krank",
        # The current month's start, already past, is not next year's.
        "Anfang November",
        "Mitte November",
        # A birth year, and a career plan, are not a calendar entry.
        "Jahrgang 12.5.85",
        "in 5 Jahren will er Teamleiter sein",
        "in 999 Jahren",
    ],
)
def test_the_past_and_the_far_future_are_not_offered(text: str) -> None:
    assert suggest_dates(text, TUE) == []


def test_more_review_cases() -> None:
    assert first("ueber morgen") == dt.date(2026, 11, 19)
    assert first("im Dezember melden", dt.date(2026, 12, 10)) == dt.date(2026, 12, 11)
    # Far enough behind, a date without a year is next year's.
    assert first("am 3.2.") == dt.date(2027, 2, 3)
    assert first("Anfang Juni wieder melden") == dt.date(2027, 6, 1)


def test_nothing_to_read() -> None:
    assert suggest_dates("Kein Bedarf, kein Interesse.", TUE) == []
    assert suggest_dates("", TUE) == []
    # "heute morgen" is this morning, not tomorrow.
    assert suggest_dates("Heute Morgen hat sie zurückgerufen.", TUE) == []
    # Not dates: a version number, a percentage, an impossible day.
    assert suggest_dates("Version 3.2 läuft, 40.13. ist kein Datum", TUE) == []


def test_several_phrases_in_order_without_duplicates() -> None:
    note = "Am Montag telefoniert. In 2 Wochen nochmal, spätestens Mitte Dezember. Ende Dezember?"
    found = suggest_dates(note, TUE)
    assert [s.phrase for s in found] == ["Am Montag", "In 2 Wochen", "Mitte Dezember"]
    assert [s.due_date for s in found] == [dt.date(2026, 11, 23), dt.date(2026, 12, 1), dt.date(2026, 12, 15)]


def test_the_same_date_twice_is_offered_once() -> None:
    found = suggest_dates("Anfang Februar melden — also im Februar", TUE)
    assert [s.due_date for s in found] == [dt.date(2027, 2, 1)]


def test_never_before_the_note_date() -> None:
    # On the last working day, "Ende des Monats" is that day, not earlier.
    assert first("Ende des Monats", dt.date(2026, 11, 30)) == dt.date(2026, 11, 30)
    # On a Saturday after it, the month's end has passed: next month's.
    assert first("Ende des Monats", dt.date(2027, 1, 30)) == dt.date(2027, 2, 26)
