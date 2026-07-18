"""The extractor seam: text → structured fields with confidence."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.agents.document_extraction import ExtractedField

# The canonical field set the CV extractor targets. Keeping OpenAI and the
# heuristic parser on the same keys makes their outputs directly comparable and
# keeps the downstream persist mapping identical.
CV_FIELDS = (
    "full_name",
    "email",
    "phone",
    "current_title",
    "current_company",
    "location",
    "skills",
)


@runtime_checkable
class CVExtractor(Protocol):
    """Turns raw CV text into extracted fields. Pure w.r.t. the DB — it reads no
    state and writes none; confidence-gating and verification happen downstream."""

    name: str

    def extract(self, text: str) -> list[ExtractedField]: ...