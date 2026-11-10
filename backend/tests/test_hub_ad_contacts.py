"""Ad contacts stored nightly — `hub_ad_contacts` (ELI-22).

The people a public ad names, read once by a scheduled pass instead of on every
panel open, so a call list can span the whole market. Shared corpus under
ARCHITECTURE.md RULE 2: as published, with provenance, and gone again when the
ad text goes (closed ad, suppressed person or company).
"""

from __future__ import annotations

import datetime as dt
import pathlib

from sqlalchemy import func, select, update

from app.core.database import SessionLocal
from app.domain.hub import ad_contacts, ats, service, suppression
from app.domain.hub.adapters.base import FetchResult, SourcedCompany, SourcedPosting
from app.domain.hub.models import (
    AD_CONTACT_RULES,
    HubAdContact,
    HubAtsBoard,
    HubJobPosting,
    HubPostingPayload,
    HubSuppression,
)

WOLTER = "Für Rückfragen: Frau Katrin Wolter (Pflegedienstleitung)\nTelefon 0395 5442681\n"
HOTLINE = "Ihre Ansprechpartnerin: Anna Weidner\nHotline 0800 / 4007766\n"


def _result(*ads: tuple[str, str | None], source: str = "bundesagentur") -> FetchResult:
    now = dt.datetime.now(dt.UTC)
    return FetchResult(
        source=source, request_url="https://example.invalid/feed", fetched_at=now, http_status=200,
        total_available=len(ads),
        postings=[
            SourcedPosting(
                external_id=external_id, title="Pflegefachkraft (m/w/d)",
                company=SourcedCompany(name="Pflegeheim Sonnenhof GmbH", postal_code="17033", city="Neubrandenburg"),
                postal_code="17033", city="Neubrandenburg", description=text, raw={},
            )
            for external_id, text in ads
        ],
    )


async def _ingest(*ads: tuple[str, str | None], source: str = "bundesagentur") -> None:
    async with SessionLocal() as s:
        await service.merge_fetch(s, result=_result(*ads, source=source), key="t")


async def _backfill(limit: int = 100) -> dict[str, int]:
    async with SessionLocal() as s:
        return await ad_contacts.backfill(s, limit=limit)


async def _contacts() -> list[HubAdContact]:
    async with SessionLocal() as s:
        return list((await s.scalars(select(HubAdContact).order_by(HubAdContact.last_name))).all())


async def test_the_pass_stores_each_named_person_with_provenance() -> None:
    await _ingest(("a-1", WOLTER), ("a-2", HOTLINE))
    assert await _backfill() == {"read": 2, "contacts": 2, "remaining": 0}

    weidner, wolter = await _contacts()
    async with SessionLocal() as s:
        posting = await s.scalar(select(HubJobPosting).where(HubJobPosting.external_id == "a-1"))
    assert (wolter.salutation, wolter.first_name, wolter.last_name) == ("Frau", "Katrin", "Wolter")
    assert (wolter.role_title, wolter.phone, wolter.phone_kind) == ("Pflegedienstleitung", "0395 5442681", "direct")
    assert weidner.phone_kind == "switchboard"
    # Provenance: which ad, which of its texts, fetched when, and the line itself.
    assert wolter.hub_job_posting_id == posting.id
    assert wolter.hub_company_id == posting.hub_company_id
    assert wolter.text_source == "ad"
    assert wolter.source_fetched_at is not None
    assert "Katrin Wolter" in wolter.quote


async def test_a_second_run_reads_nothing_and_duplicates_nothing() -> None:
    await _ingest(("a-1", WOLTER))
    await _backfill()
    assert await _backfill() == {"read": 0, "contacts": 0, "remaining": 0}
    assert len(await _contacts()) == 1


async def test_the_pass_works_in_batches() -> None:
    await _ingest(("a-1", WOLTER), ("a-2", HOTLINE), ("a-3", None))
    assert (await _backfill(limit=2))["remaining"] == 1
    assert (await _backfill(limit=2))["remaining"] == 0


