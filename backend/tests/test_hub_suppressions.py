"""The opt-out list — erasure that survives the next crawl.

The corpus re-ingests every night. Deleting a company or a person's name is
undone by the next pass, because the source still publishes it. So an
objection (GDPR Art. 21) or an erasure request (Art. 17) becomes a row in
`hub_suppressions`, checked at every write into the corpus:

  * a suppressed COMPANY is refused at ingest — counted, never stored;
  * a suppressed PERSON's name is cut out of every ad text before it is
    stored, and once from the texts already there;
  * the contacts read drops a suppressed person even from a text that was
    somehow missed (read-time backstop).

The tests that matter most are the re-crawl ones: delete, crawl again, and
the row must still be gone.
"""

from __future__ import annotations

import datetime as dt

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.hub import service, suppression
from app.domain.hub.adapters.base import (
    FetchResult,
    SourcedCompany,
    SourcedPosting,
)
from app.domain.hub.adapters.partner_pages import PartnerPage
from app.domain.hub.models import (
    PRIVATE_RECRUITER,
    HubCompany,
    HubCompanyLink,
    HubJobPosting,
    HubObservation,
    HubPostingPayload,
    HubSuppression,
)
from app.domain.hub.schemas import IngestRequest
from app.main import app

_AD = (
    "Für Rückfragen steht Ihnen Frau Katrin Wolter (Pflegedienstleitung) "
    "unter k.wolter@klinikum.example zur Verfügung. Ihre Bewerbung bearbeitet "
    "Herr Jan Dziobek."
)


# ---------------------------------------------------------------------------
# Keys and redaction — pure
# ---------------------------------------------------------------------------


def test_a_person_key_is_the_folded_full_name() -> None:
    assert suppression.person_key("Dr. Katrin  Wolter") == "katrin wolter"
    assert suppression.person_key("Frau Sophie Grümbel") == "sophie gruembel"


def test_a_surname_alone_is_too_broad_to_suppress() -> None:
    # "Müller" alone would cut every Müller out of every ad in Germany.
    with pytest.raises(ValueError):
        suppression.person_key("Wolter")


def test_redaction_removes_every_form_of_the_name() -> None:
    rules = suppression.Suppressions(persons=("katrin wolter",))
    out = rules.redact(_AD + " Frau Wolter freut sich. KATRIN WOLTER")
    assert "wolter" not in out.lower()
    assert suppression.REDACTED in out
    # Everyone else in the text stays — the ad is still useful.
    assert "Herr Jan Dziobek" in out
    assert "Pflegedienstleitung" in out


def test_redaction_matches_umlauts_either_way() -> None:
    rules = suppression.Suppressions(persons=(suppression.person_key("Sophie Grümbel"),))
    for text in ("Sophie Gruembel", "Sophie Grümbel", "Frau GRÜMBEL", "s.gruembel@x.de"):
        assert "mbel" not in rules.redact(text).lower(), text


def test_redaction_does_not_cut_a_longer_name() -> None:
    rules = suppression.Suppressions(persons=("jan wolter",))
    assert rules.redact("Frau Katrin Wolters") == "Frau Katrin Wolters"


def test_redaction_walks_the_archived_source_record() -> None:
    rules = suppression.Suppressions(persons=("katrin wolter",))
    raw = {"kontakt": {"name": "Katrin Wolter"}, "liste": ["Frau Wolter", 3]}
    assert "Wolter" not in str(rules.redact_json(raw))
    assert rules.redact_json(raw)["liste"][1] == 3


def test_a_name_written_surname_first_gives_the_same_key() -> None:
    # How a name appears on a letter. A reversed key would silently suppress
    # nothing: "katrin" would be taken for the surname.
    assert suppression.person_key("Wolter, Katrin") == "katrin wolter"


@pytest.mark.parametrize(
    "text",
    [
        "Wolter, Katrin",
        "Wolter Katrin",
        "Katrin Wolter-Schmidt",
        "Hr. Wolter",
        "Fr. Wolter",
        "Frau Dr. med. Wolter",
        "K. Wolter",
        "**Katrin Wolter**",
        "Katrin\nWolter",
    ],
)
def test_redaction_catches_the_other_written_forms(text: str) -> None:
    rules = suppression.Suppressions(persons=("katrin wolter",))
    out = rules.redact(text)
    assert "wolter" not in out.lower() and "schmidt" not in out.lower(), out


