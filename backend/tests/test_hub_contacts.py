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


# --- review of ELI-22 PR 1 (#231): recall the precision pass must not cost ---


@pytest.mark.parametrize(
    "text",
    [
        "Bei Fragen wenden Sie sich bitte an die nachfolgend genannte Ansprechpartnerin "
        "Frau Katrin Wolter, Tel. 0395 5442681.",
        "Fragen beantwortet Frau Katrin Wolter unter 0395 5442681, Fahrtkosten werden übernommen.",
        "Frau Katrin Wolter, die unser Team 2019 gegründet hat, freut sich auf Ihre Bewerbung.",
        "Ihr Ansprechpartner ist Frau Katrin Wolter, die den Betrieb in dritter Generation führt.",
    ],
)
def test_a_contact_sentence_is_not_company_history(text: str) -> None:
    assert one(text).last_name == "Wolter"


def test_history_survives_a_title_dot_in_the_sentence() -> None:
    assert extract_contacts(
        "Zum 1.1. suchen wir zur Nachfolge unserer langjährigen Chefärzte Herrn Dr. Udo "
        "Brenner und Herrn Dr. Jan Kluge eine Leitung."
    ) == []


@pytest.mark.parametrize("surname", ["Hering", "Gehring", "Döring", "Kaufer", "Salon"])
def test_a_surname_shaped_like_a_street_or_business_is_kept(surname: str) -> None:
    c = one(f"Ihr Ansprechpartner: Herr Thomas {surname}, Tel. 0395 5442681")
    assert (c.first_name, c.last_name) == ("Thomas", surname)


def test_a_street_after_a_full_name_is_still_cut() -> None:
    c = one("Frau Sophie Bennicke Ehrenbachstraße 4, 10115 Berlin")
    assert c.full_name == "Sophie Bennicke"


@pytest.mark.parametrize(
    "number", ["0711 2525 0", "089 12345 0", "0049 800 1234567", "+43 800 123456"]
)
def test_more_switchboard_shapes(number: str) -> None:
    assert one(f"Frau Katrin Wolter\nTelefon {number}\n").phone_kind == "switchboard"


def test_a_lone_street_word_before_a_house_number_is_an_address() -> None:
    c = one("Beispiel Service GmbH Herr Jäger Kreuzberger Ring 46a 65205 Wiesbaden")
    assert "Ring" not in c.full_name


# --- ELI-22 parser v2: defects seen in the first prod fill (2026-11-10) -------


def test_a_website_heading_under_a_contact_heading_is_not_a_person() -> None:
    assert extract_contacts("Ihr Kontakt\nÜber Uns\nWir sind ein Familienbetrieb.") == []


def test_an_upper_case_surname_is_part_of_the_name() -> None:
    c = one("Bewerbungen nach telefonischer Terminvereinbarung mit Herrn Felix BRANDNER")
    assert (c.first_name, c.last_name) == ("Felix", "BRANDNER")


def test_an_upper_case_surname_alone_after_the_salutation() -> None:
    c = one("Bewerbungen bitte per Mail z.H. an Herrn NIKOLAIDIS. Kontakt: Hotel Linde")
    assert (c.salutation, c.last_name) == ("Herr", "NIKOLAIDIS")


def test_upper_case_company_words_are_not_a_surname() -> None:
    assert extract_contacts("Herr GMBH UND CO KG") == []


@pytest.mark.parametrize("title", ["Dr. med.", "Dr. med. dent.", "Dr. rer. nat.", "Dr. jur.", "Dr. phil."])
def test_a_medical_or_academic_title_is_not_the_name(title: str) -> None:
    c = one(f"Für Rückfragen steht Ihnen gern Frau {title} Anna Brenner zur Verfügung.")
    assert (c.first_name, c.last_name) == ("Anna", "Brenner")


def test_a_title_alone_is_not_a_name() -> None:
    assert extract_contacts("Für Rückfragen steht Ihnen Frau Dr. gern zur Verfügung.") == []


@pytest.mark.parametrize(
    "text",
    [
        "Kontakt\nNORDA Lebensmittelfilialbetrieb Stiftung & Co. KG",
        "EDEKA Breitenbach",
        "Kontakt:\nTRAGLE Car Taxi - und Mietwagenunternehmen GmbH",
        "AWO Landesverband Sachsen-Anhalt e.V.",
    ],
)
def test_upper_case_words_without_a_salutation_are_not_a_person(text: str) -> None:
    assert extract_contacts(text) == []


