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
from sqlalchemy import desc, select

from app.domain.candidates import service as candidates_service
from app.domain.candidates.employment import normalize_employment_form
from app.domain.candidates.schemas import CandidateCreate
from app.domain.common.enums import DocumentKind
from app.domain.documents import gate, parser
from app.domain.documents.models import CandidateDocument
from app.domain.documents.extraction import get_cv_extractor
from app.domain.documents.extraction.base import (
    CVSections,
    FIELD_LABELS,
    FIELD_ORDER,
    TRANSCRIPT_FIELD_ORDER,
)
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


def _build_candidate(
    tenant_id: uuid.UUID,
    fields: list[ExtractedField],
    sections: CVSections,
) -> CandidateCreate:
    """Assemble a CandidateCreate from the accepted (high-confidence) fields —
    now covering the full aiFind field set the Candidate row can store, plus the
    structured per-entry work history + education (dates + highlights)."""
    acc = _accepted(fields)
    g = acc.get
    # Structured history takes precedence; fall back to the flat list fields.
    work_history = [r.as_dict() for r in sections.work_history]
    education = [e.as_dict() for e in sections.education] or _split_list(g("education"))
    return CandidateCreate(
        tenant_id=tenant_id,
        full_name=_full_name(acc) or "Unbekannt (aus CV)",
        email=g("email"),
        phone=g("phone"),
        current_title=g("current_title"),
        current_company=g("current_company"),
        location=g("location"),
        skills=_split_list(g("skills")) or [],
        work_history=work_history,
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
        # One label from a CV is one industry — splitting on the comma would
        # cut "Pharma, MedTech und Gesundheitsbranche" in half.
        industries=[g("industry")] if g("industry") else [],
        employment_type=g("employment_type"),
        employment_form=normalize_employment_form(g("employment_type")),
        willing_to_relocate=g("willing_to_relocate"),
        notice_period=g("notice_period"),
        availability=g("availability"),
        total_years_experience=g("total_years_experience"),
        current_salary=_to_int(g("current_salary")),
        salary_expectation=_to_int(g("expected_salary")),
        languages=_split_list(g("languages")),
        education=education,
        working_experience=_split_list(g("working_experience")),
        motivation=g("motivation"),
        source=g("source"),
    )


def _run_extractor(text: str) -> tuple[list[ExtractedField], CVSections, str]:
    """Extract via the configured provider in a SINGLE call (flat fields +
    structured history), falling back to the heuristic parser on any runtime
    error so the request never fails on the LLM."""
    extractor = get_cv_extractor()
    extract_all = getattr(extractor, "extract_all", None)
    try:
        if extract_all is not None:
            result = extract_all(text)  # one LLM round-trip
            return result.fields, result.sections, extractor.name
        # Providers without structured support (heuristic) → flat fields only.
        return extractor.extract(text), CVSections(), extractor.name
    except Exception as exc:
        logger.warning("extractor %s failed (%s) — falling back to heuristic", extractor.name, exc)
        return parser.extract_cv_fields(text), CVSections(), "heuristic (fallback)"


def _ground_sections(text: str, sections: CVSections) -> tuple[CVSections, int, int]:
    """Keep only the roles/education entries that are grounded in the CV text
    (their company/title/institution/degree actually appears in the source).

    This is the anti-hallucination guardrail: a fabricated employer or degree —
    the failure mode that erodes trust — is dropped rather than persisted.
    Returns the filtered sections plus counts of what was dropped."""
    kept_roles = [
        r for r in sections.work_history
        if gate.is_grounded(r.company, text) or gate.is_grounded(r.title, text)
    ]
    kept_edu = [
        e for e in sections.education
        if gate.is_grounded(e.institution, text) or gate.is_grounded(e.degree, text)
    ]
    dropped_roles = len(sections.work_history) - len(kept_roles)
    dropped_edu = len(sections.education) - len(kept_edu)
    return CVSections(work_history=kept_roles, education=kept_edu), dropped_roles, dropped_edu


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

    # ── Extract (vendor-neutral, single call) → confidence-gate via the agent.
    extracted, raw_sections, extractor_name = _run_extractor(text)
    notes.append(f"extracted via {extractor_name}")

    # ── Anti-hallucination: drop any role/education not grounded in the CV text,
    #    then assert (laufwise postcondition) that nothing ungrounded slipped by.
    sections, dropped_roles, dropped_edu = _ground_sections(text, raw_sections)
    sec_post = gate.evaluate(
        gate.SECTIONS_POSTCONDITIONS,
        {"roles": {"ungrounded": dropped_roles}, "education": {"ungrounded": dropped_edu}},
    )
    notes += [o.as_note() for o in sec_post]
    review_items += [o.reason or o.expr for o in sec_post if not o.ok and o.reason]
    if sections.work_history or sections.education:
        notes.append(
            f"structured: {len(sections.work_history)} role(s), "
            f"{len(sections.education)} education entr(y/ies) grounded"
        )

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
            session, data=_build_candidate(tenant_id, extracted, sections)
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

        # ── Keep the original CV as evidence, shown next to the parsed record.
        await store_document(
            session,
            tenant_id=tenant_id,
            candidate_id=candidate_id,
            filename=filename,
            content=content,
            content_type="application/pdf",
        )
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


