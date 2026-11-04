"""Reading an agency's Impressum — `hub/adapters/impressum.py`, pure.

Fixtures are real Impressum pages captured 2026-11-04 from agency domains in
the T0 sample (robots.txt respected, identified, paced), reduced to their
readable text. Every PERSON is replaced by a placeholder (Max Mustermann,
Erika Musterfrau); for the two sole traders the name-bearing business name,
address, phone and domain too. Company facts of GmbHs — name, register, VAT —
are kept as published.

What the parser must get right is measured on these, not assumed:
  * the value often sits on the NEXT non-empty line ("Geschäftsführer:" / name);
  * VAT with spaces ("DE 314 696 624"), obfuscated mail ("info(at)gecad.de");
  * register forms "HRB-Nr. : 78563 Amtsgericht Köln", "Amtsgericht Bonn HRB
    23195", "HRB 57731 | Amtsgericht Düsseldorf", "HRA 3520 NP";
  * a JavaScript-rendered page (dis-ag.com) has no Impressum text at all.
"""

from __future__ import annotations

import pathlib

import pytest

from app.domain.hub.adapters.impressum import (
    find_impressum_link,
    names_firm,
    parse_impressum,
    safe_url,
)

FX = pathlib.Path(__file__).parent / "fixtures" / "impressum"


def _page(name: str) -> str:
    return (FX / f"{name}.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "fixture, vat, register, court",
    [
        ("gawlitta_hr_de", "DE314696624", ("HRB", "23195"), "Bonn"),
        ("gecad_de", "DE223960681", ("HRB", "45867"), "Bielefeld"),
        ("gs_company_de", "DE286798712", ("HRA", "3520"), "Neuruppin"),
        ("permacon_de", "DE167339196", ("HRB", "211146"), "Lüneburg"),
        ("perse_partner_de", "DE275526440", ("HRB", "23238"), "Wuppertal"),
        ("schmidtundschmidt_eu", "DE236865937", ("HRB", "53427"), "Köln"),
        ("tempton_de", "DE252406571", ("HRB", "28871"), "Essen"),
        ("focussearch_de", None, ("HRB", "78563"), "Köln"),
        ("aurea_gmbh_de", None, ("HRB", "57731"), "Düsseldorf"),
        ("sole_trader_aerzte", "DE987654321", (None, None), None),
        ("sole_trader_personal", "DE123456789", (None, None), None),
    ],
)
def test_company_facts(fixture: str, vat, register, court) -> None:
    facts = parse_impressum(_page(fixture))
    assert facts.is_impressum
    assert facts.vat_id == vat
    assert (facts.register_type, facts.register_number) == register
    assert facts.register_court == court


def test_a_javascript_page_is_not_an_impressum() -> None:
    assert parse_impressum(_page("dis_ag_com")).is_impressum is False


def test_a_malformed_register_is_left_empty_rather_than_guessed() -> None:
    # "Registergericht:A / Registernummer: B 9211" — as published, unusable.
    facts = parse_impressum(_page("dreada_de"))
    assert facts.register_number is None and facts.vat_id == "DE122787794"


def test_phone_and_only_company_mailboxes() -> None:
    gecad = parse_impressum(_page("gecad_de"))
    assert gecad.phone == "+49 5205 1004 280"
    assert gecad.emails == ["info@gecad.de"]  # "info(at)gecad.de" as published
    assert parse_impressum(_page("perse_partner_de")).phone == "0202-26133140"
    # "+ 49 …" as published — the plus is part of the number.
    assert parse_impressum(_page("dreada_de")).phone == "+ 49 221 9258280"
    # A branch mailbox is not a function mailbox — not kept.
    assert parse_impressum(_page("gs_company_de")).emails == []


