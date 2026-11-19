"""The cover sheet: which values go on the page, which files go behind it,
and the record that it left the workspace (ELI-20).

Layer: application/presentation (layer 6), domain `presentation`. Reads the
record, writes nothing to it but a receipt.

**Fields are copied 1:1.** No model writes a sentence for the client: every
value on the page is a field a recruiter filled or confirmed in the
Qualifikationsgespräch set. An empty field leaves its row off the page — the
preview names it, so the recruiter can complete the record first or send it
as it is. Nothing is invented to fill a gap.

**A download is a disclosure.** The candidate's data goes to a client, so it
leaves a READ receipt naming the candidate, the variant, the process and the
attached files by id — references only (backend/CLAUDE.md §2.1), never a
value — in the ledger, not in the record's change history (WRITE only).
"""

from __future__ import annotations

import io
import re
import uuid
import xml.etree.ElementTree as ET  # noqa: S405 — DOCTYPE/ENTITY refused before parsing
from dataclasses import dataclass

from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.candidates.models import Candidate
from app.domain.common.enums import DocumentKind, ReceiptAction
from app.domain.documents import service as documents_service
from app.domain.documents.models import CandidateDocument
from app.domain.jobs.models import Job
from app.domain.pipeline.models import Application
from app.domain.presentation import render
from app.domain.presentation.models import DEFAULT_PRIMARY_COLOR, WorkspaceBranding
from app.domain.presentation.schemas import (
    BrandingRead,
    BrandingUpdate,
    CoverSheetAttachment,
    CoverSheetPreview,
    CoverSheetVariant as V,
)
from app.domain.verification import service as verification

#: The receipt's `agent`: the cover sheet, not a model.
RECEIPT_AGENT = "cover-sheet"
LOGO_TYPES = {"image/png", "image/jpeg"}
LOGO_MAX_BYTES = 1_000_000

#: Every label the page can carry, in page order — also what `missing` says.
POSITION = "Angestrebte Position"
SUMMARY = "Zusammenfassung"
STACK = "Technologie Stack"
SALARY = "Gehaltsvorstellung"
NOTICE = "Kündigungsfrist"
QUALIFICATIONS = "Qualifikationen"
LANGUAGES = "Sprachkenntnisse"
MOTIVATION = "Wechselmotivation"

_KINDS_BY_VARIANT: dict[V, tuple[str, ...]] = {
    V.COVER: (),
    V.ANONYMOUS: (),
    V.COVER_CV: (DocumentKind.CV.value,),
    V.COVER_CV_REFERENCES: (
        DocumentKind.CV.value,
        DocumentKind.ZEUGNIS.value,
        DocumentKind.ZERTIFIKAT.value,
    ),
}


class NotFound(Exception):
    """The candidate, or the process named, is not in this workspace."""


class InvalidLogo(ValueError):
    pass


class RenderFailed(RuntimeError):
    """The page could not be drawn. Carries no candidate text."""


# ── Branding ──────────────────────────────────────────────────────────────


async def get_branding(session: AsyncSession, *, tenant_id: uuid.UUID) -> WorkspaceBranding | None:
    return await session.scalar(
        select(WorkspaceBranding).where(WorkspaceBranding.tenant_id == tenant_id)
    )


def branding_read(row: WorkspaceBranding | None) -> BrandingRead:
    if row is None:
        return BrandingRead(primary_color=DEFAULT_PRIMARY_COLOR)
    return BrandingRead(
        company_name=row.company_name,
        company_line=row.company_line,
        legal_text=row.legal_text,
        primary_color=row.primary_color,
        contact_phone=row.contact_phone,
        has_logo=row.logo is not None,
        has_header_icon=row.header_icon is not None,
        updated_at=row.updated_at,
        updated_by_name=row.updated_by_name,
    )


async def _row(session: AsyncSession, tenant_id: uuid.UUID) -> WorkspaceBranding:
    row = await get_branding(session, tenant_id=tenant_id)
    if row is None:
        row = WorkspaceBranding(tenant_id=tenant_id, primary_color=DEFAULT_PRIMARY_COLOR)
        session.add(row)
    return row


async def save_branding(
    session: AsyncSession, *, tenant_id: uuid.UUID, data: BrandingUpdate, editor: str
) -> WorkspaceBranding:
    row = await _row(session, tenant_id)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    row.primary_color = data.primary_color.upper()
    row.updated_by_name = editor
    await session.commit()
    await session.refresh(row)
    return row


