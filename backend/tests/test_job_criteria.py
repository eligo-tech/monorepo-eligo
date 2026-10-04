"""Muss-Kriterien: proposing them, and admitting when there are none.

On the live workspace 63 of 76 mandates carry no must-have skills and 72 no
salary band, so `apply_hard_filters` decides nothing for most of the book —
the deterministic half of the matching rule is a no-op and the recruiter
sees a score that looks filtered. Two answers, both here: say so on the
result, and make the gap one click to close.
"""

from __future__ import annotations

from app.domain.jobs.criteria import (
    normalise_vocabulary,
    suggest_must_have,
)
from app.domain.jobs.models import Job
from app.domain.matching.service import active_criteria

VOCAB = {
    "Java": 40,
    "JavaScript": 30,
    "Spring Boot": 12,
    "Kubernetes": 20,
    "SAP": 25,
    "SAP Business": 4,
    "Golang": 4,
    "Rust": 2,  # below MIN_VOCABULARY_COUNT
}


class TestSuggestions:
    def test_the_title_names_the_stack(self) -> None:
        got = [s.skill for s in suggest_must_have("Anwendungsentwickler Java", VOCAB)]
        assert got == ["Java"]

    def test_a_multi_word_skill_must_appear_as_a_phrase(self) -> None:
        assert [s.skill for s in suggest_must_have("Java Spring Boot Senior", VOCAB)] == [
            "Java",
            "Spring Boot",
        ]
        assert "Spring Boot" not in [
            s.skill for s in suggest_must_have("Boot Camp Spring Festival", VOCAB)
        ]

    def test_java_is_not_proposed_for_javascript(self) -> None:
        assert [s.skill for s in suggest_must_have("JavaScript-Entwickler", VOCAB)] == [
            "JavaScript"
        ]

    def test_overlapping_terms_do_not_both_appear(self) -> None:
        # Clicking "SAP" AND "SAP Business" would demand both strings and
        # exclude everyone; the one more candidates carry wins.
        got = [s.skill for s in suggest_must_have("SAP Business Partner", VOCAB)]
        assert got == ["SAP"]

    def test_a_skill_almost_nobody_has_is_not_proposed(self) -> None:
        assert suggest_must_have("Rust Entwickler", VOCAB) == []

    def test_what_is_already_recorded_is_not_proposed_again(self) -> None:
        assert suggest_must_have("Java Entwickler", VOCAB, already=["java"]) == []

    def test_a_title_naming_no_technology_proposes_nothing(self) -> None:
        assert suggest_must_have("COC Lead", VOCAB) == []

    def test_the_suggestion_says_why_and_how_many(self) -> None:
        [one] = suggest_must_have("Kubernetes Administrator", VOCAB)
        assert one.evidence == "Der Titel nennt „Kubernetes“"
        assert one.candidates == 20


class TestVocabulary:
    def test_spellings_are_counted_together(self) -> None:
        vocab = normalise_vocabulary(["DevOps", "devops", "DEVOPS", "devops"])
        assert vocab == {"devops": 4}, "the commonest spelling, counted once"

    def test_blank_entries_are_dropped(self) -> None:
        assert normalise_vocabulary(["  ", "", "Java"]) == {"Java": 1}


class TestActiveCriteria:
    def test_a_mandate_without_criteria_reports_none(self) -> None:
        assert active_criteria(Job(title="Backend")) == []

    def test_each_recorded_criterion_is_named(self) -> None:
        job = Job(
            title="Backend",
            requires_work_permit=True,
            location="München",
            location_radius_km=50,
            salary_max=95000,
            must_have_skills=["Java", "WildFly"],
            required_certifications=["AWS"],
        )
        got = active_criteria(job)
        assert got[0] == "Arbeitserlaubnis"
        assert "München ±50 km" in got[1]
        assert "95.000 €" in got[2]
        assert "1 Zertifikat(e)" in got
        assert "2 Muss-Skill(s)" in got

    def test_a_location_without_a_radius_filters_nothing(self) -> None:
        # 13 of 76 mandates have a location and none has a radius, so the
        # location alone must not read as a filter.
        assert active_criteria(Job(title="Backend", location="München")) == []
