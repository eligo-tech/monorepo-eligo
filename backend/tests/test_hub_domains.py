"""An agency's website, as its ads suggest it — `hub/domains.py`, pure.

Measured on 200 live private-recruiter ads (T0, 2026-11-02): 76% carry a
domain, but only about two thirds of those are the agency's own. The rest are
job boards and ATS vendors (finest-jobs.com, hogapage.de, coveto.de,
bewerbung.jobs, recruiting-agents.com) or the CLIENT's site (autobahn.de).

So these are CANDIDATES, ranked with their evidence and never written to a
company record: only the Impressum naming the firm (PR7) verifies one.
"""

from __future__ import annotations

import pytest

from app.domain.hub.domains import (
    domain_candidates,
    extract_domains,
    registrable_domain,
)


def test_a_host_reduces_to_its_registrable_domain() -> None:
    assert registrable_domain("bewerbung.dis-ag.com") == "dis-ag.com"
    assert registrable_domain("WWW.HRMedical.de.") == "hrmedical.de"
    assert registrable_domain("jobs.example.co.uk") == "example.co.uk"
    assert registrable_domain("localhost") is None


def test_domains_come_from_addresses_and_links() -> None:
    text = (
        "Bewerbung an franziska.jessing@dis-ag.com oder online unter "
        "https://www.dis-ag.com/jobs/123. Mehr auf www.twcon.de, Tel 0341 123"
    )
    assert extract_domains(text) == {"dis-ag.com", "twcon.de"}


def test_freemail_and_job_boards_are_never_candidates() -> None:
    text = (
        "info@gmail.com, jobs@finest-jobs.com, https://www.hogapage.de/x, "
        "https://coveto.de/apply, bewerbung.jobs, https://www.stepstone.de/a, "
        "https://www.arbeitsagentur.de/jobsuche"
    )
    assert domain_candidates([("p1", text)], firm_names=["T-F-U Petra Pfrimmer"]) == []


def test_the_firms_own_domain_beats_a_more_frequent_board() -> None:
    ads = [
        ("p1", "Kontakt: m.woltersdorf@woltersdorf-pb.de"),
        ("p2", "Bewerben über https://recruiting.example-ats.de/123"),
        ("p3", "Bewerben über https://recruiting.example-ats.de/456"),
    ]
    best = domain_candidates(ads, firm_names=["Melanie Woltersdorf Personalberatung"])[0]
    assert best["domain"] == "woltersdorf-pb.de"
    assert best["name_match"] is True
    assert best["ads"] == 1 and best["posting_ids"] == ["p1"]


def test_without_a_name_match_the_most_used_domain_leads() -> None:
    ads = [("p1", "x@acme-personal.de"), ("p2", "y@acme-personal.de"), ("p3", "z@other.de")]
    ranked = domain_candidates(ads, firm_names=["Zebra GmbH"])
    assert [c["domain"] for c in ranked] == ["acme-personal.de", "other.de"]
    assert ranked[0]["ads"] == 2


def test_a_domain_named_like_a_known_employer_is_flagged_as_the_client() -> None:
    ranked = domain_candidates(
        [("p1", "Infos unter https://www.autobahn.de/karriere")],
        firm_names=["Die Autobahn GmbH des Bundes"],
        # As the corpus stores it: "Die Autobahn GmbH des Bundes" → "die autobahn …";
        # the employer row for the client is "die autobahn".
        employer_names={"die autobahn"},
    )
    assert ranked[0]["domain"] == "autobahn.de"
    assert ranked[0]["likely_client"] is True


def test_at_most_three_candidates_and_three_example_ads() -> None:
    ads = [(f"p{i}", "a@one.de b@two.de c@three.de d@four.de") for i in range(5)]
    ranked = domain_candidates(ads, firm_names=["X"])
    assert len(ranked) == 3
    assert all(len(c["posting_ids"]) == 3 and c["ads"] == 5 for c in ranked)


