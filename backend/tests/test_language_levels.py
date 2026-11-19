"""ELI-56: a language carries its level — Muttersprache, Verhandlungssicher …

Stored in the same `languages` list of strings as before, as "Sprache (Niveau)",
so every existing entry ("Deutsch") stays valid and simply has no level. The
scale is LinkedIn's, in German. A CV may set a level only when it states one.
"""

from __future__ import annotations

import pytest

from app.domain.candidates.languages import (
    LANGUAGE_LEVELS,
    ground_language_levels,
    normalise_language,
    split_language,
    split_languages,
)
from app.domain.candidates.schemas import CandidateCreate, CandidateUpdate


def test_the_scale_is_linkedins_five_steps_in_german() -> None:
    assert LANGUAGE_LEVELS == (
        "Muttersprache",
        "Verhandlungssicher",
        "Fließend",
        "Erweiterte Grundkenntnisse",
        "Grundkenntnisse",
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Deutsch", ("Deutsch", None)),
        ("Deutsch (Muttersprache)", ("Deutsch", "Muttersprache")),
        ("Deutsch (muttersprachlich)", ("Deutsch", "Muttersprache")),
        ("Russisch – zweisprachig", ("Russisch", "Muttersprache")),
        ("English (native)", ("English", "Muttersprache")),
        ("Englisch: verhandlungssicher", ("Englisch", "Verhandlungssicher")),
        ("Englisch (fließend)", ("Englisch", "Fließend")),
        ("Englisch - gute Kenntnisse", ("Englisch", "Fließend")),
        ("Französisch (erweiterte Grundkenntnisse)", ("Französisch", "Erweiterte Grundkenntnisse")),
        ("Spanisch (Grundkenntnisse)", ("Spanisch", "Grundkenntnisse")),
    ],
)
def test_a_stated_level_is_read(raw: str, expected: tuple[str, str | None]) -> None:
    assert split_language(raw) == expected


def test_an_unknown_qualifier_is_kept_as_written_not_guessed() -> None:
    # CEFR or anything else is not mapped onto the scale — that would be a guess.
    assert split_language("Englisch (C1)") == ("Englisch (C1)", None)
    assert normalise_language("Englisch (C1)") == "Englisch (C1)"


def test_normalising_is_canonical_and_idempotent() -> None:
    assert normalise_language("  Englisch (fluent) ") == "Englisch (Fließend)"
    assert normalise_language("Englisch (Fließend)") == "Englisch (Fließend)"
    assert normalise_language("Deutsch") == "Deutsch"


def test_old_entries_without_level_stay_valid_on_create_and_update() -> None:
    created = CandidateCreate(full_name="A", languages=["Deutsch", "Englisch (verhandlungssicher)"])
    assert created.languages == ["Deutsch", "Englisch (Verhandlungssicher)"]
    updated = CandidateUpdate(languages=["Polnisch (Muttersprache)", "", "Deutsch"])
    assert updated.languages == ["Polnisch (Muttersprache)", "Deutsch"]


def test_a_cv_list_is_not_cut_inside_a_level() -> None:
    assert split_languages("Deutsch (Muttersprache), Englisch (fließend, C1); Spanisch") == [
        "Deutsch (Muttersprache)",
        "Englisch (fließend, C1)",
        "Spanisch",
    ]


def test_a_cv_level_needs_its_word_in_the_cv() -> None:
    cv = "Sprachen\nDeutsch Muttersprache\nEnglisch\nFranzösisch Grundkenntnisse"
    # The model added "fließend" to Englisch — the CV says nothing about it.
    out = ground_language_levels(
        ["Deutsch (Muttersprache)", "Englisch (fließend)", "Französisch (Grundkenntnisse)"], cv
    )
    assert out == ["Deutsch (Muttersprache)", "Englisch", "Französisch (Grundkenntnisse)"]


def test_a_level_word_inside_another_word_is_no_evidence() -> None:
    cv = "Sprachen: Englisch. Erfahrung mit alternativen Antrieben, BASIC-Programmierung."
    assert ground_language_levels(["Englisch (native)"], cv) == ["Englisch"]


def test_eszett_spellings_read_the_same() -> None:
    assert split_language("Englisch (Fließend / gute Kenntnisse)") == ("Englisch", "Fließend")


def test_cv_extraction_keeps_only_stated_levels() -> None:
    from app.agents.document_extraction import ExtractedField
    from app.domain.documents.service import _ground_languages

    cv = "Sprachkenntnisse: Deutsch (Muttersprache), Englisch, Polnisch – Grundkenntnisse"
    fields = [
        ExtractedField(
            field="languages",
            value="Deutsch (Muttersprache); Englisch (verhandlungssicher); Polnisch – Grundkenntnisse",
            confidence=0.9,
        ),
        ExtractedField(field="city", value="Berlin", confidence=0.9),
    ]
    out, notes = _ground_languages(cv, fields)
    assert out[0].value == "Deutsch (Muttersprache); Englisch; Polnisch (Grundkenntnisse)"
    assert out[1].value == "Berlin"
    assert notes == ["languages: a level not stated in the document was dropped"]
