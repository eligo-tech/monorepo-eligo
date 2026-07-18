"""CV extraction orchestration.

laufwise-style contract order:
    precondition (document has text) → extract (vendor-neutral: OpenAI or the
    heuristic fallback) → agent confidence-gating → postcondition (result vs
    real checks) → optionally persist → postcondition (re-query the DB and prove
    the candidate row landed) + receipts via the verification gate.

The LLM only proposes fields. Every value it returns is decided by the
confidence threshold and the laufwise pre/postcondition gate — checks over real
state, never over model text.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.document_extraction import (
    HUMAN_REVIEW_THRESHOLD,
    DocumentExtractionAgent,
    DocumentExtractionInput,
    ExtractedField,
)
from app.core.logging import get_logger
from app.domain.candidates import service as candidates_service
from app.domain.candidates.schemas import CandidateCreate
from app.domain.documents import gate, parser
from app.domain.documents.extraction import get_cv_extractor
from app.domain.documents.extraction.base import FIELD_LABELS, FIELD_ORDER
from app.domain.documents.gate import GateOutcome, PreconditionFailed
from app.domain.documents.schemas import CVExtractionResult, CVField

logger = get_logger(__name__)

_IDENTIFYING = ("full_name", "email", "first_name", "last_name")


def _order_key(field: str) -> int:
    """Stable aiFind-style display order; unknown fields sort last."""
    return FIELD_ORDER.index(field) if field in FIELD_ORDER else len(FIELD_ORDER)


def _accepted(fields: list[ExtractedField]) -> dict[str, str]:
    """Fields at/above the confidence threshold, keyed by field name."""
    return {f.field: f.value for f in fields if f.confidence >= HUMAN_REVIEW_THRESHOLD}


def _extracted_email(fields: list[ExtractedField]) -> str | None:
    return next((f.value for f in fields if f.field == "email"), None)


def _full_name(acc: dict[str, str]) -> str | None:
    """Prefer an explicit full_name; else compose from first/last."""
    if acc.get("full_name"):
        return acc["full_name"]
    parts = [acc.get("first_name"), acc.get("last_name")]
    composed = " ".join(p for p in parts if p)
    return composed or None


def _split_list(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [s.strip() for s in value.replace(";", ",").split(",") if s.strip()]
    return items or None


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    digits = "".join(c for c in value if c.isdigit())
    return int(digits) if digits else None


def _build_candidate(tenant_id: uuid.UUID, fields: list[ExtractedField]) -> CandidateCreate:
    """Assemble a CandidateCreate from the accepted (high-confidence) fields —
    now covering the full aiFind field set the Candidate row can store."""
    acc = _accepted(fields)
    g = acc.get
    return CandidateCreate(
        tenant_id=tenant_id,
        full_name=_full_name(acc) or "Unbekannt (aus CV)",
        email=g("email"),
        phone=g("phone"),
        current_title=g("current_title"),
        current_company=g("current_company"),
        location=g("location"),
        skills=_split_list(g("skills")) or [],
        # Extended profile
        first_name=g("first_name"),
        last_name=g("last_name"),
        sex=g("sex"),
        name_prefix=g("name_prefix"),
        date_of_birth=g("date_of_birth"),
        street=g("street"),
        postal_code=g("postal_code"),
        city=g("city"),
        country=g("country"),
        linkedin_url=g("linkedin_url"),
        xing_url=g("xing_url"),
        industry=g("industry"),
        employment_type=g("employment_type"),
        willing_to_relocate=g("willing_to_relocate"),
        notice_period=g("notice_period"),
        availability=g("availability"),
        total_years_experience=g("total_years_experience"),
        current_salary=_to_int(g("current_salary")),
        salary_expectation=_to_int(g("expected_salary")),
        languages=_split_list(g("languages")),
        education=_split_list(g("education")),
        working_experience=_split_list(g("working_experience")),
        motivation=g("motivation"),
        source=g("source"),
    )


def _run_extractor(text: str) -> tuple[list[ExtractedField], str]:
    """Extract via the configured provider; fall back to the heuristic parser on
    any runtime error so the request never fails on the LLM."""
    extractor = get_cv_extractor()
    try:
        return extractor.extract(text), extractor.name
    except Exception as exc:
        logger.warning("extractor %s failed (%s) — falling back to heuristic", extractor.name, exc)
        return parser.extract_cv_fields(text), "heuristic (fallback)"


async def extract_cv(
    session: AsyncSession,
    *,
    filename: str,
    content: bytes,
    tenant_id: uuid.UUID,
    persist: bool,
) -> CVExtractionResult:
    text = parser.pdf_to_text(content)
    notes: list[str] = []
    review_items: list[str] = []

    # ── Precondition: the document must have extractable text.
    pre = gate.evaluate(gate.PRECONDITIONS, {"document": {"text_chars": len(text)}})
    notes += [o.as_note() for o in pre]
    if any(not o.ok for o in pre):
        reason = next((o.reason for o in pre if not o.ok), "precondition failed")
        if persist:
            raise PreconditionFailed(reason or "precondition failed")
        review_items.append(reason or "precondition failed")
        return CVExtractionResult(
            document_name=filename, fields=[], review_items=review_items,
            notes=notes, candidate_id=None, text_chars=len(text),
        )

    # ── Extract (vendor-neutral) → confidence-gate via the agent.
    extracted, extractor_name = _run_extractor(text)
    notes.append(f"extracted via {extractor_name}")

    agent = DocumentExtractionAgent()
    candidate_id: uuid.UUID | None = None
    accepted = _accepted(extracted)

    # ── Postconditions over the result (checks on real values, not model text).
    post_checks = list(gate.POSTCONDITIONS)
    email_value = _extracted_email(extracted)
    if email_value is None:
        # Drop the e-mail check when no e-mail was proposed — nothing to verify.
        post_checks = [c for c in post_checks if not c[0].startswith("email.")]
    post_fixture = {
        "email": {"valid": gate.email_is_valid(email_value)},
        "accepted": list(accepted.keys()),
    }
    post = gate.evaluate(post_checks, post_fixture)
    notes += [o.as_note() for o in post]
    review_items += [o.reason or o.expr for o in post if not o.ok and o.reason]

    # ── Persist path.
    if persist:
        identifiers = [k for k in _IDENTIFYING if k in accepted]
        persist_pre = gate.evaluate(
            gate.PERSIST_PRECONDITION, {"identifiers": identifiers}
        )
        notes += [o.as_note() for o in persist_pre]
        if any(not o.ok for o in persist_pre):
            reason = next((o.reason for o in persist_pre if not o.ok), "persist precondition failed")
            raise PreconditionFailed(reason or "persist precondition failed")

        created = await candidates_service.create_candidate(
            session, data=_build_candidate(tenant_id, extracted)
        )
        candidate_id = created.id
        agent_result = await agent.run(
            DocumentExtractionInput(
                tenant_id=tenant_id, candidate_id=candidate_id,
                document_name=filename, fields=extracted,
            )
        )
        await agent.commit(session, agent_result)
        review_items += agent_result.review_items

        # ── Postcondition: re-query the system-of-record and prove the write
        #    landed (the laufwise "verify against real state after execute" step).
        notes += [o.as_note() for o in await _verify_persisted(session, tenant_id, candidate_id, accepted.get("email"))]
    else:
        agent_result = await agent.run(
            DocumentExtractionInput(
                tenant_id=tenant_id, candidate_id=uuid.uuid4(),
                document_name=filename, fields=extracted,
            )
        )
        review_items += agent_result.review_items

    fields = [
        CVField(
            field=f.field,
            label=FIELD_LABELS.get(f.field, f.field),
            value=f.value,
            confidence=round(f.confidence, 2),
            needs_review=f.confidence < HUMAN_REVIEW_THRESHOLD,
        )
        for f in sorted(extracted, key=lambda f: _order_key(f.field))
    ]

    return CVExtractionResult(
        document_name=filename,
        fields=fields,
        # De-duplicate while preserving order.
        review_items=list(dict.fromkeys(review_items)),
        notes=notes,
        candidate_id=candidate_id,
        text_chars=len(text),
    )


async def _verify_persisted(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    expected_email: str | None,
) -> list[GateOutcome]:
    """Re-query the candidate row and check it actually exists (and matches)."""
    row = await candidates_service.get_candidate(
        session, tenant_id=tenant_id, candidate_id=candidate_id
    )
    fixture = {
        "candidate": {
            "exists": row is not None,
            "email": (row.email if row else None),
        }
    }
    checks: list[tuple[str, str | None]] = [
        ("candidate.exists == true", "candidate row not found after write"),
    ]
    if expected_email:
        checks.append(
            (f'candidate.email == "{expected_email}"', "persisted e-mail does not match")
        )
    return gate.evaluate(checks, fixture)