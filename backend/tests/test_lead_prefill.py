"""ELI-73: "Kann das Tool eine Stellenanzeige auslesen und die Daten übernehmen?"

In "+ Lead" the recruiter pastes a job-ad link or the ad's text and wants the
fields filled. RULE 1: no request handler fetches a URL. So:

  * a link to an ad Markt already holds — matched on the source's own
    reference (`source`, `external_id`; the inverse of `source_detail_url`)
    — prefills Job (the ad title), Firma (the employer) and the people the
    ad names, exactly as the corpus holds them: the deterministic rules on
    the stored text, plus the contacts the nightly model pass found AND the
    checks confirmed word for word;
  * a link Markt does not hold says so, and the pasted ad text is read by the
    same deterministic rules — no model call;
  * nothing is saved: it is a proposal for the form. The saved lead records
    where it came from — the ad link, or "aus eingefügtem Anzeigentext";
  * no outbound HTTP, whatever is pasted.
"""

from __future__ import annotations

import datetime as dt
import uuid

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.hub import posting_links
from app.domain.hub.models import HubAdContact, HubCompany, HubJobPosting, HubPostingPayload
from app.domain.hub.schemas import source_detail_url
from app.domain.managers.models import Manager

API = settings.api_v1_prefix
NOW = dt.datetime.now(dt.UTC)
REFNR = "10000-1201234567-S"
AD_TEXT = (
    "Senior Java Entwickler (m/w/d)\n"
    "Nordlicht Software GmbH · Freiburg im Breisgau · Vollzeit\n"
    "Wir suchen ab sofort einen Senior Java Entwickler (m/w/d) für unser Team in Freiburg.\n"
    "Ihre Aufgaben: Entwicklung und Betrieb unserer Plattform.\n"
    "Ihre Ansprechpartnerin: Frau Anna Berg, Tel. 0761 123456, anna.berg@firma.de\n"
)


