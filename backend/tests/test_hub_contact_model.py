"""ELI-25 layer 2: a model reads the ads the rules could not name a person in.

The model proposes; deterministic checks decide (backend/CLAUDE.md §2.5). A
name the model returns is kept only if it stands in the ad word for word,
close to a phone number or e-mail the ad gives, and every phone or e-mail
the model attaches is in the ad too. These tests pin the checks, the queue
and the pass — with a fake model, never the network.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.domain.hub import ad_contacts, contact_model
from app.domain.hub.contact_model import ModelPerson, excerpt, ground
from app.domain.hub.models import HubAdContact, HubCompany, HubJobPosting, HubPostingPayload

AD = (
    "Wir bieten ein tolles Team. Ihre Bewerbung richten Sie bitte direkt an Hussien Bader: "
    "h.bader@apotheke-am-hit.de oder telefonisch 0711 123456. Wir freuen uns auf Sie!"
)


def _p(first: str | None, last: str, *, phone: str | None = None, email: str | None = None, sal: str | None = None) -> ModelPerson:
    return ModelPerson(first_name=first, last_name=last, salutation=sal, role_title=None, phone=phone, email=email)


# --- the checks -----------------------------------------------------------


def test_a_name_that_stands_in_the_ad_next_to_its_contact_data_is_kept() -> None:
    (c,) = ground(AD, [_p("Hussien", "Bader", phone="0711 123456", email="h.bader@apotheke-am-hit.de")])
    assert (c.first_name, c.last_name, c.full_name) == ("Hussien", "Bader", "Hussien Bader")
    assert (c.phone, c.email, c.phone_kind) == ("0711 123456", "h.bader@apotheke-am-hit.de", "direct")
    assert "Hussien Bader" in c.quote


def test_a_name_the_ad_does_not_contain_is_dropped() -> None:
    assert ground(AD, [_p("Hussein", "Bader")]) == []  # not word for word
    assert ground(AD, [_p("Maria", "Schulz")]) == []


def test_a_phone_or_email_the_ad_does_not_contain_drops_the_person() -> None:
    # The model invented contact data: nothing it says about this person is trusted.
    assert ground(AD, [_p("Hussien", "Bader", phone="0711 999999")]) == []
    assert ground(AD, [_p("Hussien", "Bader", email="hussien@apotheke-am-hit.de")]) == []


def test_a_name_far_from_any_contact_data_is_dropped() -> None:
    text = "Unser Gründer Hussien Bader eröffnete 1990 die erste Filiale. " + "Lorem ipsum. " * 40 + "Tel. 0711 123456"
    assert ground(text, [_p("Hussien", "Bader")]) == []


@pytest.mark.parametrize("last", ["Personalabteilung", "Team", "GmbH"])
def test_a_unit_is_not_a_person_even_if_the_model_says_so(last: str) -> None:
    text = f"Kontakt: Recruiting {last}, Tel. 0711 123456"
    assert ground(text, [_p("Recruiting", last)]) == []


def test_a_saluted_surname_alone_is_kept() -> None:
    text = "Fragen beantwortet Ihnen gerne Frau Okonkwo unter 0711 123456."
    (c,) = ground(text, [_p(None, "Okonkwo", sal="Frau")])
    assert (c.salutation, c.first_name, c.last_name, c.phone) == ("Frau", None, "Okonkwo", "0711 123456")


def test_a_bare_surname_alone_is_not_enough() -> None:
    assert ground(AD, [_p(None, "Bader")]) == []


# --- what is sent --------------------------------------------------------


def test_only_the_lines_around_the_contact_data_are_sent() -> None:
    text = "Aufgaben " * 300 + AD + " Benefits " * 300
    sent = excerpt(text)
    assert sent is not None and "Hussien Bader" in sent and "0711 123456" in sent
    assert len(sent) <= contact_model.EXCERPT_MAX


def test_an_ad_without_contact_data_is_not_sent() -> None:
    assert excerpt("Wir suchen Verstärkung. Bewerben Sie sich online.") is None
    assert excerpt(None) is None


# --- the queue and the pass ---------------------------------------------

NOW = dt.datetime.now(dt.UTC)


async def _ad(text: str) -> uuid.UUID:
    async with SessionLocal() as s:
        company = HubCompany(
            name="Apotheke am HIT", normalized_name=f"apotheke-{uuid.uuid4().hex[:6]}", dedupe_key=f"k-{uuid.uuid4()}",
            resolution_basis="name_place", city="Stuttgart", source="bundesagentur", first_seen_at=NOW, last_seen_at=NOW,
        )
        s.add(company)
        await s.flush()
        posting = HubJobPosting(
            hub_company_id=company.id, title="PTA (m/w/d)", source="bundesagentur",
            external_id=f"10001-{uuid.uuid4().hex[:10]}-S", posted_at=NOW, first_seen_at=NOW, last_seen_at=NOW,
            is_active=True, content_hash=uuid.uuid4().hex, description_fetched_at=NOW,
        )
        posting.payload = HubPostingPayload(raw={}, description=text)
        s.add(posting)
        await s.commit()
        return posting.id


class FakeReader:
    def __init__(self, answer: list[ModelPerson] | Exception) -> None:
        self.answer, self.sent = answer, []

    async def read(self, excerpt: str) -> list[ModelPerson]:
        self.sent.append(excerpt)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


async def _due(posting_id: uuid.UUID) -> bool:
    async with SessionLocal() as s:
        return (await s.get(HubJobPosting, posting_id)).contacts_model_due


async def test_the_rule_pass_queues_only_ads_with_contact_data_and_no_named_person() -> None:
    unnamed = await _ad(AD)
    named = await _ad("Für Fragen steht Janet Jürgens telefonisch unter +49 5491 666 2834 zur Verfügung.")
    silent = await _ad("Bewerben Sie sich online über unser Portal.")
    async with SessionLocal() as s:
        await ad_contacts.backfill(s, limit=1000)
    assert (await _due(unnamed), await _due(named), await _due(silent)) == (True, False, False)


async def test_the_model_pass_stores_what_passes_the_checks_and_marks_it() -> None:
    posting_id = await _ad(AD)
    async with SessionLocal() as s:
        await ad_contacts.backfill(s, limit=1000)
    reader = FakeReader([_p("Hussien", "Bader", email="h.bader@apotheke-am-hit.de"), _p("Erfunden", "Person")])
    async with SessionLocal() as s:
        result = await contact_model.backfill(s, limit=1000, reader=reader)
    assert result["read"] >= 1 and result["failed"] == 0
    assert "Hussien Bader" in reader.sent[0]
    async with SessionLocal() as s:
        rows = (await s.execute(select(HubAdContact).where(HubAdContact.hub_job_posting_id == posting_id))).scalars().all()
    assert [(r.full_name, r.email, r.found_by) for r in rows] == [("Hussien Bader", "h.bader@apotheke-am-hit.de", "model")]
    assert await _due(posting_id) is False


async def test_a_model_failure_leaves_the_ad_queued_and_stores_nothing() -> None:
    posting_id = await _ad(AD)
    async with SessionLocal() as s:
        await ad_contacts.backfill(s, limit=1000)
    async with SessionLocal() as s:
        result = await contact_model.backfill(s, limit=1000, reader=FakeReader(TimeoutError("model down")))
    assert result["failed"] >= 1
    assert await _due(posting_id) is True
    async with SessionLocal() as s:
        rows = (await s.execute(select(HubAdContact).where(HubAdContact.hub_job_posting_id == posting_id))).scalars().all()
    assert rows == []


async def test_a_suppressed_person_is_never_stored_by_the_model_pass() -> None:
    from app.domain.hub import suppression

    posting_id = await _ad(AD)
    async with SessionLocal() as s:
        await ad_contacts.backfill(s, limit=1000)
        await suppression.suppress(s, scope="person", name="Hussien Bader", reason="objection")
    async with SessionLocal() as s:
        await contact_model.backfill(s, limit=1000, reader=FakeReader([_p("Hussien", "Bader")]))
        rows = (await s.execute(select(HubAdContact).where(HubAdContact.hub_job_posting_id == posting_id))).scalars().all()
    assert rows == []


async def test_without_a_model_the_pass_does_nothing() -> None:
    async with SessionLocal() as s:
        assert await contact_model.backfill(s, limit=10, reader=None) == {"read": 0, "contacts": 0, "failed": 0, "remaining": -1}


def test_the_model_pass_is_machine_only() -> None:
    from tests.test_operator_endpoints import DECLARED_OPERATOR_ROUTES

    assert ("POST", "/hub/ad-contacts/model-backfill") in DECLARED_OPERATOR_ROUTES


# --- real model answers the first checks dropped wrongly (measured 2026-11-11) ---


@pytest.mark.parametrize(
    ("text", "person", "name"),
    [
        ("Kontakt: Nortmeier Susanne +49 8025 2806 50", _p("Susanne", "Nortmeier"), "Susanne Nortmeier"),
        ("Ihr Kontakt | Kasek, Helene | 08861 219-7000", _p("Helene", "Kasek"), "Helene Kasek"),
        ("Stadtplatz 12, 4840 VöcklabruckSandra WagenederGeschäftsführerinT +43 7672 317 00-4810", _p("Sandra", "Wageneder"), "Sandra Wageneder"),
        ("finden Sie auf KontaktdatenNiclas StrzelskiTel.-Nr. 0160 96739876", _p("Niclas", "Strzelski", phone="0160 96739876"), "Niclas Strzelski"),
        ("Ihre Bewerbung an P. Ruckdeschel, Tel. 089/5155570", _p("P.", "Ruckdeschel"), "P. Ruckdeschel"),
        ("Kontakt: Eve J. Koncewicz, eve.koncewicz@agentur-suess.de", _p("Eve J.", "Koncewicz"), "Eve J. Koncewicz"),
        ("Fragen an Ina Roser-Plötz, Telefon 0781 800 – 3122", _p("Ina", "Roser-Plötz", phone="0781 800 – 3122"), "Ina Roser-Plötz"),
    ],
)
def test_forms_a_real_ad_writes_a_name_in(text: str, person: ModelPerson, name: str) -> None:
    (c,) = ground(text, [person])
    assert c.full_name == name


def test_a_name_far_from_the_contact_data_counts_when_its_email_spells_it() -> None:
    text = "Ihre Ansprechpartnerin Lorena Ahrens freut sich auf Sie. " + "Wir bieten viel. " * 30 + "lorena.ahrens@container.de"
    (c,) = ground(text, [_p("Lorena", "Ahrens", email="lorena.ahrens@container.de")])
    assert c.email == "lorena.ahrens@container.de"


def test_an_obfuscated_email_is_kept_as_an_address() -> None:
    text = "Ansprechpartner: Johannes Schulz, Tel. 06298 923131, johannes.schulz[at]baustoffe-schulz.de"
    (c,) = ground(text, [_p("Johannes", "Schulz", email="johannes.schulz[at]baustoffe-schulz.de")])
    assert c.email == "johannes.schulz@baustoffe-schulz.de"


def test_a_company_mailbox_is_not_a_persons_email() -> None:
    text = "Bildungszentrum Rostock Dorit Pries Tel. 0381 80944-13 bewerben@grone.de"
    (c,) = ground(text, [_p("Dorit", "Pries", phone="0381 80944-13", email="bewerben@grone.de")])
    assert (c.full_name, c.phone, c.email) == ("Dorit Pries", "0381 80944-13", None)


def test_a_name_only_inside_an_email_address_is_not_written_in_the_ad() -> None:
    # The model rebuilt "Eva Hofer" from the address: not written, not kept.
    assert ground("Bewerbung an: eva.hofer@hiebler-gmbh.at. Besuchen Sie uns", [_p("Eva", "Hofer", email="eva.hofer@hiebler-gmbh.at")]) == []


def test_a_street_is_not_a_person_even_in_the_order_the_model_gives() -> None:
    text = "Bewerbung an: Musterfirma, Daniel Gran-Straße 12, 3100 St. Pölten, Tel. 02742/26839"
    assert ground(text, [_p("Daniel", "Gran-Straße", phone="02742/26839")]) == []


async def test_the_nightly_job_asks_the_model_in_batches_and_stops_when_it_should() -> None:
    import httpx

    from scripts.hub_daily import _read_ad_contacts_model

    left = {"n": 120, "down": False, "off": False}
    asked: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        n = int(request.url.params["limit"])
        asked.append(n)
        if left["off"]:
            return httpx.Response(200, json={"read": 0, "contacts": 0, "failed": 0, "remaining": -1})
        if left["down"]:
            return httpx.Response(200, json={"read": 0, "contacts": 0, "failed": n, "remaining": left["n"]})
        read = min(n, left["n"])
        left["n"] -= read
        return httpx.Response(200, json={"read": read, "contacts": read // 2, "failed": 0, "remaining": left["n"]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://api") as client:
        # The queue drains, then the job stops.
        assert await _read_ad_contacts_model(client, budget=10_000) == {"read": 120, "contacts": 60, "failed": 0, "remaining": 0}
        assert asked == [50, 50, 50]
        # The model is down: one failed batch, and the ads wait for the next night.
        asked.clear(); left.update(n=500, down=True)
        assert (await _read_ad_contacts_model(client, budget=10_000))["failed"] == 50
        assert asked == [50]
        # No model configured: nothing is asked twice.
        asked.clear(); left.update(down=False, off=True)
        assert (await _read_ad_contacts_model(client, budget=10_000))["remaining"] == -1
        assert asked == [50]