def test_one_ad_counts_once_per_domain() -> None:
    ranked = domain_candidates([("p1", "a@acme.de b@acme.de https://acme.de")], firm_names=["Acme"])
    assert ranked[0]["ads"] == 1


def test_a_sentence_glued_to_an_address_does_not_invent_a_domain() -> None:
    assert extract_domains("Mail an info@firma.de.Wir freuen uns") == {"firma.de"}
    assert extract_domains("Mehr auf www.firma.de.Bewerben Sie sich") == {"firma.de"}


def test_an_address_inside_a_link_is_not_a_second_domain() -> None:
    assert extract_domains("https://bewerbung.firma.de/apply?mail=a@other.de") == {"firma.de"}


def test_umlaut_domains_match_the_folded_firm_name() -> None:
    best = domain_candidates([("p1", "x@müller-personal.de")], firm_names=["Müller Personal GmbH"])[0]
    assert best["name_match"] is True


def test_city_and_sector_words_do_not_make_a_name_match() -> None:
    ranked = domain_candidates(
        [("p1", "https://www.charite-berlin.de/x"), ("p2", "https://www.pflegeheim-sonne.de")],
        firm_names=["Berlin Pflege Plus GmbH"],
    )
    assert not any(c["name_match"] for c in ranked)


def test_an_agency_that_also_hires_in_its_own_name_keeps_its_own_site() -> None:
    ranked = domain_candidates(
        [("p1", "x@zebrafink.de")],
        firm_names=["Zebrafink Personal GmbH"],
        employer_names={"zebrafink"},
        own_names={"zebrafink", "zebrafink personal"},
    )
    assert ranked[0]["likely_client"] is False


def test_a_chain_with_thousands_of_ads_keeps_three_examples_and_the_count() -> None:
    ranked = domain_candidates([(f"p{i}", "x@chain-personal.de") for i in range(5000)], firm_names=["Chain Personal"])
    assert ranked[0]["ads"] == 5000 and len(ranked[0]["posting_ids"]) == 3


def test_a_domain_spelling_the_whole_firm_name_matches_even_if_short_or_generic() -> None:
    # From the T0 sample: both are the agencies' own sites.
    assert domain_candidates([("p", "x@dis-ag.com")], firm_names=["DIS AG Germany"])[0]["name_match"]
    assert domain_candidates([("p", "x@bbrecruiting.de")], firm_names=["BBRecruiting Personalberatung"])[0]["name_match"]


def test_a_firm_named_after_its_city_does_not_own_the_citys_domain() -> None:
    assert not domain_candidates([("p", "https://www.berlin.de/x")], firm_names=["Berlin Personal GmbH"])[0]["name_match"]


# ELI-30: job boards measured in 1,000 employers' ads (2026-11-11). Each one's
# Impressum names the board, so it cost a fetch and blocked the second try.
@pytest.mark.parametrize(
    "board",
    [
        "azubi.de", "gute-jobs.de", "ausbildung.de", "studyflix.de", "jobs4us.de",
        "awo-jobs.de", "genau-mein-job.de", "kalaydo.de", "jobblitz.de",
        "jobs-oberlausitz.de", "karriere-suedwestfalen.de", "ams.at", "hokify.at",
        "hamburger-jobanzeiger.de", "wuerzburger-jobanzeiger.de", "aachener-jobanzeiger.de",
    ],
)
def test_a_job_board_is_never_an_employers_website(board: str) -> None:
    ads = [("p1", f"Bewerben Sie sich auf www.{board}/job/123 oder an bewerbung@muster-bau.de")]
    assert [c["domain"] for c in domain_candidates(ads, firm_names=["Muster Bau GmbH"])] == ["muster-bau.de"]


def test_an_employers_own_jobs_domain_stays_a_candidate() -> None:
    # Measured: KANN GmbH Baustoffwerke's own site is kann-jobs.de (verified).
    ads = [("p1", "Mehr unter www.kann-jobs.de")]
    assert [c["domain"] for c in domain_candidates(ads, firm_names=["KANN GmbH Baustoffwerke"])] == ["kann-jobs.de"]
