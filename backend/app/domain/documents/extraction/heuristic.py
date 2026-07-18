"""Heuristic extractor — the deterministic, zero-dependency fallback.

Wraps the regex/vocabulary parser so it satisfies the same `CVExtractor`
protocol as the LLM-backed extractors. Always available (no API key, no network),
so it backs CI, offline dev, and any provider outage.
"""

from __future__ import annotations

from app.agents.document_extraction import ExtractedField
from app.domain.documents import parser


class HeuristicExtractor:
    name = "heuristic"

    def extract(self, text: str) -> list[ExtractedField]:
        return parser.extract_cv_fields(text)