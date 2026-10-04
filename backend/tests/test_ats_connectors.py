"""The ATS seam, exercised without the vendor that happened to be first.

aiFind was the first integration and for a while its name was the importer's,
the runner's, the credential store's and the settings screen's. These tests
pin the thing that replaced that: a registry of connectors, a neutral record
shape, and an importer that takes the source as DATA.

The fake connector below is the point. If the product can import a book from
a system invented inside a test file, then nothing downstream depends on
which system a row came from — which is exactly the claim being made.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.domain.atsimport import factory
from app.domain.atsimport import service as importer
from app.domain.atsimport.connectors.base import (
    AtsConnector,
    AtsExport,
    Credentials,
    SourcedCandidate,
    SourcedCompany,
    SourcedJob,
    SourcedManager,
)
from app.domain.candidates.models import Candidate
from app.domain.companies.models import Company
from app.domain.jobs.models import Job

TENANT = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


class FakeAts:
    """A recruiting system that exists only here."""

    key = "fake-ats"
    label = "Fake ATS"
    hint = "Erfunden für diesen Test"
    mode = "pull"
    needs = ("secret",)

    def __init__(self) -> None:
        self.calls: list[bool] = []

    async def fetch(
        self, credentials: Credentials, *, with_details: bool = True
    ) -> AtsExport:
        self.calls.append(with_details)
        if credentials.secret != "token-123":
            raise RuntimeError("fake-ats login rejected")
        company = SourcedCompany(external_id="C1", name="Beispiel GmbH")
        manager = SourcedManager(
            external_id="M1",
            full_name="Mara Muster",
            job_title="Head of Engineering",
            company_external_id="C1",
            email="mara@beispiel.invalid",
        )
        return AtsExport(
            companies=[company],
            managers=[manager],
            jobs=[
                SourcedJob(
                    external_id="J1",
                    title="Backend-Entwicklerin",
                    is_open=True,
                    company=company,
                    manager=manager,
                )
            ],
            candidates=[
                SourcedCandidate(
                    external_id="K1", full_name="Kim Kandidat", skills=["Go"]
                )
            ],
        )


def test_the_protocol_is_structural() -> None:
    """A connector is anything with the shape — no base class to inherit."""
    assert isinstance(FakeAts(), AtsConnector)


class TestRegistry:
    def test_it_describes_what_a_settings_form_needs(self) -> None:
        described = {row["key"]: row for row in factory.describe()}
        assert "aifind" in described, "the first integration is still one of them"
        assert described["aifind"]["label"]
        assert described["aifind"]["needs"]

    def test_an_unknown_source_fails_loudly(self) -> None:
        # A typo in a workspace's configuration must not quietly import
        # nothing — that looks exactly like an empty ATS.
        with pytest.raises(ValueError, match="unknown ATS source"):
            factory.get_connector("ats-that-does-not-exist")

    def test_the_key_is_what_gets_written_to_rows(self) -> None:
        assert factory.get_connector("aifind").key == "aifind"

    def test_a_file_source_is_listed_but_never_fetched(self) -> None:
        """CSV/Excel is an option, not something the scheduler can start.

        It has no login to schedule and the bytes arrive with the request,
        so it must appear in the list a recruiter chooses from and nowhere
        near the runner or the credential store.
        """
        described = {row["key"]: row for row in factory.describe()}
        assert described["datei-import"]["mode"] == "file"
        assert described["datei-import"]["needs"] == []
        assert "datei-import" not in factory.pull_sources()
        with pytest.raises(ValueError, match="uploaded"):
            factory.get_connector("datei-import")

    def test_a_pull_source_is_both_listed_and_fetchable(self) -> None:
        described = {row["key"]: row for row in factory.describe()}
        assert described["aifind"]["mode"] == "pull"
        assert "aifind" in factory.pull_sources()


@pytest.fixture
def registered() -> FakeAts:
    """Register the fake for one test, then take it out again."""
    connector = FakeAts()
    factory._SOURCES[connector.key] = connector
    try:
        yield connector
    finally:
        factory._SOURCES.pop(connector.key, None)


async def test_a_book_from_an_invented_system_imports_end_to_end(
    registered: FakeAts,
) -> None:
    connector = factory.get_connector("fake-ats")
    export = await connector.fetch(Credentials(secret="token-123"))
    assert export.counts() == {
        "companies": 1,
        "managers": 1,
        "jobs": 1,
        "candidates": 1,
    }

    async with SessionLocal() as s:
        summary = await importer.import_export(
            s, tenant_id=TENANT, export=export, source=connector.key
        )
    assert summary.companies_created == 1
    assert summary.managers_created == 1
    assert summary.jobs_created == 1
    assert summary.candidates_created == 1

    async with SessionLocal() as s:
        company = await s.scalar(select(Company).where(Company.tenant_id == TENANT))
        assert company.source == "fake-ats", "the row names the system it came from"


async def test_a_second_run_updates_rather_than_doubles(registered: FakeAts) -> None:
    connector = factory.get_connector("fake-ats")
    export = await connector.fetch(Credentials(secret="token-123"))
    async with SessionLocal() as s:
        await importer.import_export(
            s, tenant_id=TENANT, export=export, source=connector.key
        )
        second = await importer.import_export(
            s, tenant_id=TENANT, export=export, source=connector.key
        )
    assert second.companies_created == 0
    assert second.jobs_created == 0
    async with SessionLocal() as s:
        assert await s.scalar(
            select(func.count(Company.id)).where(Company.tenant_id == TENANT)
        ) == 1


async def test_two_systems_in_one_workspace_do_not_collide(
    registered: FakeAts,
) -> None:
    """The reason `source` is an argument and not a module constant.

    Both systems number their records from scratch, so "C1" means a different
    company in each. Recognising its own output means recognising it PER
    SOURCE — otherwise the second import would overwrite the first one's rows
    and the two books would merge into one wrong one.
    """
    export = await FakeAts().fetch(Credentials(secret="token-123"))
    other = AtsExport(
        companies=[SourcedCompany(external_id="C1", name="Andere AG")],
        candidates=[
            SourcedCandidate(external_id="K1", full_name="Toni Zweitquelle")
        ],
    )
    async with SessionLocal() as s:
        await importer.import_export(
            s, tenant_id=TENANT, export=export, source="fake-ats"
        )
        await importer.import_export(
            s, tenant_id=TENANT, export=other, source="other-ats"
        )

    async with SessionLocal() as s:
        names = sorted(
            (await s.scalars(select(Company.name).where(Company.tenant_id == TENANT)))
        )
        assert names == ["Andere AG", "Beispiel GmbH"]
        people = sorted(
            (
                await s.scalars(
                    select(Candidate.full_name).where(Candidate.tenant_id == TENANT)
                )
            )
        )
        assert people == ["Kim Kandidat", "Toni Zweitquelle"]


async def test_the_detail_pass_can_be_skipped(registered: FakeAts) -> None:
    await registered.fetch(Credentials(secret="token-123"), with_details=False)
    assert registered.calls == [False]


async def test_a_job_keeps_its_client(registered: FakeAts) -> None:
    export = await FakeAts().fetch(Credentials(secret="token-123"))
    async with SessionLocal() as s:
        await importer.import_export(
            s, tenant_id=TENANT, export=export, source="fake-ats"
        )
    async with SessionLocal() as s:
        job = await s.scalar(select(Job).where(Job.tenant_id == TENANT))
        company = await s.get(Company, job.client_company_id)
        assert company.name == "Beispiel GmbH"
