#!/usr/bin/env python
"""Attach a Gesprächstranskript to a candidate, as a document of that kind.

    python -m scripts.import_transcript --tenant <uuid> \
        --candidate "Nesim Celik" --file /path/to/transkript.txt [--dry-run]

`candidate_documents` already distinguishes what a file IS
(cv · transkript · zeugnis · zertifikat · sonstiges), and the candidate page
renders a transcript with "Transkript auswerten" next to it. So a call
recording belongs here and nowhere else: next to the CV, as the second source
the qualification data is read from.

**The file is never committed to this repository.** A transcript is a
recording of a named person talking about their employer, their salary and
their reasons for leaving; it belongs in the tenant's database, behind RLS,
not in version control where every checkout carries a copy. The script
therefore takes a path and this repo holds no transcripts — the GE example is
committed because it is anonymised, which these are not.

Replaces by (candidate, filename) on a re-run rather than stacking copies.
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import uuid

from sqlalchemy import select

from app.core.database import SessionLocal, current_tenant_var
from app.domain.candidates.models import Candidate
from app.domain.common.enums import DocumentKind
from app.domain.documents.models import CandidateDocument
from app.domain.registry import *  # noqa: F401,F403 — register every table


async def load(
    *,
    tenant_id: uuid.UUID,
    candidate_name: str,
    path: pathlib.Path,
    kind: str,
) -> dict:
    body = path.read_bytes()
    current_tenant_var.set(str(tenant_id))
    async with SessionLocal() as s:
        candidate = await s.scalar(
            select(Candidate).where(
                Candidate.tenant_id == tenant_id,
                Candidate.full_name == candidate_name,
            )
        )
        if candidate is None:
            # Named, never guessed: attaching a recording of one person's
            # conversation to another person's record is not a near miss.
            raise SystemExit(f"no candidate named {candidate_name!r} for this tenant")

        doc = await s.scalar(
            select(CandidateDocument).where(
                CandidateDocument.tenant_id == tenant_id,
                CandidateDocument.candidate_id == candidate.id,
                CandidateDocument.filename == path.name,
            )
        )
        if doc is None:
            doc = CandidateDocument(
                tenant_id=tenant_id,
                candidate_id=candidate.id,
                filename=path.name,
            )
            s.add(doc)
        doc.kind = kind
        doc.content_type = "text/plain; charset=utf-8"
        doc.content = body
        doc.byte_size = len(body)
        await s.commit()
        return {
            "candidate": candidate_name,
            "candidate_id": str(candidate.id),
            "document_id": str(doc.id),
            "bytes": len(body),
        }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tenant", type=uuid.UUID, required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--file", type=pathlib.Path, required=True)
    ap.add_argument(
        "--kind",
        default=DocumentKind.TRANSKRIPT.value,
        choices=[k.value for k in DocumentKind],
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.file.exists():
        raise SystemExit(f"{args.file} not found")
    text = args.file.read_text(encoding="utf-8")
    print(
        f"{args.file.name}: {len(text)} Zeichen, {len(text.splitlines())} Zeilen"
        f" → {args.candidate} ({args.kind})"
    )
    if args.dry_run:
        print(text[:400].rstrip() + " …")
        return
    print("geschrieben:", asyncio.run(
        load(
            tenant_id=args.tenant,
            candidate_name=args.candidate,
            path=args.file,
            kind=args.kind,
        )
    ))


if __name__ == "__main__":
    main()