def _api() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def no_outbound_http(monkeypatch):
    """Any outbound request fails the test. The app's own test client is an
    ASGI transport and never reaches `send` on a real network transport."""

    async def refuse_async(self, request, *args, **kwargs):  # noqa: ANN001
        raise AssertionError(f"outbound HTTP to {request.url}")

    def refuse(self, request, *args, **kwargs):  # noqa: ANN001
        raise AssertionError(f"outbound HTTP to {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse_async)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    import socket

    real = socket.socket.connect

    def no_connect(sock, address):  # noqa: ANN001
        # Belt and braces: whatever client a future change might pull in.
        raise AssertionError(f"outbound connect to {address}")

    monkeypatch.setattr(socket.socket, "connect", no_connect)
    yield
    monkeypatch.setattr(socket.socket, "connect", real)


async def _ad(*, source: str = "bundesagentur", external_id: str = REFNR, text: str | None = AD_TEXT,
              staffing: bool = False) -> uuid.UUID:
    async with SessionLocal() as s:
        company = HubCompany(
            name="Nordlicht Software GmbH", normalized_name="nordlicht software", dedupe_key=f"k-{uuid.uuid4()}",
            resolution_basis="name_place", city="Freiburg", source=source, first_seen_at=NOW, last_seen_at=NOW,
            staffing_name=staffing,
        )
        s.add(company)
        await s.flush()
        posting = HubJobPosting(
            hub_company_id=company.id, title="Senior Java Entwickler (m/w/d)", source=source,
            external_id=external_id, posted_at=NOW, first_seen_at=NOW, last_seen_at=NOW, is_active=True,
            content_hash=uuid.uuid4().hex,
        )
        posting.payload = HubPostingPayload(raw={}, description=text)
        s.add(posting)
        await s.commit()
        return posting.id


async def _prefill(**body) -> dict:
    async with _api() as c:
        r = await c.post(f"{API}/managers/leads/prefill", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# --- the link → the ad Markt holds ----------------------------------------


def test_every_ad_link_markt_builds_leads_back_to_its_ad() -> None:
    refs = [
        ("bundesagentur", REFNR),
        ("personio", "nordlicht:1234567"),
        ("greenhouse", "nordlicht:4012345"),
        ("ashby", "nordlicht:7f3c2b1a-0e9d-4c8b-a1f2-3d4e5f6a7b8c"),
        ("lever", "nordlicht:0a1b2c3d-4e5f-6789-abcd-ef0123456789"),
        ("lever", "eu:nordlicht:0a1b2c3d-4e5f-6789-abcd-ef0123456789"),
        ("eures", "MTIzNDU2Nzg5IDE"),
    ]
    for source, external_id in refs:
        url = source_detail_url(source, external_id)
        assert posting_links.posting_ref(url) == (source, external_id), url


def test_the_links_people_paste_are_read_too() -> None:
    ref = posting_links.posting_ref
    assert ref(f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{REFNR}?pk_campaign=x#top") == ("bundesagentur", REFNR)
    assert ref(f"arbeitsagentur.de/jobsuche/jobdetail/{REFNR}/") == ("bundesagentur", REFNR)
    assert ref("https://nordlicht.jobs.personio.com/job/1234567?display=en") == ("personio", "nordlicht:1234567")
    assert ref("https://boards.greenhouse.io/nordlicht/jobs/4012345") == ("greenhouse", "nordlicht:4012345")
    # Board slugs are stored lower-case; the apply pages are the same ad.
    assert ref("https://jobs.ashbyhq.com/Nordlicht/7f3c/application") == ("ashby", "nordlicht:7f3c")
    assert ref("https://jobs.lever.co/nordlicht/0a1b/apply") == ("lever", "nordlicht:0a1b")
    for other in ("https://www.stepstone.de/stellenangebote--Java-123.html", "https://www.linkedin.com/jobs/view/1",
                  "", "not a link", "https://www.arbeitsagentur.de/jobsuche/suche?was=java"):
        assert ref(other) is None


async def test_a_link_to_an_ad_in_markt_prefills_the_form() -> None:
    posting_id = await _ad()
    body = await _prefill(url=f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{REFNR}")
    assert body["found"] == "corpus"
    assert body["posting_id"] == str(posting_id)
    assert body["job_title"] == "Senior Java Entwickler (m/w/d)"
    assert body["company_name"] == "Nordlicht Software GmbH"
    assert body["source_url"] == source_detail_url("bundesagentur", REFNR)
    (person,) = body["contacts"]
    assert person["full_name"] == "Anna Berg"
    assert person["email"] == "anna.berg@firma.de"
    assert person["phone"] == "0761 123456"
    assert person["found_by"] == "rules"
    # Nothing was written.
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).select_from(Manager)) == 0


async def test_a_contact_the_verified_model_pass_found_is_offered_as_stored() -> None:
    posting_id = await _ad(text="Bei Fragen hilft Ihnen unser Team gerne weiter.")
    async with SessionLocal() as s:
        posting = await s.get(HubJobPosting, posting_id)
        s.add(HubAdContact(
            hub_job_posting_id=posting_id, hub_company_id=posting.hub_company_id, person_key="berg",
            full_name="Anna Berg", first_name="Anna", last_name="Berg", role_title="Teamleitung HR",
            email="anna.berg@firma.de", quote="… Anna Berg (Teamleitung HR) …", text_source="ad", found_by="model",
        ))
        await s.commit()
    body = await _prefill(url=source_detail_url("bundesagentur", REFNR))
    (person,) = body["contacts"]
    assert (person["full_name"], person["role_title"], person["found_by"]) == ("Anna Berg", "Teamleitung HR", "model")


async def test_an_agency_ad_is_marked() -> None:
    await _ad(staffing=True)
    assert (await _prefill(url=source_detail_url("bundesagentur", REFNR)))["is_agency"] is True


async def test_a_link_markt_does_not_hold_asks_for_the_text() -> None:
    body = await _prefill(url="https://www.stepstone.de/stellenangebote--Senior-Java-12345.html")
    assert body["found"] == "not_in_corpus"
    assert body["contacts"] == [] and body["job_title"] is None
    # A known shape, but an ad Markt has not seen.
    assert (await _prefill(url=source_detail_url("bundesagentur", "10000-0000000000-S")))["found"] == "not_in_corpus"


# --- the pasted text --------------------------------------------------------


async def test_pasted_text_proposes_the_named_contact_and_the_title() -> None:
    body = await _prefill(text=AD_TEXT)
    assert body["found"] == "text"
    assert body["job_title"] == "Senior Java Entwickler (m/w/d)"
    (person,) = body["contacts"]
    assert person["full_name"] == "Anna Berg"
    assert person["email"] == "anna.berg@firma.de"
    assert person["phone"] == "0761 123456"


async def test_a_title_is_never_cut_out_of_a_sentence() -> None:
    body = await _prefill(text="Wir suchen ab sofort einen Senior Java Entwickler (m/w/d) für unser Team.")
    assert body["job_title"] is None


def test_titles_people_write() -> None:
    from app.domain.managers.prefill import title_from_text

    assert title_from_text("Koch (m/w/d) gesucht!\nWir freuen uns.") == "Koch (m/w/d) gesucht!"
    assert title_from_text("Koch m/w/d\nIn Vollzeit") == "Koch m/w/d"
    # A board's related-jobs list is not this ad's title.
    assert title_from_text("Stellenangebote ähnlich wie Koch (m/w/d)\nBäcker (m/w/d)") == "Bäcker (m/w/d)"


async def test_someone_the_corpus_suppresses_is_never_proposed() -> None:
    from app.domain.hub import suppression

    await _ad()
    async with SessionLocal() as s:
        await suppression.suppress(s, scope=suppression.SUPPRESS_PERSON, name="Anna Berg", reason="objection")
        await s.commit()
    assert (await _prefill(url=source_detail_url("bundesagentur", REFNR)))["contacts"] == []
    assert (await _prefill(text=AD_TEXT))["contacts"] == []


async def _erase(full_name: str, *, phone: str | None = None) -> None:
    from app.domain.erasure import service as erasure

    async with _api() as c:
        lead = (await c.post(f"{API}/managers/leads", json={
            "job_title": "Controller", "full_name": full_name, "company_name": "Nordlicht Software GmbH",
            "phone": phone,
        })).json()
    async with SessionLocal() as s:
        await erasure.erase_manager(
            s, tenant_id=settings.default_tenant_id, manager_id=uuid.UUID(lead["id"]), confirm_name=full_name,
            reason="erasure", requested_on=dt.date(2026, 11, 11), actor_user_id="u1", actor_name="Test",
        )
        await s.commit()


async def test_someone_this_workspace_erased_is_dropped(monkeypatch) -> None:
    monkeypatch.setattr(settings, "suppression_key", "k" * 40)
    await _ad()
    await _erase("Anna Berg")
    body = await _prefill(url=source_detail_url("bundesagentur", REFNR))
    assert body["contacts"] == [] and body["contacts_withheld"] is False


async def test_a_person_erased_by_their_mobile_is_dropped_though_the_ad_gives_a_landline(monkeypatch) -> None:
    monkeypatch.setattr(settings, "suppression_key", "k" * 40)
    await _erase("Lena Ott", phone="0171 2345678")
    body = await _prefill(text="Ihre Ansprechpartnerin: Frau Jana Kurz, Tel. 0761 123456, mobil 0171 2345678")
    assert body["contacts"] == []


async def test_when_erasures_cannot_be_checked_nobody_is_proposed_and_it_says_so(monkeypatch) -> None:
    monkeypatch.setattr(settings, "suppression_key", "k" * 40)
    await _ad()
    await _erase("Ben Ott")
    monkeypatch.setattr(settings, "suppression_key", "")
    body = await _prefill(url=source_detail_url("bundesagentur", REFNR))
    assert body["contacts"] == [] and body["contacts_withheld"] is True


async def test_text_naming_nobody_proposes_nobody() -> None:
    body = await _prefill(text="Bewerbungen bitte an jobs@firma.de. Wir freuen uns auf Sie!")
    assert body["contacts"] == [] and body["job_title"] is None


async def test_an_empty_request_is_refused() -> None:
    async with _api() as c:
        assert (await c.post(f"{API}/managers/leads/prefill", json={})).status_code == 422


# --- what the saved lead records -------------------------------------------


async def test_the_saved_lead_records_where_it_came_from() -> None:
    lead = {"job_title": "Senior Java Entwickler (m/w/d)", "full_name": "Anna Berg",
            "company_name": "Nordlicht Software GmbH"}
    async with _api() as c:
        from_ad = await c.post(f"{API}/managers/leads", json={
            **lead, "source_url": source_detail_url("bundesagentur", REFNR),
        })
        from_text = await c.post(f"{API}/managers/leads", json={
            **lead, "full_name": "Ben Ott", "from_pasted_text": True,
        })
    assert from_ad.status_code == 201, from_ad.text
    assert from_ad.json()["source_detail"] == source_detail_url("bundesagentur", REFNR)
    assert from_text.status_code == 201, from_text.text
    assert from_text.json()["source_detail"] == "aus eingefügtem Anzeigentext"
