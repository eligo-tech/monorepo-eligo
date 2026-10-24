"""Reading a job advert into a Suchprofil (ELI-6).

Three things these pin, in order of how badly they would hurt:

1. **Reading an advert creates nothing.** `must_have_skills` are hard
   filters — they exclude people — so an extractor that could write a
   mandate would be a model deciding who never gets seen.
2. **The fetcher cannot be aimed inside.** A pasted URL is attacker-supplied
   the moment somebody shares a "job advert" link, and a server that fetches
   `http://169.254.169.254/` on request is an SSRF with a nice form on top.
3. **Nothing is invented.** An advert with no salary must produce no salary;
   a blank field is obviously blank, where a plausible wrong band is not.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.jobs import jobspec
from app.domain.jobs.jobspec.heuristic import HeuristicJobSpecExtractor

API = "/api/v1/jobs"

# The advert from ELI-6, trimmed to what a parser sees.
ADVERT = """
IT-Administrator (m/w/d) OT / produktionsnahe IT

Linde + Wiemann SE & Co. KG
Standort: Dillenburg
35683 Dillenburg, Hessen

Ihre Aufgaben: Administration, Planung und Optimierung des globalen Remote
Maintenance Systems, der Shopfloor Devices und des unternehmensweiten Mobile
Device Managements. Fehleranalyse im Change- und Problemmanagement,
2nd/3rd Level Support.

Sie bringen mit: Kenntnisse in OT-Systemen, -Software und -Protokollen.

Wir bieten: Eine Vergütung von 60.000 - 70.000 € nach Tarif (IG Metall),
Vollzeit, 2 Tage Homeoffice pro Woche.
"""


def _heuristic(text: str = ADVERT, title: str = ""):
    return HeuristicJobSpecExtractor().extract(text, title)


# ── the parser ────────────────────────────────────────────────────────────


def test_the_headline_beats_the_page_title() -> None:
    # A <title> is the headline plus the site; the (m/w/d) line is the
    # advert's own words.
    spec = _heuristic(title="IT-Administrator | Linde + Wiemann | Jobportal")
    assert spec.title is not None
    assert spec.title.value.startswith("IT-Administrator (m/w/d)")


def test_the_page_title_is_used_when_there_is_no_headline() -> None:
    spec = _heuristic("Wir suchen Verstärkung. " * 10, "Fachkraft Logistik | ACME AG")
    assert spec.title is not None
    # The site suffix is dropped.
    assert spec.title.value == "Fachkraft Logistik"
    # …and it is a weaker claim than a real headline.
    assert spec.title.confidence < 0.8


def test_the_band_is_read_as_two_numbers() -> None:
    spec = _heuristic()
    assert spec.salary_min is not None and spec.salary_max is not None
    assert (spec.salary_min.value, spec.salary_max.value) == ("60000", "70000")


@pytest.mark.parametrize(
    "text,low,high",
    [
        ("Gehalt 60.000 – 70.000 €", "60000", "70000"),
        ("Vergütung: 60 - 70 T€ jährlich", "60000", "70000"),
        ("salary 55,000 to 65,000 EUR", "55000", "65000"),
    ],
)
def test_the_band_survives_the_spellings_adverts_use(text, low, high) -> None:
    spec = _heuristic(text + " " * 100)
    assert spec.salary_min and spec.salary_max
    assert (spec.salary_min.value, spec.salary_max.value) == (low, high)


def test_one_number_becomes_the_CEILING_not_the_floor() -> None:
    # A single figure is not a band. Put in the minimum it would silently
    # exclude everyone below it; put in the maximum a recruiter widens it.
    spec = _heuristic("Das Gehalt liegt bei ca. 65.000 €. " * 5)
    assert spec.salary_min is None
    assert spec.salary_max is not None and spec.salary_max.value == "65000"
    assert spec.salary_max.confidence < 0.6


def test_an_advert_without_a_band_proposes_no_band() -> None:
    spec = _heuristic("Attraktive Vergütung nach Tarif IG Metall. " * 8)
    assert spec.salary_min is None and spec.salary_max is None


def test_a_year_is_not_a_salary() -> None:
    # "seit 2019" and "2nd/3rd Level" must not become money.
    spec = _heuristic("Das Unternehmen besteht seit 2019 - 2020 war das beste Jahr. " * 4)
    assert spec.salary_min is None and spec.salary_max is None


def test_the_labelled_location_wins_over_the_postcode() -> None:
    spec = _heuristic()
    assert spec.location is not None and spec.location.value == "Dillenburg"


def test_a_postcode_is_used_when_nothing_is_labelled() -> None:
    spec = _heuristic("Wir suchen für 35683 Dillenburg eine Fachkraft. " * 5)
    assert spec.location is not None and spec.location.value.startswith("35683")


def test_a_place_at_the_end_of_a_sentence_loses_the_full_stop() -> None:
    # The class must allow a dot — "St. Ingbert", "Bad Soden a.Ts." — so the
    # sentence's own punctuation comes along unless it is trimmed.
    spec = _heuristic("Standort: Dillenburg. Wir freuen uns auf Sie. " * 5)
    assert spec.location is not None and spec.location.value == "Dillenburg"


def test_a_place_with_a_dot_in_its_name_keeps_it() -> None:
    spec = _heuristic("Einsatzort: St. Ingbert bietet viel. " * 5)
    assert spec.location is not None and spec.location.value == "St. Ingbert"


def test_the_employment_form_is_read() -> None:
    assert _heuristic().employment_form.value == "Vollzeit"


def test_the_heuristic_proposes_no_hard_criteria() -> None:
    # The whole point: a regex must never decide who is excluded.
    assert _heuristic().must_have_skills == []


# ── HTML ──────────────────────────────────────────────────────────────────


def test_script_and_style_never_reach_the_parser() -> None:
    text, _ = jobspec.html_to_text(
        "<html><head><style>.a{color:red}</style>"
        "<script>var gehalt = '999.999 €';</script></head>"
        "<body><h1>Fachkraft (m/w/d)</h1><p>Vollzeit</p></body></html>"
    )
    assert "999.999" not in text and "color:red" not in text
    assert "Fachkraft (m/w/d)" in text and "Vollzeit" in text


def test_og_title_is_preferred_over_the_tab_title() -> None:
    _, title = jobspec.html_to_text(
        '<html><head><meta property="og:title" content="Fachkraft (m/w/d)">'
        "<title>Fachkraft | ACME | Jobs</title></head><body>x</body></html>"
    )
    assert title == "Fachkraft (m/w/d)"


def test_broken_markup_does_not_raise() -> None:
    text, _ = jobspec.html_to_text("<div><p>Stelle<span>offen</div></p></span")
    assert "Stelle" in text


# ── the fetcher's blast radius ────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/advert",
        "gopher://example.com",
        "javascript:alert(1)",
    ],
)
def test_only_http_is_fetchable(url) -> None:
    with pytest.raises(jobspec.NotFetchable):
        jobspec.check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/api/v1/jobs",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",  # cloud credentials
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://[::1]/",
    ],
)
def test_the_fetcher_cannot_be_aimed_inside(url) -> None:
    with pytest.raises(jobspec.NotFetchable):
        jobspec.check_url(url)


def test_a_hostname_resolving_inside_is_refused(monkeypatch) -> None:
    # The literal looks like any other host; only resolution gives it away,
    # which is why the check runs after getaddrinfo and not on the string.
    monkeypatch.setattr(
        jobspec.fetch.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 80))],
    )
    with pytest.raises(jobspec.NotFetchable):
        jobspec.check_url("http://adverts.example.com/job/1")


def test_one_private_answer_among_several_is_enough_to_refuse(monkeypatch) -> None:
    monkeypatch.setattr(
        jobspec.fetch.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 80)), (2, 1, 6, "", ("10.1.1.1", 80))],
    )
    with pytest.raises(jobspec.NotFetchable):
        jobspec.check_url("http://adverts.example.com/job/1")


def test_a_public_host_passes(monkeypatch) -> None:
    monkeypatch.setattr(
        jobspec.fetch.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 80))],
    )
    assert jobspec.check_url("https://adverts.example.com/job/1").startswith("https://")


# ── the endpoint ──────────────────────────────────────────────────────────


async def _post(body: dict):
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(f"{API}/parse-spec", json=body)


async def test_pasted_text_comes_back_as_a_proposal() -> None:
    response = await _post({"text": ADVERT})
    assert response.status_code == 200
    body = response.json()
    assert body["title"]["value"].startswith("IT-Administrator (m/w/d)")
    assert body["salary_max"]["value"] == "70000"
    assert body["excerpt"]


async def test_reading_an_advert_creates_no_mandate() -> None:
    """THE boundary. A model may propose a Suchprofil; it may not open one."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        before = len((await client.get(API)).json())
        assert (await client.post(f"{API}/parse-spec", json={"text": ADVERT})).status_code == 200
        after = len((await client.get(API)).json())
    assert before == after


