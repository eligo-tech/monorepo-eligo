"""Named contacts in public ad texts — extraction, not judgement.

Every case below is a real contact block from a Bundesagentur ad (Sept 2026),
kept verbatim including its line breaks and markdown, because those are what
the parser actually has to survive. The negative cases are the false positives
a naive "Frau|Herr|Ansprechpartner + capital word" pattern produces on the same
corpus.
"""

from __future__ import annotations

import pytest

from app.domain.hub.contacts import company_mailboxes, extract_contacts, person_key


def one(text: str):
    found = extract_contacts(text)
    assert len(found) == 1, found
    return found[0]


def test_salutation_name_role_and_phone() -> None:
    c = one(
        "Für Rückfragen wenden Sie sich bitte an:\n\n"
        "Frau Katrin Wolter (Pflegedienstleitung)\nTelefon 0395 5442681\n"
    )
    assert (c.salutation, c.first_name, c.last_name) == ("Frau", "Katrin", "Wolter")
    assert c.role_title == "Pflegedienstleitung"
    assert c.phone == "0395 5442681"
    assert "Katrin Wolter" in c.quote


def test_personal_email_is_attributed_by_surname() -> None:
    c = one(
        "Herrn Thorsten Grümbel\n57074 Siegen\nRosterstraße 37\n\n"
        "Telefon: 0271/33583-0\nE-Mail: thorsten.gruembel@gehre-treuhand.de\n"
    )
    assert c.email == "thorsten.gruembel@gehre-treuhand.de"  # ü ↔ ue


def test_generic_mailbox_is_not_a_persons_email() -> None:
    text = (
        "Wir freuen uns auf Ihre Bewerbung an bewerbungen@hacker-partner.de\n\n"
        "Ihre Ansprechpartnerin: Christiane Weigmann\n"
    )
    c = one(text)
    assert c.full_name == "Christiane Weigmann"
    assert c.email is None
    assert company_mailboxes(text) == ["bewerbungen@hacker-partner.de"]


def test_email_is_not_borrowed_from_a_colleague_with_the_same_first_name() -> None:
    found = extract_contacts(
        "Frau Susanne Brendler, Leiterin Abteilung Verwaltung, "
        "susanne.brendler@smns-bw.de\n\nAnsprechpartner:\nSusanne Treu\n"
    )
    by_name = {c.last_name: c for c in found}
    assert by_name["Brendler"].email == "susanne.brendler@smns-bw.de"
    assert by_name["Treu"].email is None


def test_role_before_the_name() -> None:
    c = one(
        "Für erste Fragen steht Dir unsere Pflegedirektorin Frau Christina Lemke "
        "gerne unter 03844 880899 zur Verfügung."
    )
    assert c.role_title == "Pflegedirektorin"
    assert c.phone == "03844 880899"


def test_role_before_the_name_drops_separators() -> None:
    c = one("Sto SE & Co. KGaA\nBereich Personal - Frau Sophie Bennicke\nTel. +49 7744 57 1660")
    assert c.role_title == "Bereich Personal"


def test_role_word_glued_to_the_name_is_split_off() -> None:
    c = one("im Stadtamt Perg, Frau Stadtamtsleiterin Ulrike Edtbauer, MPA, 1. Stock")
    assert c.full_name == "Ulrike Edtbauer"
    assert c.role_title == "Stadtamtsleiterin"


def test_surname_only_is_the_formal_german_form() -> None:
    c = one(
        "Als Ansprechperson steht Ihnen für inhaltliche Fragen aus dem "
        "Fachbereich Soziales Herr Trippner (02323/16-3221) zur Verfügung."
    )
    assert (c.first_name, c.last_name) == (None, "Trippner")
    assert c.phone == "02323/16-3221"


def test_academic_titles_are_kept() -> None:
    c = one("Für Rückfragen steht Ihnen Herr Dr. Benjamin Schmidt\n\nunter [0951-70085-0](tel:0951700850) zur Verfügung.")
    assert c.full_name == "Dr. Benjamin Schmidt"
    assert c.last_name == "Schmidt"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The street on the next line is not part of the name.
        ("Frau Sophie Bennicke\nEhrenbachstraße 1\n79780 Stühlingen", "Sophie Bennicke"),
        # A trailing department word is not a surname.
        ("Herr Julian Köppel Recruiting\nTel. +49 08654 7707 0", "Julian Köppel"),
        # A surname wrapped onto the next line is.
        ("Geschäftsstelle Frau Anna-Lena\nHorn (Recruiterin) Böhmerstraße 11", "Anna-Lena Horn"),
        # A particle that led into a department is dropped.
        ("wenden Sie sich an Frau Ringleben vom Personaleinsatzmanagement", "Ringleben"),
    ],
)
def test_name_boundaries(text: str, expected: str) -> None:
    assert one(text).full_name == expected


def test_first_name_is_recovered_from_a_contact_mention() -> None:
    c = one(
        "unterstützt mit unserer Ansprechpartnerin Jutta Weber unterstützt. "
        "Frau Weber wird deine Bewerbung in unserem Auftrag erhalten."
    )
    assert c.full_name == "Jutta Weber"


def test_first_name_is_not_borrowed_from_another_person() -> None:
    # The practice is Dr. Gerald Büger; the contact is a Frau Büger.
    c = one("Dr. iur. Gerald Büger\n\nBewerbungen bitte an Frau Büger, s.bueger@bueger.at")
    assert c.full_name == "Büger"
    assert c.email == "s.bueger@bueger.at"