@pytest.mark.parametrize(
    ("text", "first", "last"),
    [
        ("Bei Fragen können Sie sich gerne an Frau Mag.a Christine Reiter wenden.", "Christine", "Reiter"),
        ("z. H. Frau Mag. (FH) Saskia Knauer", "Saskia", "Knauer"),
        ("Terminvereinbarung mit Frau Dr.in Michaela Gruber, Tel. 03125/2355", "Michaela", "Gruber"),
        ("Frau Dr.rer.nat. Laura Fröhner", "Laura", "Fröhner"),
        ("Herr Dr.med. Dirk Arnold", "Dirk", "Arnold"),
        ("von dem Dekan, Herrn Prof. Dr.-Ing. Thomas Keller, beantwortet", "Thomas", "Keller"),
        ("Herr Landrat Dr. Richard Sieber", "Richard", "Sieber"),
    ],
)
def test_more_title_forms(text: str, first: str, last: str) -> None:
    c = one(text)
    assert (c.first_name, c.last_name) == (first, last)


def test_a_postnominal_is_not_the_surname() -> None:
    c = one("Ihr Ansprechpartner: Herr Heinz Hierl MAS, Bereichsleitung, T: 0732/7897-24967")
    assert (c.first_name, c.last_name) == ("Heinz", "Hierl")


def test_an_upper_case_ordinary_word_after_a_surname_is_not_the_name() -> None:
    c = one("Persönlich bei Frau Steiner NACH telefonischer Terminvereinbarung unter 0664/420 69 73")
    assert c.full_name == "Steiner"


@pytest.mark.parametrize(
    ("text", "first", "last"),
    [
        ("Fragen beantwortet Ihnen \nFrau Oberärztin Dr. Gabriele Hartl, Tel. +43 5522 303", "Gabriele", "Hartl"),
        ("unter Leitung von Herrn Chefarzt Privatdozent Dr. Jonas Diehm.", "Jonas", "Diehm"),
    ],
)
def test_a_medical_rank_before_the_name_is_the_role(text: str, first: str, last: str) -> None:
    c = one(text)
    assert (c.first_name, c.last_name) == (first, last)


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("Ihr Ansprechpartner: Michael Schliwa Energie Südbayern GmbH Ungsteiner Straße 31", "Michael Schliwa"),
        ("Ansprechpartnerin: Jana Hasan Randstad Austria GmbH Vogelweiderstraße 33", "Jana Hasan"),
        ("Beispiel GmbH\nFrau Mirèio Rath da Silva", "Mirèio Rath da Silva"),
    ],
)
def test_a_company_after_the_name_does_not_cost_the_name(text: str, name: str) -> None:
    assert one(text).full_name == name


def test_the_rank_words_before_a_name_are_its_role() -> None:
    c = one("Sie bitte an Herrn Oberlandeskirchenrat Dr. Thilo Daniel, Tel. (0351) 4692")
    assert (c.first_name, c.last_name, c.role_title) == ("Thilo", "Daniel", "Oberlandeskirchenrat")


@pytest.mark.parametrize("text", ["Kontakt:\nHuman Resources", "Herrn Rabko DIENSTGEBER: Beispiel GmbH"])
def test_department_and_label_words_are_not_a_name(text: str) -> None:
    assert all("Resources" not in c.full_name and "DIENSTGEBER" not in c.full_name for c in extract_contacts(text))


# --- ELI-25: a name without "Frau"/"Herr" and without "Label:" ------------
# Measured 2026-11-11 on 1/16 of the open corpus: about 30% of the ads that
# name a person wrote the name bare, in a sentence or under a label without a
# colon, and v2 found nobody. A bare name is only taken with evidence: a
# contact phrase right before it and a phone or e-mail right after it, or a
# personal e-mail that spells the same name.


