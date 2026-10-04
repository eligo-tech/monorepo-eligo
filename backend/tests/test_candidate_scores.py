"""Two numbers, and the difference between them.

The live workspace had 447 candidates of which 446 scored `verification_score
= 0.0`, because the only path that recomputed it was a manual edit — while
the column rendered in the cockpit as "Verif.". What it computed was the
share of key fields with a VALUE, which is completeness.

These tests pin the distinction that makes the number worth showing: a value
is verified when something checked it against a nameable source, and an
import is not that.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.core.database import SessionLocal
from app.domain.candidates import service
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ConfidenceSource, is_evidence
from app.main import app


def _api() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestWhatCountsAsEvidence:
    def test_a_checkable_source_counts(self) -> None:
        for source in (
            ConfidenceSource.DOCUMENT_EXTRACTION,
            ConfidenceSource.HUMAN_VERIFIED,
            ConfidenceSource.PUBLIC_WEB,
            ConfidenceSource.THIRD_PARTY_SOURCE,
        ):
            assert is_evidence(source), source

    def test_what_someone_said_about_themselves_does_not(self) -> None:
        assert not is_evidence(ConfidenceSource.SELF_REPORTED)
        assert not is_evidence(None)
        assert not is_evidence("aus dem Bauch")


async def test_a_bare_record_is_complete_but_unverified() -> None:
    """The import's shape: fields filled, nothing checked."""
    async with _api() as c:
        created = (
            await c.post(
                "/api/v1/candidates",
                json={
                    "full_name": "Ida Import",
                    "email": "ida@example.invalid",
                    "phone": "+49 30 1",
                    "current_title": "Entwicklerin",
                    "current_company": "Beispiel AG",
                    "location": "Berlin",
                    "skills": ["Python"],
                },
            )
        ).json()

    async with SessionLocal() as s:
        row = await s.get(Candidate, uuid.UUID(created["id"]))
        await service.recompute_scores(s, tenant_id=row.tenant_id, candidate=row)
        assert row.completeness_score > 0.4, "seven of thirteen key fields are filled"
        assert row.verification_score == 0.0, "nobody checked any of it"


async def test_a_human_edit_puts_evidence_behind_the_field() -> None:
    async with _api() as c:
        created = (
            await c.post("/api/v1/candidates", json={"full_name": "Eva Edit"})
        ).json()
        # The PATCH body IS the field set — flat, not wrapped.
        r = await c.patch(
            f"/api/v1/candidates/{created['id']}",
            json={"email": "eva@example.invalid"},
        )
        assert r.status_code == 200, r.text
        after = (await c.get(f"/api/v1/candidates/{created['id']}")).json()

    # One of thirteen key fields now has a committed human_verified record.
    assert after["verification_score"] > 0
    assert after["completeness_score"] >= after["verification_score"]


async def test_the_score_is_a_share_of_the_same_field_set() -> None:
    """Both numbers measure the same thirteen fields, so they compare."""
    async with _api() as c:
        created = (
            await c.post("/api/v1/candidates", json={"full_name": "Vera Voll"})
        ).json()
    async with SessionLocal() as s:
        row = await s.get(Candidate, uuid.UUID(created["id"]))
        await service.recompute_scores(s, tenant_id=row.tenant_id, candidate=row)
        # full_name and work_permit ("unknown" does not count) → 1 of 13.
        assert round(row.completeness_score * 13) == 1
        assert row.verification_score == 0.0


async def test_the_list_carries_both_numbers() -> None:
    async with _api() as c:
        await c.post("/api/v1/candidates", json={"full_name": "Lea Liste"})
        rows = (await c.get("/api/v1/candidates")).json()
        assert rows
        assert "verification_score" in rows[0]
        assert "completeness_score" in rows[0]