@pytest.mark.parametrize(
    "text",
    [
        # A duty in a task list, not a person — the commonest false positive.
        "Du bist Ansprechpartner für Bewohner/innen, Kunden/innen und Angehörige",
        "Ansprechpartner:in für Patient:innen, Angehörige und Kolleg:innen",
        # A company after a contact label.
        "Ansprechpartnerin:\nVision Consulting GmbH\nTel. 030 / 20 60 67",
        # A sentence after a contact label.
        "Kontakt:\nWenn Sie Spaß an der Arbeit haben, melden Sie sich.",
        # Placeholder names.
        "Anrede: Frau Divers Divers",
        # A bare word after a label may be a department.
        "Kontakt:\nPersonalabteilung\n",
    ],
)
def test_not_a_person(text: str) -> None:
    assert extract_contacts(text) == []


def test_same_person_twice_in_one_ad_is_one_contact() -> None:
    found = extract_contacts(
        "Ansprechpartnerin: Jutta Dziobek\nE-Mail: dz@x.de\n\n"
        "Frau Dziobek freut sich auf Ihre Bewerbung."
    )
    assert [c.full_name for c in found] == ["Jutta Dziobek"]


def test_person_key_merges_formal_and_full_mentions() -> None:
    assert person_key(None, "Bennicke") == person_key("Sophie", "Bennicke")
    assert person_key("Jürgen", "Stöckel") == person_key(None, "Stoeckel")


def test_empty_input() -> None:
    assert extract_contacts(None) == []
    assert extract_contacts("") == []
    assert company_mailboxes(None) == []


# --------------------------------------------------------------------------
# ELI-22 precision pass — defects found in a prod spot-check (2026-11-10) of
# 38 extracted persons, before contacts are stored nightly. Shapes are the
# real ones; the names are invented.
# --------------------------------------------------------------------------


def test_former_owner_in_company_history_is_not_a_contact() -> None:
    assert extract_contacts(
        "Seit 2015 hat nun Herr Torsten Kaltwasser die erfolgreich geführte "
        "Traditionsfirma von Herrn Olaf Brenner übernommen."
    ) == []


def test_business_after_contact_label_is_not_a_person() -> None:
    assert extract_contacts("Kontakt:\nBäckerei Sonnenschein\nHauptstraße 1") == []


def test_austrian_master_title_is_not_the_name() -> None:
    c = one(
        "Bewerben Sie sich: office@beispiel.at BEISPIEL Herr Mst. Richard Kranzl "
        "Lindenstraße 17b 4400 Steyr"
    )
    assert (c.first_name, c.last_name) == ("Richard", "Kranzl")


def test_surname_that_is_also_a_street_suffix_is_kept() -> None:
    c = one(
        "Für Fragen rund um Ihre Bewerbung steht Ihnen Herr Marco Damm gerne "
        "telefonisch unter +49 2323 1383111 zur Verfügung."
    )
    assert (c.first_name, c.last_name) == ("Marco", "Damm")


def test_trailing_business_word_is_not_part_of_the_name() -> None:
    found = extract_contacts(
        "Bitte bewerben Sie sich bei Herrn Peter Lang oder Frau Cordula Steiner "
        "Gasthof - Krone Grazerstraße 36 8403 Lebring Tel. Nr: 03182/2521"
    )
    assert {c.full_name for c in found} == {"Peter Lang", "Cordula Steiner"}


@pytest.mark.parametrize(
    ("raw", "first"),
    [
        ("0800 / 4007766 0800 / 4007767", "0800 / 4007766"),
        ("0531 3800849 0531 3800850", "0531 3800849"),
        ("0921 72612-38 / 01512 3456789", "0921 72612-38"),
    ],
)
def test_two_numbers_in_a_row_are_not_one_phone(raw: str, first: str) -> None:
    assert one(f"Frau Anna Weidner\nTelefon {raw}\n").phone == first


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Frau Katrin Wolter\nTelefon 0395 5442681\n", "direct"),
        ("Herrn Thorsten Grümbel\nTelefon: 0271/33583-0\n", "switchboard"),
        ("Frau Anna Weidner\nHotline 0800 / 4007766\n", "switchboard"),
        ("Frau Katrin Wolter\n", None),
    ],
)
def test_phone_kind_says_whether_it_reaches_the_person(text: str, kind: str | None) -> None:
    assert one(text).phone_kind == kind


@pytest.mark.parametrize(
    "number",
    [
        "+41 41 553 01 65",
        "02331/33 00 481",
        "030 9210 952 00",
        "+49 791 946 009 111",
        "+49 (0)160 99 80 07 17",
        "+49 (0) 7231 778 06 50",
        "+49 151 571 579 07",
        "0699/153 322 04",
    ],
)
def test_digit_groups_starting_with_zero_stay_one_number(number: str) -> None:
    # Regression guard for the two-numbers split: found by running the old
    # and new parser over 15k prod ads before shipping.
    assert one(f"Frau Nicole Brandt\nTelefon {number}\n").phone == number


def test_a_takeover_offer_to_the_candidate_is_not_company_history() -> None:
    c = one(
        "* Perspektive auf eine Übernahme ins Stammpersonal * Arbeitsort: Wels "
        "Kontakt: Sabine Pohl Geschäftsführerin BEISPIEL GmbH"
    )
    assert c.full_name == "Sabine Pohl"


def test_noch_fragen_is_not_a_name() -> None:
    assert extract_contacts("Ansprechpartner:\nNoch Fragen\n030 9210 952 00") == []
