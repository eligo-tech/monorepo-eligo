"""An agency's website, as its ads suggest it — `hub/domains.py`, pure.

Measured on 200 live private-recruiter ads (T0, 2026-11-02): 76% carry a
domain, but only about two thirds of those are the agency's own. The rest are
job boards and ATS vendors (finest-jobs.com, hogapage.de, coveto.de,
bewerbung.jobs, recruiting-agents.com) or the CLIENT's site (autobahn.de).

So these are CANDIDATES, ranked with their evidence and never written to a
company record: only the Impressum naming the firm (PR7) verifies one.
"""

from __future__ import annotations

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
        employer_names={"autobahn"},
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