def test_a_hyphenated_first_name_matches_with_a_space() -> None:
    rules = suppression.Suppressions(persons=(suppression.person_key("Marie-Luise Weber"),))
    assert "weber" not in rules.redact("Marie Luise Weber").lower()


def test_an_umlaut_email_address_is_cut() -> None:
    rules = suppression.Suppressions(persons=(suppression.person_key("Anna Grümbel"),))
    assert "mbel" not in rules.redact("a.grümbel@firma.de").lower()


def test_no_suppressions_leaves_text_untouched() -> None:
    assert suppression.Suppressions().redact(_AD) == _AD


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def _result(firma: str, external_id: str, description: str | None = None) -> FetchResult:
    return FetchResult(
        source="bundesagentur",
        request_url="https://example.invalid/pc/v6/jobs",
        fetched_at=dt.datetime.now(dt.UTC),
        http_status=200,
        total_available=1,
        postings=[
            SourcedPosting(
                external_id=external_id,
                title="Pflegefachkraft (m/w/d)",
                company=SourcedCompany(name=firma, postal_code="04105", city="Leipzig"),
                postal_code="04105",
                city="Leipzig",
                posted_at=dt.datetime.now(dt.UTC),
                description=description,
                raw={"kontakt": description} if description else {},
            )
        ],
    )


class _Replay:
    name = "bundesagentur"

    def __init__(self, result: FetchResult, details: dict[str, str] | None = None) -> None:
        self.result = result
        self.details = details or {}

    async def fetch(self, query):
        return self.result

    async def fetch_description(self, external_id: str) -> str | None:
        return self.details.get(external_id)


async def _suppress(scope: str, name: str) -> dict:
    async with SessionLocal() as s:
        return await suppression.suppress(s, scope=scope, name=name, reason="objection")


async def _count(model) -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(func.count()).select_from(model)) or 0


async def test_a_suppressed_company_is_refused_at_ingest() -> None:
    await _suppress("company", "Klinikum Musterstadt GmbH")
    async with SessionLocal() as s:
        summary = await service.ingest(
            s, adapter=_Replay(_result("Klinikum Musterstadt GmbH", "a-1")), request=IngestRequest()
        )
        observation = await s.get(HubObservation, summary.observation_id)
    assert await _count(HubCompany) == 0
    assert await _count(HubJobPosting) == 0
    assert summary.suppressed == 1
    assert any("opt-out" in n for n in summary.notes)
    assert "suppressed=1" in (observation.note or "")
    # Not echoed back by name: the refusal must not re-publish who objected.
    assert summary.rejected == []


async def test_suppressing_a_company_removes_it_and_a_recrawl_does_not_bring_it_back() -> None:
    name = "Klinikum Musterstadt GmbH"
    async with SessionLocal() as s:
        await service.ingest(s, adapter=_Replay(_result(name, "a-1", _AD)), request=IngestRequest())
        await service.ingest(
            s,
            adapter=_Replay(_result(name, "p-1")),
            request=IngestRequest(segment=PRIVATE_RECRUITER),
        )
        company = await s.scalar(select(HubCompany).limit(1))
        s.add(HubCompanyLink(tenant_id=settings.default_tenant_id, hub_company_id=company.id))
        await s.commit()
    assert await _count(HubCompany) == 2  # employer row + agency row

    outcome = await _suppress("company", "KLINIKUM Musterstadt")
    assert outcome["companies_deleted"] == 2  # every row of that name, both kinds
    for model in (HubCompany, HubJobPosting, HubPostingPayload, HubCompanyLink):
        assert await _count(model) == 0, model.__name__

    async with SessionLocal() as s:
        await service.ingest(s, adapter=_Replay(_result(name, "a-1", _AD)), request=IngestRequest())
    assert await _count(HubCompany) == 0


async def test_suppressing_twice_keeps_one_entry() -> None:
    await _suppress("person", "Katrin Wolter")
    await _suppress("person", "Dr. Katrin Wolter")
    assert await _count(HubSuppression) == 1