@pytest.mark.parametrize(
    ("text", "first", "last", "phone"),
    [
        (
            "Home-Office-Möglichkeit Kontakt\nFür Fragen steht Janet Jürgens telefonisch unter +49 5491 666 2834\n"
            "oder auch über WhatsApp unter +49 151 51446810 gerne zur Verfügung.",
            "Janet", "Jürgens", "+49 5491 666 2834",
        ),
        (
            "Kontakt:  Für Rückfragen steht ihnen gerne Beate Bremauer unter Tel. 089/45832-146 zur Verfügung.",
            "Beate", "Bremauer", "089/45832-146",
        ),
        (
            "Fragen zur Stellenausschreibung beantwortet Ihnen Doreen Hennig aus unserer Personalabteilung unter 0151/18957922.",
            "Doreen", "Hennig", "0151/18957922",
        ),
        (
            "Bei Fragen melde dich gerne bei: Céline Ortz (HR Manager) Telefon: +49 711 1640 1254 Mail: karriere@bw-p.de",
            "Céline", "Ortz", "+49 711 1640 1254",
        ),
        (
            "Ansprechpartner Lennart Stutz Leiter der Vertriebsorganisation Tel. 0160 96300257",
            "Lennart", "Stutz", "0160 96300257",
        ),
        (
            "IHR KONTAKT Tobias Neugebauer Bereichsleiter Personalvermittlung +49 (0) 69 27 29 881 – 15 bewerbung@teic.de",
            "Tobias", "Neugebauer", None,
        ),
        (
            "Für Rückfragen steht Dir gerne Ursula Friedsam unter +49 8651-71511-0 zur Verfügung.",
            "Ursula", "Friedsam", "+49 8651-71511-0",
        ),
        (
            "Zur Stelle wende Dich telefonisch an Monika Schmidt, Einrichtungsleitung Evangelischer Beratungsdienst, unter 089 / 287 78 69 - 0",
            "Monika", "Schmidt", None,
        ),
    ],
)
def test_a_bare_name_in_a_contact_phrase_with_a_number(text: str, first: str, last: str, phone: str | None) -> None:
    c = one(text)
    assert (c.salutation, c.first_name, c.last_name) == (None, first, last)
    if phone:
        assert c.phone == phone
    else:
        assert c.phone


@pytest.mark.parametrize(
    ("text", "first", "last", "email"),
    [
        (
            "Ansprechpartner  ### Tanja Hilt  t.hilt@globus.net  +49(6851)803 105",
            "Tanja", "Hilt", "t.hilt@globus.net",
        ),
        (
            "ERGO Beratung und Vertrieb AG Mirjam Barthel - Personalberaterin mirjam.barthel@ergo.de 0155-65793268",
            "Mirjam", "Barthel", "mirjam.barthel@ergo.de",
        ),
        (
            "Bewerbungen bitte an Stephanie Christ (Beauftragte Aus- und Weiterbildung) s.christ@schwitzers.com",
            "Stephanie", "Christ", "s.christ@schwitzers.com",
        ),
        (
            "Kontakt zu uns Ann-Christin Göttsch ann-christin.goettsch@dis-ag.com +49 431 7299 0846",
            "Ann-Christin", "Göttsch", "ann-christin.goettsch@dis-ag.com",
        ),
    ],
)
def test_a_bare_name_spelled_by_its_own_email(text: str, first: str, last: str, email: str) -> None:
    c = one(text)
    assert (c.salutation, c.first_name, c.last_name, c.email) == (None, first, last, email)


@pytest.mark.parametrize(
    "text",
    [
        "📞 Sie haben noch Fragen? Melden Sie sich gerne telefonisch unter 02507 - 981 729 oder per Mail an bewerbung@x.de",
        "Nehmen Sie bei Fragen gerne zu uns Kontakt auf!  Tel.: 035265 649740 Mail: personal-rg@x.de",
        "Dein Ansprechpartner Recruiting Team 069-405625-427 Referenznummer: KP1",
        "Hörmann KG Verkaufsgesellschaft Horststraße 2-4 33803 Steinhagen Telefon +49 5204 915-3042",
        "PARTZSCH Spezialdrähte GmbH Personalabteilung Ossig Nr. 9 D-04741 Roßwein OT Ossig Telefon +49(0) 3431 7166-158",
        "Für Rückfragen stehen wir Ihnen gerne unter 0160 / 97996011 zur Verfügung.",
        "Kontakt zu uns Chemnitz Office & Management chemnitz-office@dis-ag.com +493716905730",
        "In deiner REWE Christian Chauviere oHG sorgst du dafür, dass sich deine Kund:innen wohlfühlen.",
        "Kontakt Personalabteilung Klinikum Nord Telefon 0911 398-0",
    ],
)
def test_no_bare_name_without_a_person(text: str) -> None:
    assert extract_contacts(text) == []


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("Kontakt Ihre Ansprechperson Lena Fischer\nTel. 0211/506699-26 Lena.Fischer@permacon.de", "Lena Fischer"),
        ("Wenn Du noch Fragen hast, wende Dich gerne an: Laura Marie Köster und Matthias Biss Tel. 04342 8882-0", "Laura Marie Köster"),
        ("Bei Fragen melden Sie sich gerne bei Yvonne van Pinxteren in der Recruiting-Abteilung unter 089 278 131 49.", "Yvonne van Pinxteren"),
    ],
)
def test_a_bare_name_is_not_cut_short(text: str, name: str) -> None:
    assert extract_contacts(text)[0].full_name == name


