"""Entity resolution is the hub's identity contract — test it like one.

Every case here is a real shape seen in Bundesagentur data or a German Impressum,
not a synthetic string.
"""

from __future__ import annotations

from app.domain.hub.resolution import (
    extract_legal_form,
    identity_key,
    normalize_company_name,
    normalize_domain,
    normalize_register_number,
    normalize_vat_id,
)


def test_case_and_legal_form_variants_collapse() -> None:
    # The exact pair the BA employer facet returns for one company.
    assert normalize_company_name("ARC-GREENLAB GmbH") == normalize_company_name(
        "ARC-Greenlab GmbH"
    )
    assert normalize_company_name("Muster GmbH & Co. KG") == normalize_company_name(
        "Muster KG"
    )


def test_umlauts_fold_to_their_german_transliteration() -> None:
    # NFKD alone would give "muller", which does not match the "Mueller"
    # spelling the same company uses on its own website.
    assert normalize_company_name("Müller GmbH") == normalize_company_name("Mueller GmbH")
    assert normalize_company_name("Weiß AG") == normalize_company_name("Weiss AG")


def test_nonbreaking_whitespace_is_normalized() -> None:
    # Real BA payloads carry trailing \xa0 in `firma`.
    assert normalize_company_name("zollsoft GmbH \xa0 \xa0") == "zollsoft"


def test_a_name_that_normalizes_away_is_unresolvable_not_empty_match() -> None:
    assert normalize_company_name("GmbH") == ""
    assert normalize_company_name(None) == ""
    # ...and must not become an identity, or every nameless record merges into one.
    assert identity_key(name="GmbH", postal_code="10115") is None


def test_domain_reduces_to_the_registrable_part() -> None:
    assert normalize_domain("https://www.Example.co.uk/karriere?x=1") == "example.co.uk"
    assert normalize_domain("careers.bayoonet.de") == "bayoonet.de"
    assert normalize_domain("bayoonet.de") == "bayoonet.de"
    assert normalize_domain("not a domain") is None
    assert normalize_domain(None) is None


def test_vat_syntax_requires_a_real_country_prefix_and_digits() -> None:
    assert normalize_vat_id("DE 123 456 789") == "DE123456789"
    assert normalize_vat_id("ATU12345678") == "ATU12345678"
    # "NOPE" is two letters + two letters — shape alone must not make it a VAT id.
    assert normalize_vat_id("nope") is None
    assert normalize_vat_id("ZZ123456789") is None
    assert normalize_vat_id("DEABCDEFG") is None


def test_register_number_canonicalizes_or_rejects() -> None:
    assert normalize_register_number("hrb  12345") == "HRB 12345"
    assert normalize_register_number("HRA 987") == "HRA 987"
    assert normalize_register_number("12345") is None


def test_legal_form_is_read_from_the_tail() -> None:
    assert extract_legal_form("Muster GmbH & Co. KG") == "GmbH & Co. KG"
    assert extract_legal_form("Deutsche Bahn AG") == "AG"
    assert extract_legal_form("Zalando SE") == "SE"
    assert extract_legal_form("Some Partnership") is None


def test_ladder_prefers_the_strongest_available_identity() -> None:
    strongest = identity_key(
        name="Muster GmbH",
        vat_id="DE123456789",
        register_court="Amtsgericht Berlin",
        register_number="HRB 1",
        website_domain="muster.de",
        postal_code="10115",
    )
    assert strongest == ("vat", "vat:DE123456789")

    assert identity_key(
        name="Muster GmbH",
        register_court="Amtsgericht Berlin",
        register_number="HRB 1",
        website_domain="muster.de",
    )[0] == "register"

    assert identity_key(name="Muster GmbH", website_domain="muster.de")[0] == "domain"
    assert identity_key(name="Muster GmbH", postal_code="10115")[0] == "name_place"


def test_a_name_without_a_place_does_not_resolve() -> None:
    # "Müller GmbH" alone is not an identity in a country with thousands of them.
    assert identity_key(name="Müller GmbH") is None