async def extract_transcript(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    filename: str,
    content: bytes,
    content_type: str,
) -> CVExtractionResult:
    """Read a Gesprächstranskript for the qualification fields — and PROPOSE.

    The same seam as the CV pass (precondition → extract → confidence gate),
    with one deliberate difference at the end: **nothing is written.**

    A CV creates a candidate that did not exist, so there is nothing to
    overwrite. A transcript lands on a record a recruiter has already worked
    on, and "Mindestgehalt 92.000" read out of a conversation is a model's
    reading of hedged speech. Writing it through `update_candidate` would
    stamp it `HUMAN_VERIFIED`, confidence 1.0 — the receipt would then claim a
    human asserted a number nobody checked. So the extraction comes back as
    proposals with their confidence, the recruiter confirms what is right, and
    the ordinary PATCH records it as the human edit it then is.

    The file itself is stored either way: keeping evidence asserts nothing.
    """
    candidate = await candidates_service.get_candidate(
        session, tenant_id=tenant_id, candidate_id=candidate_id
    )
    if candidate is None:
        raise PreconditionFailed("candidate not found")

    text = _document_text(content, content_type)
    notes: list[str] = []
    review_items: list[str] = []

    pre = gate.evaluate(gate.PRECONDITIONS, {"document": {"text_chars": len(text)}})
    notes += [o.as_note() for o in pre]
    if any(not o.ok for o in pre):
        reason = next((o.reason for o in pre if not o.ok), "precondition failed")
        raise PreconditionFailed(reason or "precondition failed")

    extracted, extractor_name = _run_qualification_extractor(text)
    notes.append(f"gelesen via {extractor_name}")
    if not extracted:
        review_items.append(
            "keine Felder aus dem Transkript gelesen — bitte manuell erfassen"
        )

    for f in extracted:
        if f.confidence < HUMAN_REVIEW_THRESHOLD:
            label = FIELD_LABELS.get(f.field, f.field)
            review_items.append(f"{label}: unsicher gelesen ({f.confidence:.0%})")

    notes.append("Vorschläge — nichts wurde in den Datensatz geschrieben")

    await store_document(
        session,
        tenant_id=tenant_id,
        candidate_id=candidate_id,
        filename=filename,
        content=content,
        content_type=content_type,
        kind=DocumentKind.TRANSKRIPT.value,
    )

    order = {name: i for i, name in enumerate(TRANSCRIPT_FIELD_ORDER)}
    fields = [
        CVField(
            field=f.field,
            label=FIELD_LABELS.get(f.field, f.field),
            value=f.value,
            confidence=round(f.confidence, 2),
            needs_review=f.confidence < HUMAN_REVIEW_THRESHOLD,
        )
        for f in sorted(extracted, key=lambda f: order.get(f.field, len(order)))
    ]
    return CVExtractionResult(
        document_name=filename,
        fields=fields,
        review_items=list(dict.fromkeys(review_items)),
        notes=notes,
        candidate_id=candidate_id,
        text_chars=len(text),
    )


def _document_text(content: bytes, content_type: str) -> str:
    """A transcript arrives as a PDF export or as plain text — both are read.

    Anything else is refused at the router, so a silently empty parse of a
    .docx cannot look like "the conversation said nothing".
    """
    if content_type == "text/plain":
        return content.decode("utf-8", errors="replace")
    return parser.pdf_to_text(content)


def _run_qualification_extractor(text: str) -> tuple[list[ExtractedField], str]:
    """Ask the configured provider to read the transcript.

    A provider that cannot (the heuristic fallback) yields NOTHING rather than
    guessing: the CV regexes look for a salary figure and would happily read
    the client's budget, a year, or a phone number as a candidate's floor. An
    empty form the recruiter fills in is honest; a wrong number is not.
    """
    extractor = get_cv_extractor()
    read = getattr(extractor, "extract_qualification", None)
    if read is None:
        return [], f"{extractor.name} (kann keine Transkripte lesen)"
    try:
        return read(text), extractor.name
    except Exception as exc:
        logger.warning("transcript extractor %s failed (%s)", extractor.name, exc)
        return [], f"{extractor.name} (Fehler: {type(exc).__name__})"


async def store_document(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    filename: str,
    content: bytes,
    content_type: str = "application/pdf",
    kind: str = DocumentKind.CV.value,
) -> CandidateDocument:
    """Persist an uploaded file so it can be shown next to the parsed record."""
    doc = CandidateDocument(
        tenant_id=tenant_id,
        candidate_id=candidate_id,
        kind=kind,
        filename=filename,
        content_type=content_type,
        byte_size=len(content),
        content=content,
    )
    session.add(doc)
    await session.commit()
    return doc


async def get_latest_document(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    kind: str | None = DocumentKind.CV.value,
) -> CandidateDocument | None:
    """The most recent document of one kind for a candidate (None if none).

    Defaults to the CV. It used to mean "the newest file", which was the same
    thing while CVs were all there was — the first Zeugnis uploaded would have
    started being served as the candidate's CV.
    """
    query = select(CandidateDocument).where(
        CandidateDocument.tenant_id == tenant_id,
        CandidateDocument.candidate_id == candidate_id,
    )
    if kind is not None:
        query = query.where(CandidateDocument.kind == kind)
    result = await session.execute(
        query.order_by(desc(CandidateDocument.created_at)).limit(1)
    )
    return result.scalar_one_or_none()


async def list_documents(
    session: AsyncSession, *, tenant_id: uuid.UUID, candidate_id: uuid.UUID
) -> list[CandidateDocument]:
    """Every file on a candidate, newest first. Metadata only is the caller's
    job — the rows carry their bytes and must not be serialized wholesale."""
    result = await session.execute(
        select(CandidateDocument)
        .where(
            CandidateDocument.tenant_id == tenant_id,
            CandidateDocument.candidate_id == candidate_id,
        )
        .order_by(desc(CandidateDocument.created_at))
    )
    return list(result.scalars())


async def get_document(
    session: AsyncSession, *, tenant_id: uuid.UUID, document_id: uuid.UUID
) -> CandidateDocument | None:
    return await session.scalar(
        select(CandidateDocument).where(
            CandidateDocument.tenant_id == tenant_id,
            CandidateDocument.id == document_id,
        )
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