async def test_an_ad_without_text_is_read_once_and_again_when_text_arrives() -> None:
    await _ingest(("a-1", None))
    assert await _backfill() == {"read": 1, "contacts": 0, "remaining": 0}
    assert await _backfill() == {"read": 0, "contacts": 0, "remaining": 0}

    # The description pass fills the text later (it stamps the fetch time).
    async with SessionLocal() as s:
        row = await s.scalar(select(HubJobPosting).where(HubJobPosting.external_id == "a-1"))
        row.description_fetched_at = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=1)
        payload = await s.get(HubPostingPayload, row.id)
        payload.description = WOLTER
        await s.commit()
    assert await _backfill() == {"read": 1, "contacts": 1, "remaining": 0}


async def test_a_changed_ad_replaces_its_contacts() -> None:
    await _ingest(("a-1", WOLTER))
    await _backfill()
    await _ingest(("a-1", HOTLINE))  # re-ingest with a new text
    await _backfill()
    assert [c.last_name for c in await _contacts()] == ["Weidner"]


async def test_the_partner_page_is_read_too_and_one_person_is_one_row() -> None:
    await _ingest(("a-1", "Frau Katrin Wolter freut sich auf Sie."))
    async with SessionLocal() as s:
        row = await s.scalar(select(HubJobPosting))
        row.source_page_fetched_at = dt.datetime.now(dt.UTC)
        payload = await s.get(HubPostingPayload, row.id)
        payload.source_page_text = WOLTER
        await s.commit()
    await _backfill()
    (wolter,) = await _contacts()
    # The fuller mention wins: the page gives the phone the ad does not.
    assert (wolter.phone, wolter.text_source) == ("0395 5442681", "page")


async def test_a_suppressed_person_is_never_stored() -> None:
    await _ingest(("a-1", WOLTER), ("a-2", HOTLINE))
    # Recorded behind the text's back, as if the redaction had missed it: the
    # pass must still not store the person (the read path's backstop, here).
    async with SessionLocal() as s:
        s.add(HubSuppression(scope="person", key=suppression.person_key("Katrin Wolter"), reason="objection"))
        await s.commit()
    await _backfill()
    assert [c.last_name for c in await _contacts()] == ["Weidner"]


async def test_suppressing_a_person_removes_what_is_stored() -> None:
    await _ingest(("a-1", WOLTER), ("a-2", HOTLINE))
    await _backfill()
    async with SessionLocal() as s:
        await suppression.suppress(s, scope="person", name="Katrin Wolter", reason="objection")
    await _backfill()
    assert [c.last_name for c in await _contacts()] == ["Weidner"]


async def test_suppressing_the_company_removes_its_contacts() -> None:
    await _ingest(("a-1", WOLTER))
    await _backfill()
    async with SessionLocal() as s:
        await suppression.suppress(s, scope="company", name="Pflegeheim Sonnenhof GmbH", reason="objection")
    assert await _contacts() == []


async def test_a_closed_ad_takes_its_contacts_with_its_text() -> None:
    await _ingest(("board:1", WOLTER), source="personio")
    await _backfill()
    async with SessionLocal() as s:
        board = HubAtsBoard(ats="personio", slug="board", discovered_via="test")
        s.add(board)
        await s.flush()
        assert await ats._close(s, board, ["board:1"], "gone from the feed") == 1
        await s.commit()
    assert await _contacts() == []


async def test_a_rule_change_rereads_ads_read_under_older_rules() -> None:
    await _ingest(("a-1", WOLTER))
    await _backfill()
    async with SessionLocal() as s:
        await s.execute(update(HubJobPosting).values(contacts_rules=AD_CONTACT_RULES - 1))
        await s.commit()
    assert (await _backfill())["read"] == 1
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).select_from(HubAdContact)) == 1


def test_the_queue_index_names_the_current_rules_version() -> None:
    from app.domain.hub import models

    index = next(i for i in models.HubJobPosting.__table__.indexes if i.name == "ix_hub_posting_contacts_due")
    assert f"contacts_rules < {AD_CONTACT_RULES}" in str(index.dialect_options["postgresql"]["where"])
    migrations = pathlib.Path(models.__file__).parents[3].joinpath("migrations/versions").glob("0*.py")
    assert any(f"contacts_rules < {AD_CONTACT_RULES}" in p.read_text() for p in migrations)