def check_logo(content: bytes, content_type: str | None) -> str:
    """The logo's media type, or InvalidLogo. Opened, not trusted by its
    name: a file the renderer cannot read would fail every later download."""
    if content_type not in LOGO_TYPES:
        raise InvalidLogo("Nur PNG oder JPEG.")
    if len(content) > LOGO_MAX_BYTES:
        raise InvalidLogo("Höchstens 1 MB.")
    try:
        w, h = ImageReader(io.BytesIO(content)).getSize()
    except Exception as exc:  # noqa: BLE001 — any decoder error means "not an image"
        raise InvalidLogo("Die Datei ist kein lesbares Bild.") from exc
    if not w or not h:
        raise InvalidLogo("Die Datei ist kein lesbares Bild.")
    return content_type


async def set_logo(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    content: bytes,
    content_type: str | None,
    editor: str,
) -> WorkspaceBranding:
    kind = check_logo(content, content_type)
    row = await _row(session, tenant_id)
    row.logo, row.logo_content_type, row.updated_by_name = content, kind, editor
    await session.commit()
    await session.refresh(row)
    return row


async def clear_logo(session: AsyncSession, *, tenant_id: uuid.UUID, editor: str) -> None:
    row = await get_branding(session, tenant_id=tenant_id)
    if row is not None:
        row.logo, row.logo_content_type, row.updated_by_name = None, None, editor
        await session.commit()


# ── The header icon (ELI-55) ──────────────────────────────────────────────

SVG = "image/svg+xml"
HEADER_ICON_TYPES = {"image/png", "image/jpeg", SVG}
_SVG_NS = "http://www.w3.org/2000/svg"
#: Shapes and their grouping. No <a>, <use>, <image>, <foreignObject>,
#: <script>, <animate>, filters or text — nothing that links, loads or runs.
_SVG_ELEMENTS = {
    "svg", "g", "defs", "style", "path", "rect", "circle", "ellipse",
    "polygon", "polyline", "line",
}
#: Real logos nest a handful of groups; this keeps recursion far from Python's limit.
_SVG_MAX_DEPTH = 64
_DRAWN = {"path","rect", "circle", "ellipse", "polygon", "polyline", "line"}
#: Geometry and paint only. No `style` attribute, no `href`, no `on*`.
_SVG_ATTRIBUTES = {
    "viewBox", "width", "height", "x", "y", "rx", "ry", "cx", "cy", "r",
    "x1", "y1", "x2", "y2", "d", "points", "transform", "class", "id",
    "fill", "fill-rule", "fill-opacity", "clip-rule", "opacity", "stroke",
    "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit",
    "stroke-opacity", "preserveAspectRatio",
}
#: A value or a class rule: no parentheses (so no url()), no "@", no quotes.
_SAFE_VALUE = re.compile(r"^[\w\s.,#%:;{}\-]*$")
#: transform="translate(160 214.68) rotate(180)" needs parentheses.
_SAFE_TRANSFORM = re.compile(r"^(\s*(matrix|translate|scale|rotate|skewX|skewY)\([\d\s.,eE+\-]*\)\s*)*$")


def _safe_attribute(name: str, value: str) -> bool:
    if name not in _SVG_ATTRIBUTES:
        return False
    pattern = _SAFE_TRANSFORM if name == "transform" else _SAFE_VALUE
    return bool(pattern.match(value))