@pytest.mark.parametrize(
    "fixture, people",
    [
        ("focussearch_de", [("Geschäftsführer", "Max Mustermann")]),
        ("permacon_de", [("Geschäftsführer", "Max Mustermann")]),
        ("gecad_de", [("Geschäftsführer", "Max Mustermann"), ("Geschäftsführer", "Erika Musterfrau")]),
        ("schmidtundschmidt_eu", [("Vertreten durch", "Erika Musterfrau"), ("Vertreten durch", "Max Mustermann")]),
        ("tempton_de", [("Geschäftsführende Gesellschafterin", "Dr. Erika Musterfrau"), ("Geschäftsführender Gesellschafter", "Max Mustermann")]),
        ("sole_trader_aerzte", [("Inhaberin", "Erika Musterfrau")]),
    ],
)
def test_people_are_read_with_their_role(fixture: str, people) -> None:
    # Parsed and tested — NOT stored (PR7 option A, until the Art. 14 answer).
    found = [(p.role, p.name) for p in parse_impressum(_page(fixture)).people]
    assert found[: len(people)] == people
    assert all(p.quote for p in parse_impressum(_page(fixture)).people)


@pytest.mark.parametrize(
    "fixture, firm",
    [
        ("focussearch_de", "FOCUS search GmbH"),
        ("gawlitta_hr_de", "dr. gawlitta (BDU) GmbH"),
        ("twcon_de", "tw.con. GmbH"),
        ("gs_company_de", "GS-COMPANY GmbH & Co. KG"),
        ("permacon_de", "PERMACON GmbH Düsseldorf"),
        ("schmidtundschmidt_eu", "Schmidt & Schmidt Personalberatung GmbH"),
        ("sole_trader_aerzte", "Ärztevermittlung Erika Muster"),
        ("sole_trader_personal", "Erika Beispiel Personalberatung"),
    ],
)
def test_the_impressum_names_the_firm(fixture: str, firm: str) -> None:
    assert names_firm(_page(fixture), [firm])


def test_another_firms_impressum_does_not_verify() -> None:
    assert not names_firm(_page("gecad_de"), ["FOCUS search GmbH"])


def test_a_job_board_mentioning_the_agency_is_not_its_impressum() -> None:
    # The hogapage.de trap from T0: the board's page names the agency it
    # advertises for, but the OPERATOR is the board.
    board = (
        "Jobs\nStellenangebote\nImpressum\nhogapage Media GmbH\nMusterweg 1\n12345 Musterstadt\n"
        "Geschäftsführer: Max Mustermann\nHRB 12345, Amtsgericht Musterstadt\n"
        "USt-IdNr. DE111111111\n\nAktuelle Jobs von BUHL Personal GmbH in Ihrer Region\n" * 1
    )
    assert names_firm(board, ["hogapage Media GmbH"])
    assert not names_firm(board, ["BUHL Personal GmbH - Zentrales Recruiting"])


# --- links: same site only, never an internal address ------------------------


def test_the_impressum_link_is_found_on_the_homepage() -> None:
    html = '<a href="/ueber-uns">Über uns</a> <a href="/kontakt/impressum/">Impressum</a>'
    assert find_impressum_link(html, "https://www.dreada.de/", "dreada.de") == "https://www.dreada.de/kontakt/impressum/"


def test_a_link_to_another_site_is_not_followed() -> None:
    html = '<a href="https://www.e-recht24.de/impressum-generator.html">Impressum</a>'
    assert find_impressum_link(html, "https://www.firma.de/", "firma.de") is None


def test_a_link_to_an_internal_address_is_never_followed() -> None:
    # Measured: bbrecruiting.de links its Impressum to http://localhost:8093/.
    html = '<a href="http://localhost:8093/impressum/">Impressum</a>'
    assert find_impressum_link(html, "https://www.bbrecruiting.de/", "bbrecruiting.de") is None


@pytest.mark.parametrize(
    "url, ok",
    [
        ("https://www.firma.de/impressum", True),
        ("http://firma.de/impressum", True),
        ("https://firma.de.evil.com/impressum", False),
        ("http://localhost/impressum", False),
        ("http://127.0.0.1/impressum", False),
        ("http://10.0.0.5/impressum", False),
        ("http://192.168.1.1/", False),
        ("http://[::1]/", False),
        ("ftp://firma.de/impressum", False),
        ("https://firma.de:8443/impressum", False),
    ],
)
def test_safe_url(url: str, ok: bool) -> None:
    assert safe_url(url, "firma.de") is ok
