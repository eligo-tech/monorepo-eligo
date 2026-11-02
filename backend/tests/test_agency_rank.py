"""Agency or client? And how good a lead? — `hub/agency_rank.py`, pure.

A private-recruiter ad names ONE firm, and the source has no field saying
whether it is the agency or the agency's client. Measured 2026-11-02 on 600
live pav ads (142 firms): deterministic signals mark 82% as agencies; of the
rest, about half are clients (KHS, SoftwareOne, Tipico, Stadt Frankfurt).

The cases below are real firms from that sample. Plain code decides, every
verdict lists its reasons (CLAUDE.md: deterministic, evidence-backed).
"""

from __future__ import annotations

import datetime as dt

from app.domain.hub.agency_rank import (
    AGENCY,
    CHAIN_OPEN_POSTINGS,
    CLIENT,
    UNCLEAR,
    AgencyFacts,
    classify,
    group_key,
    score,
    text_signals,
)

NOW = dt.datetime(2026, 11, 2, tzinfo=dt.UTC)


def _facts(**kw) -> AgencyFacts:
    base = dict(group_key="x", names=["X"], open_postings=3)
    return AgencyFacts(**{**base, **kw})


# --- one agency, many branches ---------------------------------------------


def test_branches_fold_into_one_agency() -> None:
    assert group_key("OPTIPER GmbH - Niederlassung Meiningen") == group_key("OPTIPER GmbH - Niederlassung Plauen") == "optiper"
    assert group_key("Brunel GmbH NL Essen") == group_key("Brunel GmbH NL Braunschweig") == "brunel"
    assert group_key("Piening GmbH (Saarbrücken)") == "piening"
    assert group_key("LOCAL.WORK Service GmbH Standort Dresden") == "local work service"


def test_different_firms_stay_apart() -> None:
    assert group_key("DIS AG Germany") != group_key("expertum GmbH")


# --- what the ad text says -------------------------------------------------


def test_the_client_phrase_says_the_advertiser_is_an_agency() -> None:
    for text in (
        "Unser Mandant ist ein international führender Konzern",
        "Für unseren Kunden, ein Unternehmen aus der Windenergiebranche, suchen wir",
        "Im Auftrag unseres Kunden besetzen wir",
    ):
        assert "client_phrase" in text_signals(text, "Firma")[0], text


def test_customer_service_is_not_a_client_phrase() -> None:
    # The loose form matched employers talking about their own customers.
    for text in (
        "Für unser Kundendienstteam suchen wir einen Kundendiensttechniker",
        "unsere Kunden auf unseren Anlagen schätzen unseren Pioniergeist",
        "Wir bieten unseren Kunden erstklassigen Service",
        "im Auftrag der Deutschen Bahn warten wir Weichen",
        "im Auftrag des Landes betreiben wir Schulen",
    ):
        assert "client_phrase" not in text_signals(text, "KHS GmbH")[0], text


def test_a_contact_address_at_the_firms_own_domain() -> None:
    signals, domains = text_signals(
        "weitere Informationen bei: p.lanzillotta@lehrcare.de", "LehrCare GmbH"
    )
    assert "mail_domain" in signals and domains == {"lehrcare.de"}


def test_freemail_and_foreign_domains_say_nothing() -> None:
    assert text_signals("bewerbung@gmail.com", "Gmail Personal")[0] == set()
    assert text_signals("jobs@persy.jobs", "LehrCare GmbH")[0] == set()


# --- the verdict -------------------------------------------------------------


def test_a_staffing_name_is_an_agency() -> None:
    for name in ("Jürgen Tausch Personnel Service", "KA Resources", "MB Beratung", "persoperm GmbH", "ROSA Experts AG & Co KG"):
        verdict, reasons = classify(_facts(names=[name]))
        assert verdict == AGENCY, name
        assert reasons[0]["code"] == "name"


def test_an_employer_already_in_the_corpus_is_a_client() -> None:
    verdict, reasons = classify(_facts(names=["KHS GmbH"], employer_overlap=True))
    assert verdict == CLIENT
    assert [r["code"] for r in reasons] == ["also_employer"]


def test_a_public_body_is_a_client() -> None:
    verdict, _ = classify(_facts(names=["Stadt Frankfurt am Main - Der Magistrat - Branddirektion"]))
    assert verdict == CLIENT


def test_conflicting_signals_are_unclear_not_guessed() -> None:
    verdict, reasons = classify(
        _facts(names=["Hays AG"], employer_overlap=True, phrase_postings=4)
    )
    assert verdict == UNCLEAR
    assert {r["code"] for r in reasons} == {"client_phrase", "also_employer"}


def test_no_signal_at_all_is_unclear() -> None:
    assert classify(_facts(names=["Freedocs GmbH"]))[0] == UNCLEAR


def test_posting_across_many_fields_is_an_agency_signal() -> None:
    verdict, reasons = classify(_facts(names=["tw.con. GmbH"], fields={"Medizin": 3, "IT": 2, "Bau": 1}))
    assert verdict == AGENCY and reasons[0]["evidence"]["fields"] == 3


# --- the ranking --------------------------------------------------------------


def test_a_small_active_sole_trader_ranks_above_a_mid_size_firm() -> None:
    small, why = score(_facts(open_postings=3, sole_trader=True, new_7d=2, new_28d=3))
    mid, _ = score(_facts(open_postings=40))
    assert small > mid
    assert {r["code"] for r in why} == {"size", "sole_trader", "new_7d", "new_28d"}


def test_every_point_carries_its_evidence() -> None:
    _, why = score(_facts(open_postings=4, recruiter_roles=1, recruiter_posting_ids=["p1"]))
    growth = next(r for r in why if r["code"] == "hiring_recruiters")
    assert growth["evidence"] == {"postings": 1, "posting_ids": ["p1"]}
    assert all("points" in r for r in why)


def test_a_chain_scores_nothing_for_size() -> None:
    _, why = score(_facts(open_postings=CHAIN_OPEN_POSTINGS + 1))
    assert "size" not in {r["code"] for r in why}


def test_a_generic_first_word_does_not_claim_someone_elses_domain() -> None:
    assert text_signals("jobs@personalwerk.de", "Personal Partner GmbH")[0] == set()
    assert "mail_domain" in text_signals("a@personalpartner.de", "Personal Partner GmbH")[0]


def test_a_leading_parenthesis_does_not_merge_unrelated_agencies() -> None:
    assert group_key("(BAP) Personal GmbH") != group_key("(XYZ) Personal GmbH")
