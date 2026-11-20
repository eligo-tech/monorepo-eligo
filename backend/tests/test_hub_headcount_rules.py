"""ELI-54: employer headcount read out of ad texts — the deterministic rules.

An ad's self-statement ("Mit rund 250 Mitarbeitenden sind wir …") is a public
company fact. The rules are deliberately conservative: a team, a department, a
site, a leadership span, people served, a hiring count or a parent group's
total is not the employer's headcount, and when a clause is unclear the rules
skip it. A missing size costs a row in the filter; a wrong one misleads.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.domain.hub import headcount
from app.domain.hub.headcount import Statement


def _one(text: str) -> tuple[int, int | None, str]:
    found = headcount.extract_statements(text)
    assert len(found) == 1, found
    return found[0].min, found[0].max, found[0].scope


# --- what counts -----------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Mit rund 250 Mitarbeitenden sind wir ein führender Anbieter.", (250, 250)),
        ("Wir sind ein Familienunternehmen mit über 500 Mitarbeitern.", (500, None)),
        ("Unsere 1.200 Beschäftigten arbeiten an Lösungen für morgen.", (1200, 1200)),
        ("Wir beschäftigen ca. 80 Mitarbeiter*innen in Bayern.", (80, 80)),
        ("Als mittelständisches Unternehmen mit mehr als 3.000 Mitarbeiter:innen …", (3000, None)),
        ("Wir sind ein Team? Nein: ein Unternehmen mit 45 Angestellten.", (45, 45)),
        ("Als Familienunternehmen, das seit 1950 besteht, beschäftigen wir 300 Mitarbeiter.", (300, 300)),
        ("Wir sind ein internationales Unternehmen mit 250 Mitarbeitern.", (250, 250)),
        ("Mit über 2000 Mitarbeitern sind wir ein großer Arbeitgeber.", (2000, None)),
        ("Bei uns arbeiten zwischen 50 und 100 Beschäftigte.", (50, 100)),
        ("Mitarbeiterzahl: 51-200", (51, 200)),
        ("Unternehmensgröße: 1.001 – 5.000 Mitarbeiter", (1001, 5000)),
        ("We are a company with more than 1,000 employees in Europe.", (1000, None)),
        ("Mit 250+ engagierten Mitarbeitenden betreuen wir Projekte.", (250, None)),
        ("Wir zählen aktuell 3 Mitarbeiter.", (3, 3)),
    ],
)
def test_reads_an_employer_self_statement(text: str, expected: tuple[int, int | None]) -> None:
    lo, hi, scope = _one(text)
    assert (lo, hi) == expected
    assert scope == "local"


def test_the_quote_is_the_sentence_it_came_from() -> None:
    text = "Ihre Aufgaben sind vielfältig. Mit rund 250 Mitarbeitenden sind wir ein führender Anbieter. Bewerben Sie sich!"
    (s,) = headcount.extract_statements(text)
    assert s.quote == "Mit rund 250 Mitarbeitenden sind wir ein führender Anbieter."


def test_a_worldwide_total_is_marked_as_such() -> None:
    lo, hi, scope = _one("Wir sind ein Familienunternehmen mit weltweit 3.500 Mitarbeitenden.")
    assert (lo, hi, scope) == (3500, 3500, "worldwide")


# --- what does not ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # Team, department, site — smaller than the employer.
        "Sie arbeiten in einem Team von 15 Mitarbeitern.",
        "Unser Team aus rund 20 Kolleginnen und Kollegen freut sich auf Sie.",
        "Die Abteilung mit 12 Mitarbeitenden verantwortet den Einkauf.",
        "An unserem Standort in Ulm arbeiten 300 Mitarbeitende.",
        "Unsere Station mit 25 Beschäftigten sucht Verstärkung.",
        "Sie arbeiten mit 20 Mitarbeitenden in unserem Team.",
        # Leadership span.
        "Sie führen 8 Mitarbeiter disziplinarisch.",
        "Personalverantwortung für 15 Mitarbeitende.",
        "Sie übernehmen die Leitung von 10 Mitarbeitern.",
        # People served / the customers' staff.
        "Wir betreuen die Lohnabrechnung für 200 Mitarbeiter unserer Kunden.",
        "Unsere Kunden sind Unternehmen mit 50 bis 500 Mitarbeitern.",
        "Wir versorgen 120 Bewohner mit 60 Mitarbeitern.",
        "Wir betreuen 500 Patienten.",
        # Hiring counts and thresholds.
        "Wir suchen 5 Mitarbeiter (m/w/d) für die Produktion.",
        "3 Mitarbeiter (m/w/d) gesucht",
        "Förderung für Betriebe ab 10 Mitarbeitern.",
        "Bis zu 50 Mitarbeiter pro Schicht.",
        # The parent group's total, not the employer's.
        "Wir sind Teil der XY-Gruppe mit 50.000 Mitarbeitenden.",
        "Als Tochter eines Konzerns mit über 10.000 Beschäftigten …",
        "Unsere Unternehmensgruppe beschäftigt 2.000 Mitarbeiter.",
        # No employer context at all.
        "250 Mitarbeiter",
        "Menschen: 500 Menschen vertrauen uns täglich.",
        # Colleagues you will work with, not the company (review of #301).
        "Mit 2 Kollegen bildest du das Team.",
        "Gemeinsam mit 4 Kollegen betreust du die Anlage.",
        "Mit 2-3 Mitarbeitern arbeitest du zusammen.",
        "Mit Ihren 5 Mitarbeitern betreuen Sie den Bereich.",
        "Sie haben bereits Erfahrung mit 10 Mitarbeitern.",
        # Hiring, absences, field staff.
        "Wir stellen 5 Mitarbeiter ein.",
        "Wir haben 5 neue Mitarbeiter eingestellt.",
        "Wir haben 3 Mitarbeiter in Elternzeit.",
        "Mit 3 Mitarbeitern im Außendienst sind wir unterwegs.",
        "Wir bieten 40 Stunden und 2 Mitarbeitern im Homeoffice.",
        # Not a number of people.
        "Wir haben 24/7 Mitarbeiter im Einsatz.",
        "Wir haben 2024 Mitarbeiter geehrt.",
        # History, placements, a client's size.
        "Wir sind 2019 mit 3 Mitarbeitern gestartet.",
        "Als Personaldienstleister vermitteln wir jährlich 2.000 Mitarbeiter.",
        "Our client is a company with 200 employees.",
    ],
)
def test_skips_what_is_not_the_employers_headcount(text: str) -> None:
    assert headcount.extract_statements(text) == []


def test_today_wins_over_the_founding_figure() -> None:
    found = headcount.extract_statements(
        "Gegründet 1998 mit 5 Mitarbeitern, heute über 400 Mitarbeitende."
    )
    assert [(s.min, s.max) for s in found] == [(400, None)]


def test_a_worldwide_marker_belongs_to_its_number_not_the_sentence() -> None:
    found = headcount.extract_statements("Mit 12.000 Mitarbeitenden in Deutschland und 40.000 weltweit sind wir groß.")
    assert [(s.min, s.scope) for s in found] == [(12000, "local")]


def test_a_target_group_is_not_a_parent_group() -> None:
    assert headcount.extract_statements(
        "Unsere Zielgruppe sind Familien, und mit rund 250 Mitarbeitenden sind wir für sie da."
    )


def test_nothing_in_an_empty_text() -> None:
    assert headcount.extract_statements(None) == []
    assert headcount.extract_statements("") == []


# --- one company, many ads ----------------------------------------------------------


def _st(lo: int, hi: int | None, scope: str = "local") -> Statement:
    return Statement(min=lo, max=hi, scope=scope, quote=f"mit {lo} Mitarbeitern")


T1 = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
T2 = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
T3 = dt.datetime(2026, 11, 15, tzinfo=dt.UTC)


def test_the_most_frequent_statement_wins() -> None:
    choice = headcount.aggregate(
        [(_st(250, 250), "a", T1), (_st(250, 250), "b", T2), (_st(300, 300), "c", T3)]
    )
    assert (choice.min, choice.max) == (250, 250)
    # Evidence: the newest ad that carries the chosen value.
    assert choice.ref == "b" and choice.as_of == T2


def test_a_tie_goes_to_the_newest() -> None:
    choice = headcount.aggregate([(_st(250, 250), "a", T1), (_st(300, 300), "c", T3)])
    assert (choice.min, choice.ref) == (300, "c")


def test_a_worldwide_total_is_used_only_when_nothing_else_is_said() -> None:
    both = headcount.aggregate(
        [(_st(3500, 3500, "worldwide"), "w", T3), (_st(250, 250), "l", T1)]
    )
    assert both.min == 250
    alone = headcount.aggregate([(_st(3500, 3500, "worldwide"), "w", T3)])
    assert alone.min == 3500
    assert headcount.aggregate([]) is None


# --- buckets ---------------------------------------------------------------------------


def test_the_route_offers_the_same_buckets() -> None:
    from typing import get_args

    from app.domain.hub.router import HeadcountBucket

    assert list(get_args(HeadcountBucket)) == list(headcount.BUCKETS)


def test_the_ten_buckets_of_the_ticket() -> None:
    assert list(headcount.BUCKETS) == [
        "1-3", "4-10", "11-50", "51-150", "151-300", "301-650",
        "651-1000", "1001-5000", "5001-10000", "10001+",
    ]


@pytest.mark.parametrize(
    "lo,hi,expected",
    [
        (250, 250, {"151-300"}),
        (300, 300, {"151-300"}),
        (301, 301, {"301-650"}),
        # A range matches every bucket it overlaps.
        (51, 200, {"51-150", "151-300"}),
        (1001, 5000, {"1001-5000"}),
        # Open-ended: "über 500" overlaps everything from 301-650 up.
        (500, None, {"301-650", "651-1000", "1001-5000", "5001-10000", "10001+"}),
        (20000, 20000, {"10001+"}),
    ],
)
def test_a_range_matches_every_bucket_it_overlaps(lo: int, hi: int | None, expected: set[str]) -> None:
    assert {b for b in headcount.BUCKETS if headcount.overlaps(lo, hi, b)} == expected


# --- which source wins ---------------------------------------------------------------


def test_the_newest_dated_value_wins_across_sources() -> None:
    # A Wikidata figure "as of 2021" never replaces an ad statement read this month…
    assert not headcount.replaces(
        new_source="wikidata", new_as_of=dt.datetime(2021, 1, 1, tzinfo=dt.UTC),
        cur_source="ad_text", cur_as_of=T2,
    )
    # …an undated Wikidata figure never replaces anything dated…
    assert not headcount.replaces(new_source="wikidata", new_as_of=None, cur_source="ad_text", cur_as_of=T1)
    # …and a newer ad statement replaces an older Wikidata figure.
    assert headcount.replaces(
        new_source="ad_text", new_as_of=T3, cur_source="wikidata",
        cur_as_of=dt.datetime(2024, 12, 31, tzinfo=dt.UTC),
    )
    # The same source re-reading itself always refreshes its value.
    assert headcount.replaces(new_source="ad_text", new_as_of=T1, cur_source="ad_text", cur_as_of=T3)
    # Nothing stored yet: anything wins.
    assert headcount.replaces(new_source="wikidata", new_as_of=None, cur_source=None, cur_as_of=None)


# --- EURES organisationSizeCode ---------------------------------------------------------


@pytest.mark.parametrize(
    "code,expected",
    [
        ("10-49", (10, 49)),
        ("250+", (250, None)),
        ("1-9", (1, 9)),
        ("50 - 249", (50, 249)),
        # Unknown shapes are not guessed at.
        ("SME", None),
        ("", None),
        (None, None),
        ("3", None),
    ],
)
def test_eures_size_codes_map_only_when_they_spell_a_band(code, expected) -> None:
    assert headcount.eures_size(code) == expected