@pytest.mark.parametrize(
    "text",
    [
        "Kontaktdaten: Kreis Unna: 02303/2807111 Kreis-unna.berufsberatung@arbeitsagentur.de",
        "Gerne steht Ihnen die Leitung der Gebäudereinigung unter der Telefonnummer 0151/15171624 zur Verfügung.",
        "Für Fragen stehen wir Ihnen gern zur Verfügung: Zu den Aufgabeninhalten der Stelle (Tel. 0351/48 46 120)",
    ],
)
def test_a_place_or_a_unit_is_not_a_bare_name(text: str) -> None:
    assert extract_contacts(text) == []


def test_a_bare_name_with_an_unknown_first_name_is_left_to_the_model() -> None:
    # The rules take a bare name only if its first name is in first_names.txt.
    # "Hussien" is not; the AI fallback reads ads like this one.
    text = "Ihre Bewerbung richten Sie bitte direkt an Hussien Bader: h.bader@apotheke-am-hit.de"
    assert extract_contacts(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "Bei Rückfragen steht Ihnen Kita Ruth-Grohe-Haus unter 02372/10485 kita-ruth-grohe-haus@awo-ha-mk.de zur Verfügung",
        "Für Fragen steht Ihnen der Sachgebiet Pädagogik unter 04791 930-2830 zur Verfügung.",
        "Ihre Bewerbungsunterlagen schicken Sie bitte per Mail an erdbau.schinagl@gmail.com Erdbau Schinagl",
    ],
)
def test_a_unit_that_looks_like_a_name_is_not_one(text: str) -> None:
    assert extract_contacts(text) == []


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("Ansprechpartner: Alexander Kreis, Tel. +49 (0)160-99 80 35 48, alexander.kreis@ruhr-placement.com", "Alexander Kreis"),
        ("Ansprechpartnerin: Jennifer Schweizer Auskunft unter 061 733 0770", "Jennifer Schweizer"),
        ("Ansprechpartnerin: Micaela Iozzo Bewerbungen bitte an jobs@example.ch", "Micaela Iozzo"),
        ("Ansprechpartnerin: Kim Isabell Schönenberger und Team", "Kim Isabell Schönenberger"),
        ("Ein Fahrtgeldzuschuss. Ansprechpartner Linda Schwenke Senior Recruiter 0211 302061-276", "Linda Schwenke"),
    ],
)
def test_a_third_name_part_only_after_two_first_names_or_a_particle(text: str, name: str) -> None:
    assert extract_contacts(text)[0].full_name == name


# --- ELI-25 safety net: contact data with no recognised name ---------------
# A phone or personal e-mail in an ad must never be lost because the parser
# could not name its owner. `unnamed_reach` returns what no named person in
# the same text claims: the company card shows it as "from the ad, no name
# recognised".

from app.domain.hub.contacts import unnamed_reach  # noqa: E402


def test_a_number_nobody_claims_is_kept() -> None:
    text = "Ihre Bewerbung richten Sie bitte direkt an Hussien Bader: h.bader@apotheke-am-hit.de oder 0711 123456"
    reach = unnamed_reach(text)
    assert [(r.kind, r.value) for r in reach] == [("email", "h.bader@apotheke-am-hit.de"), ("phone", "0711 123456")]
    assert "Hussien Bader" in reach[0].quote


def test_a_named_persons_number_is_not_repeated() -> None:
    text = "Für Fragen steht Janet Jürgens telefonisch unter +49 5491 666 2834 zur Verfügung. Zentrale: 05491 6660"
    assert [(r.kind, r.value) for r in unnamed_reach(text)] == [("phone", "05491 6660")]


def test_a_company_mailbox_and_a_fax_are_not_unnamed_reach() -> None:
    text = "Bewerbungen an bewerbung@firma.de, Fax 0711 99887766. Tel. 0711 998877-0"
    assert [(r.kind, r.value, r.phone_kind) for r in unnamed_reach(text)] == [("phone", "0711 998877-0", "switchboard")]


def test_no_reach_in_an_empty_text() -> None:
    assert unnamed_reach(None) == [] and unnamed_reach("") == []


@pytest.mark.parametrize(
    ("text", "email"),
    [
        ("Unsere E-Mail-Adresse lautet: ag@riepe.comSie erreichen uns auch telefonisch", "ag@riepe.com"),
        ("an email to our Inclusion Officer at inclusion@deliveryhero.cominclude it in your", "inclusion@deliveryhero.com"),
        ("per Mail an m.arndt@fine-wall-berlin.de.", "m.arndt@fine-wall-berlin.de"),
    ],
)
def test_an_email_glued_to_the_next_word_is_cut_at_its_domain(text: str, email: str) -> None:
    assert [r.value for r in unnamed_reach(text) if r.kind == "email"] == [email]