async def test_a_suppressed_person_is_cut_from_ad_text_at_ingest() -> None:
    await _suppress("person", "Katrin Wolter")
    async with SessionLocal() as s:
        await service.ingest(
            s, adapter=_Replay(_result("Klinikum Musterstadt", "a-1", _AD)), request=IngestRequest()
        )
        payload = await s.scalar(select(HubPostingPayload))
    assert "Wolter" not in (payload.description or "")
    assert "Wolter" not in str(payload.raw)
    assert "Dziobek" in payload.description


async def test_suppressing_a_person_redacts_the_texts_already_stored() -> None:
    async with SessionLocal() as s:
        await service.ingest(
            s, adapter=_Replay(_result("Klinikum Musterstadt", "a-1", _AD)), request=IngestRequest()
        )
        payload = await s.scalar(select(HubPostingPayload))
        payload.source_page_text = "Ihr Kontakt\nKatrin Wolter\nRecruiterin"
        await s.commit()

    outcome = await _suppress("person", "Katrin Wolter")
    assert outcome["texts_redacted"] == 1

    async with SessionLocal() as s:
        payload = await s.scalar(select(HubPostingPayload))
        await s.refresh(payload)
    for text in (payload.description, payload.source_page_text, str(payload.raw)):
        assert "Wolter" not in text

    # A re-crawl of the same ad must not restore the name.
    async with SessionLocal() as s:
        await service.ingest(
            s,
            adapter=_Replay(_result("Klinikum Musterstadt", "a-1", _AD + " (aktualisiert)")),
            request=IngestRequest(),
        )
        payload = await s.scalar(select(HubPostingPayload))
        await s.refresh(payload)
    assert "Wolter" not in payload.description


async def test_the_sweep_finds_a_name_that_is_only_in_the_archived_record() -> None:
    # `raw` is stored as JSON with non-ASCII escaped ("Gr\\u00fcmbel"), so a
    # plain LIKE on the name misses it.
    result = _result("Klinikum Musterstadt", "a-1")
    result.postings[0].raw = {"kontakt": "Anna Grümbel"}
    async with SessionLocal() as s:
        await service.ingest(s, adapter=_Replay(result), request=IngestRequest())
    outcome = await _suppress("person", "Anna Grümbel")
    assert outcome["texts_redacted"] == 1
    async with SessionLocal() as s:
        payload = await s.scalar(select(HubPostingPayload))
        await s.refresh(payload)
    assert "mbel" not in str(payload.raw)


async def test_the_description_pass_redacts_a_suppressed_person() -> None:
    await _suppress("person", "Katrin Wolter")
    adapter = _Replay(_result("Klinikum Musterstadt", "a-1"), details={"a-1": _AD})
    async with SessionLocal() as s:
        await service.ingest(s, adapter=adapter, request=IngestRequest())
        await service.fetch_missing_descriptions(s, adapter=adapter, delay=0)
        payload = await s.scalar(select(HubPostingPayload))
    assert payload.description and "Wolter" not in payload.description


async def test_the_partner_page_pass_redacts_a_suppressed_person() -> None:
    await _suppress("person", "Katrin Wolter")
    url = "https://board.example/job/1"
    result = _result("Klinikum Musterstadt", "a-1")
    result.postings[0].source_url = url

    class _Fetcher:
        async def fetch(self, u: str) -> PartnerPage:
            return PartnerPage(u, None, 200, "Ihr Kontakt\nKatrin Wolter\nRecruiterin")

    async with SessionLocal() as s:
        await service.ingest(s, adapter=_Replay(result), request=IngestRequest())
        await service.fetch_missing_partner_pages(s, fetcher=_Fetcher())
        payload = await s.scalar(select(HubPostingPayload))
    assert payload.source_page_text and "Wolter" not in payload.source_page_text


async def test_contacts_drop_a_suppressed_person_even_from_an_unredacted_text() -> None:
    # A text stored before the suppression and missed by the backfill.
    async with SessionLocal() as s:
        await service.ingest(
            s, adapter=_Replay(_result("Klinikum Musterstadt", "a-1", _AD)), request=IngestRequest()
        )
        company = await s.scalar(select(HubCompany))
        s.add(HubSuppression(scope="person", key="katrin wolter", reason="erasure"))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        response = await c.get(f"/api/v1/hub/companies/{company.id}/contacts")
    assert response.status_code == 200
    assert "Wolter" not in response.text
    assert "Dziobek" in response.text