async def test_pasted_html_is_stripped_before_parsing() -> None:
    response = await _post(
        {"text": "<html><body><h1>Fachkraft (m/w/d) Logistik</h1>"
                 "<p>Standort: Kassel</p><p>Vollzeit</p>"
                 f"<p>{'Aufgaben und Verantwortung. ' * 10}</p></body></html>"}
    )
    assert response.status_code == 200
    assert response.json()["location"]["value"] == "Kassel"


async def test_neither_url_nor_text_is_refused() -> None:
    assert (await _post({})).status_code == 422


async def test_a_page_with_no_advert_text_says_so() -> None:
    response = await _post({"text": "Cookies akzeptieren"})
    assert response.status_code == 422
    assert "Anzeigentext" in response.json()["detail"]


async def test_an_internal_url_is_refused_by_the_endpoint() -> None:
    response = await _post({"url": "http://127.0.0.1:8000/api/v1/jobs"})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "line,expected",
    [
        ("Standort: Dillenburg. Wir freuen uns auf Sie.", "Dillenburg"),
        ("Einsatzort: St. Ingbert bietet viel.", "St. Ingbert"),
        ("Standort: Frankfurt am Main", "Frankfurt"),
        ("Arbeitsort: 35683 Dillenburg, Hessen", "35683 Dillenburg, Hessen"),
        ("Dienstsitz: Berlin", "Berlin"),
        ("Standort: flexibel nach Absprache", ""),
    ],
)
def test_where_the_place_name_stops(line, expected) -> None:
    # A full stop is ambiguous in German place names: it ends a sentence AND
    # it lives inside "St. Ingbert". Length is what tells them apart.
    spec = _heuristic(line + "\n" + "Aufgaben und Verantwortung. " * 6)
    assert (spec.location.value if spec.location else "") == expected