def sanitize_svg(content: bytes) -> bytes:
    """The SVG rebuilt from an allow-list, or InvalidLogo.

    An uploaded SVG is markup, not a picture: it can carry script, links and
    remote loads. Nothing of the original is passed through — a new tree is
    written holding only shapes, their geometry and fill rules. The header
    shows it in an <img> (no script runs there either) and the route serves
    it with a CSP that forbids everything; this is the first wall, not the
    only one. Only UTF-8 is read, and DOCTYPE and entities are refused before
    parsing (no expansion bombs, no external entities): the text is decoded
    first and the parser gets that text with its XML declaration removed, so
    no declared encoding can make it read bytes the check did not see."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidLogo("Das SVG muss UTF-8 sein.") from exc
    lowered = text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise InvalidLogo("Die Datei ist kein lesbares SVG.")
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    try:
        root = ET.fromstring(text)  # noqa: S314 — see above
    except ET.ParseError as exc:
        raise InvalidLogo("Die Datei ist kein lesbares SVG.") from exc
    if root.tag != f"{{{_SVG_NS}}}svg":
        raise InvalidLogo("Die Datei ist kein lesbares SVG.")

    drawn = 0

    def copy(src: ET.Element, parent: ET.Element | None, depth: int = 0) -> ET.Element | None:
        nonlocal drawn
        if depth > _SVG_MAX_DEPTH:
            raise InvalidLogo("Das SVG ist zu tief verschachtelt.")
        prefix = f"{{{_SVG_NS}}}"
        name = src.tag[len(prefix):] if isinstance(src.tag, str) and src.tag.startswith(prefix) else ""
        if name not in _SVG_ELEMENTS:
            return None
        attrs = {k: v for k, v in src.attrib.items() if _safe_attribute(k, v)}
        el = ET.Element(name, attrs) if parent is None else ET.SubElement(parent, name, attrs)
        if name == "style":
            css = (src.text or "").strip()
            el.text = css if _SAFE_VALUE.match(css) else ""
            return el
        drawn += name in _DRAWN
        for child in src:
            copy(child, el, depth + 1)
        return el

    out = copy(root, None)
    if out is None or not drawn:
        raise InvalidLogo("Das SVG enthält keine Form.")
    out.set("xmlns", _SVG_NS)
    return ET.tostring(out, encoding="utf-8", xml_declaration=False)


def check_header_icon(content: bytes, content_type: str | None) -> tuple[bytes, str]:
    """What is stored, and its media type — or InvalidLogo."""
    if content_type not in HEADER_ICON_TYPES:
        raise InvalidLogo("Nur PNG, JPEG oder SVG.")
    if len(content) > LOGO_MAX_BYTES:
        raise InvalidLogo("Höchstens 1 MB.")
    if content_type == SVG:
        return sanitize_svg(content), SVG
    return content, check_logo(content, content_type)


async def set_header_icon(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    content: bytes,
    content_type: str | None,
    editor: str,
) -> WorkspaceBranding:
    stored, kind = check_header_icon(content, content_type)
    row = await _row(session, tenant_id)
    row.header_icon, row.header_icon_content_type, row.updated_by_name = stored, kind, editor
    await session.commit()
    await session.refresh(row)
    return row


async def clear_header_icon(session: AsyncSession, *, tenant_id: uuid.UUID, editor: str) -> None:
    row = await get_branding(session, tenant_id=tenant_id)
    if row is not None:
        row.header_icon, row.header_icon_content_type, row.updated_by_name = None, None, editor
        await session.commit()


# ── What goes on the page ─────────────────────────────────────────────────


def initials(candidate: Candidate) -> str:
    """"N. C." — first letter of the first and the last name."""
    first = (candidate.first_name or "").strip()
    last = (candidate.last_name or "").strip()
    if not (first and last):
        parts = candidate.full_name.split()
        first = first or (parts[0] if parts else "")
        last = last or (parts[-1] if len(parts) > 1 else "")
    return " ".join(f"{p[0].upper()}." for p in (first, last) if p)


def _name_pattern(candidate: Candidate) -> re.Pattern[str] | None:
    """Every spelling of the name a recruiter's text may quote, longest
    first, as whole words — so "Celik" goes but "Celikbau GmbH" stays."""
    names = {candidate.full_name, candidate.first_name, candidate.last_name}
    names |= set(candidate.full_name.split())
    names = {n.strip() for n in names if n and len(n.strip()) >= 2}
    if not names:
        return None
    alternation = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternation})(?!\w)", re.IGNORECASE)


#: What an anonymous sheet says where the prose named the employer.
EMPLOYER_MASK = "[Arbeitgeber]"


def _employer_pattern(candidate: Candidate) -> re.Pattern[str] | None:
    """The current employer as the record names it — whole, and its name
    before a comma ("Coaching Company, Kreuztal" → "Coaching Company").

    Only what the record holds: an earlier employer named in the prose is
    not found, which is why the UI tells the recruiter to read the free text
    before sending an anonymous profile.
    """
    raw = (candidate.current_company or "").strip()
    spellings = {raw, raw.split(",")[0].strip()}
    spellings = {s for s in spellings if len(s) >= 3}
    if not spellings:
        return None
    alternation = "|".join(re.escape(s) for s in sorted(spellings, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternation})(?!\w)", re.IGNORECASE)


def _money(amount: int, currency: str | None) -> str:
    symbol = {"EUR": "€", None: "€", "": "€"}.get(currency, currency)
    return f"{amount:,}".replace(",", ".") + f" {symbol}"


def _education(entries: list | None) -> list[str]:
    out: list[str] = []
    for e in entries or []:
        if isinstance(e, dict):
            text = (e.get("degree") or e.get("institution") or "").strip()
        else:
            text = str(e).strip()
        if text:
            out.append(text)
    return out


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


@dataclass
class Composition:
    sheet: render.Sheet
    branding: render.Branding
    preview: CoverSheetPreview
    #: The files to append, in order — only those that will merge.
    documents: list[CandidateDocument]


def _pdf_problem(doc: CandidateDocument) -> str | None:
    """Why a file cannot go behind the cover sheet, or None if it can."""
    looks_pdf = doc.content[:1024].lstrip().startswith(b"%PDF") or (
        doc.content_type == "application/pdf" and doc.content.startswith(b"%PDF")
    )
    if not looks_pdf:
        return "not_pdf"
    try:
        reader = PdfReader(io.BytesIO(doc.content))
        if reader.is_encrypted and not reader.decrypt(""):
            return "encrypted"
        if len(reader.pages) == 0:
            return "unreadable"
    except Exception:  # noqa: BLE001 — a broken upload must not break the download
        return "unreadable"
    return None


async def _position(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    candidate: Candidate,
    application_id: uuid.UUID | None,
    position: str | None,
) -> tuple[str | None, str | None]:
    if application_id is not None:
        title = await session.scalar(
            select(Job.title)
            .join(Application, Application.job_id == Job.id)
            .where(
                Application.id == application_id,
                Application.tenant_id == tenant_id,
                Application.candidate_id == candidate.id,
                Job.tenant_id == tenant_id,
            )
        )
        if title is None:
            raise NotFound("process not found for this candidate")
        return title, "mandate"
    if _clean(position):
        return _clean(position), "given"
    if _clean(candidate.current_title):
        return _clean(candidate.current_title), "current_title"
    return None, None


async def compose(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    variant: V,
    application_id: uuid.UUID | None = None,
    position: str | None = None,
    contact_name: str | None = None,
    contact_email: str | None = None,
    contact_phone: str | None = None,
) -> Composition:
    """Everything the PDF holds, decided here and nowhere else."""
    candidate = await session.scalar(
        select(Candidate).where(Candidate.tenant_id == tenant_id, Candidate.id == candidate_id)
    )
    if candidate is None:
        raise NotFound("candidate not found")
    brand_row = await get_branding(session, tenant_id=tenant_id)
    anonymous = variant is V.ANONYMOUS
    pattern = _name_pattern(candidate) if anonymous else None
    employer = _employer_pattern(candidate) if anonymous else None
    who = f"Kandidat {initials(candidate)}" if anonymous else candidate.full_name.strip()

    def text(value: str | None) -> str | None:
        value = _clean(value)
        if value and pattern is not None:
            value = pattern.sub(initials(candidate) or "Kandidat", value)
        if value and employer is not None:
            value = employer.sub(EMPLOYER_MASK, value)
        return value

    pos, pos_source = await _position(
        session,
        tenant_id=tenant_id,
        candidate=candidate,
        application_id=application_id,
        position=position,
    )
    pos = text(pos)

    missing: list[str] = [] if pos else [POSITION]
    rows: list[render.Row] = []

    def prose(label: str, value: str | None) -> None:
        if value:
            rows.append(render.Row(label=label, text=value))
        else:
            missing.append(label)

    prose(SUMMARY, text(candidate.profile_summary))
    stack = text(candidate.technical_profile) or text(", ".join(candidate.skills or []))
    prose(STACK, stack)

    terms: list[render.Bullet] = []
    if candidate.salary_expectation is not None:
        terms.append(
            render.Bullet(f"{SALARY}: {_money(candidate.salary_expectation, candidate.salary_currency)}")
        )
    else:
        missing.append(SALARY)
    notice = text(candidate.notice_period)
    if notice:
        terms.append(render.Bullet(f"{NOTICE}: {notice}"))
    else:
        missing.append(NOTICE)
    if terms:
        rows.append(render.Row(label="Rahmenbedingungen", bullets=tuple(terms)))

    quals = [render.Bullet(q) for q in (text(e) for e in _education(candidate.education)) if q]
    if not quals:
        missing.append(QUALIFICATIONS)
    langs = [text(lang) for lang in (candidate.languages or [])]
    langs = [lang for lang in langs if lang]
    if langs:
        quals.append(render.Bullet(f"{LANGUAGES} nach Sprachniveau:"))
        quals += [render.Bullet(lang, level=1) for lang in langs]
    else:
        missing.append(LANGUAGES)
    if quals:
        rows.append(render.Row(label=QUALIFICATIONS, bullets=tuple(quals)))

    prose(MOTIVATION, text(candidate.motivation))

    phone = _clean(contact_phone) or (brand_row.contact_phone if brand_row else None)
    contact_parts = [p for p in (_clean(contact_name), _clean(contact_email), phone) if p]
    contact = f"Kontakt: {' – '.join(contact_parts)}" if contact_parts else None

    # The files behind the page.
    wanted = _KINDS_BY_VARIANT[variant]
    attachments: list[CoverSheetAttachment] = []
    documents: list[CandidateDocument] = []
    if wanted:
        on_file = await documents_service.list_documents(
            session, tenant_id=tenant_id, candidate_id=candidate.id
        )  # newest first
        for kind in wanted:
            of_kind = [d for d in on_file if d.kind == kind]
            if kind == DocumentKind.CV.value:
                of_kind = of_kind[:1]  # "the CV" is the newest one
            for doc in of_kind:
                problem = _pdf_problem(doc)
                attachments.append(
                    CoverSheetAttachment(
                        document_id=doc.id,
                        filename=doc.filename,
                        kind=doc.kind,
                        included=problem is None,
                        reason=problem,
                    )
                )
                if problem is None:
                    documents.append(doc)

    branding = render.Branding(
        primary_color=brand_row.primary_color if brand_row else DEFAULT_PRIMARY_COLOR,
        company_name=brand_row.company_name if brand_row else None,
        company_line=brand_row.company_line if brand_row else None,
        legal_text=brand_row.legal_text if brand_row else None,
        logo=brand_row.logo if brand_row else None,
    )
    branding_missing = [
        key
        for key, present in (
            ("logo", branding.logo),
            ("company_line", branding.company_line),
            ("legal_text", branding.legal_text),
        )
        if not present
    ]

    title = f"Kandidatenprofil – {who}"
    sheet = render.Sheet(title=title, position=pos, rows=tuple(rows), contact=contact)
    preview = CoverSheetPreview(
        variant=variant,
        title=title,
        position=pos,
        position_source=pos_source,
        missing=missing,
        attachments=attachments,
        branding_missing=branding_missing,
    )
    return Composition(sheet=sheet, branding=branding, preview=preview, documents=documents)


def assemble(composition: Composition) -> bytes:
    """The cover sheet, then each file in order, as one PDF."""
    try:
        cover = render.render(composition.sheet, composition.branding)
    except Exception:  # noqa: BLE001
        # ReportLab's layout errors quote the flowable — the candidate's own
        # text. `from None` keeps it out of the log and the crash report.
        raise RenderFailed("cover sheet could not be laid out") from None
    if not composition.documents:
        return cover
    writer = PdfWriter()
    writer.append(io.BytesIO(cover))
    for doc in composition.documents:
        reader = PdfReader(io.BytesIO(doc.content))
        if reader.is_encrypted:
            reader.decrypt("")
        writer.append(reader)
    writer.add_metadata({"/Title": composition.sheet.title})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


async def record_disclosure(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    variant: V,
    application_id: uuid.UUID | None,
    document_ids: list[uuid.UUID],
) -> None:
    """One receipt per download: ids and the variant, never a value."""
    await verification.append_receipt(
        session,
        tenant_id=tenant_id,
        agent=RECEIPT_AGENT,
        action=ReceiptAction.READ,
        subject_type="candidate",
        subject_id=str(candidate_id),
        verified=True,
        summary=f"cover sheet exported for a client (variant {variant.value})",
        payload={
            "variant": variant.value,
            "application_id": str(application_id) if application_id else None,
            "documents": [str(d) for d in document_ids],
        },
    )
    await session.commit()
