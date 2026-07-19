"""Repopulate the candidate record from the real CVs in data/sample_cv/.

Wipes candidate-scoped rows, then runs each PDF through the full extraction +
verification pipeline (OpenAI extractor → laufwise gate → persist), so the
complete aiFind field set lands in the database and the Candidate-360 dossier
fills in.

Run from the backend/ directory (so .env is picked up):

    .venv/bin/python -m scripts.repopulate_cvs
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.database import SessionLocal, create_all
from app.domain.candidates.models import Candidate
from app.domain.documents import service as documents_service
from app.domain.documents.gate import PreconditionFailed
from app.domain.documents.models import CandidateDocument
from app.domain.matching.models import MatchReceipt
from app.domain.pipeline.models import Application
from app.domain.verification.models import EnrichmentRecord, Receipt

CV_DIR = Path(__file__).resolve().parents[2] / "data" / "sample_cv"

# Non-empty extended fields we report coverage on.
EXT_FIELDS = (
    "linkedin_url", "city", "country", "industry", "date_of_birth",
    "languages", "education", "working_experience", "motivation",
    "notice_period", "availability", "current_salary",
)


async def _wipe() -> None:
    """Delete candidate-scoped rows in FK-safe order (jobs/companies kept)."""
    async with SessionLocal() as s:
        for model in (Application, MatchReceipt, EnrichmentRecord, Receipt, CandidateDocument, Candidate):
            await s.execute(delete(model))
        await s.commit()
    print("· wiped applications, match_receipts, enrichment_records, receipts, candidate_documents, candidates")


def _filled(c: Candidate) -> int:
    return sum(1 for f in EXT_FIELDS if getattr(c, f, None) not in (None, [], ""))


async def _ingest_one(pdf: Path, tenant_id) -> tuple[str, str]:
    """Return (status, detail) for one CV. Fresh session so a failure is isolated."""
    async with SessionLocal() as s:
        try:
            result = await documents_service.extract_cv(
                s,
                filename=pdf.name,
                content=pdf.read_bytes(),
                tenant_id=tenant_id,
                persist=True,
            )
        except PreconditionFailed as exc:
            return "skip", str(exc)
        except Exception as exc:  # noqa: BLE001 — report, keep going
            return "error", f"{type(exc).__name__}: {exc}"

        if not result.candidate_id:
            return "skip", "; ".join(result.review_items) or "not persisted"

        row = await s.get(Candidate, result.candidate_id)
        ext = _filled(row) if row else 0
        return "ok", f"{row.full_name if row else '?'} · {ext}/{len(EXT_FIELDS)} ext fields"


async def _resolve_tenant():
    """Which tenant to load into. An arg (clerk_org_id) targets that org; else the
    single existing org tenant if there is exactly one; else the default tenant."""
    from app.domain.tenants import service as tenants_service
    from app.domain.tenants.models import Tenant

    async with SessionLocal() as s:
        if len(sys.argv) > 1:
            t = await tenants_service.get_or_create(s, clerk_org_id=sys.argv[1])
            return t.id, t.clerk_org_id
        rows = (await s.execute(select(Tenant))).scalars().all()
        if len(rows) == 1:
            return rows[0].id, rows[0].clerk_org_id
        if len(rows) > 1:
            listing = ", ".join(t.clerk_org_id for t in rows)
            sys.exit(f"multiple org tenants — pass one explicitly: {listing}")
        return settings.default_tenant_id, "default"


async def main() -> None:
    pdfs = sorted(CV_DIR.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"no CVs found in {CV_DIR}")

    await create_all()  # ensure new tables (e.g. candidate_documents) exist
    tenant_id, tenant_label = await _resolve_tenant()
    print(
        f"CVs: {len(pdfs)}  ·  provider: {settings.llm_provider}  ·  "
        f"db: {settings.safe_database_url}  ·  tenant: {tenant_label} ({tenant_id})"
    )
    await _wipe()

    counts = {"ok": 0, "skip": 0, "error": 0}
    for i, pdf in enumerate(pdfs, 1):
        status, detail = await _ingest_one(pdf, tenant_id)
        counts[status] += 1
        mark = {"ok": "✓", "skip": "–", "error": "✗"}[status]
        print(f"  {mark} [{i:>2}/{len(pdfs)}] {pdf.name[:42]:42}  {detail}")

    async with SessionLocal() as s:
        total = await s.scalar(select(func.count()).select_from(Candidate))
    print(f"\ndone — created {counts['ok']}, skipped {counts['skip']}, errored {counts['error']}  ·  candidates now in DB: {total}")


if __name__ == "__main__":
    asyncio.run(main())
