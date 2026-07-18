"""Extractor factory — vendor-neutral selection with safe fallback.

Selection is by `settings.llm_provider`. Any provider that can't be constructed
(missing key, missing SDK, import error) degrades to the heuristic parser rather
than failing the request — the feature must always work, LLM or not.
"""

from __future__ import annotations

from app.core.config import Settings, settings
from app.core.logging import get_logger
from app.domain.documents.extraction.base import CVExtractor
from app.domain.documents.extraction.heuristic import HeuristicExtractor

logger = get_logger(__name__)


def _build_openai(cfg: Settings) -> CVExtractor | None:
    if not cfg.openai_api_key:
        logger.warning("llm_provider=openai but OPENAI_API_KEY is unset — using heuristic")
        return None
    try:
        from app.domain.documents.extraction.openai_extractor import OpenAIExtractor

        return OpenAIExtractor(api_key=cfg.openai_api_key, model=cfg.llm_model)
    except Exception as exc:  # missing SDK, bad config, etc.
        logger.warning("OpenAI extractor unavailable (%s) — using heuristic", exc)
        return None


# Registry of provider builders. Add a new provider here (anthropic, a
# self-hosted OSS model, …) and nothing else changes.
_BUILDERS = {
    "openai": _build_openai,
}


def get_cv_extractor(cfg: Settings | None = None) -> CVExtractor:
    cfg = cfg or settings
    builder = _BUILDERS.get(cfg.llm_provider.lower())
    if builder is not None:
        extractor = builder(cfg)
        if extractor is not None:
            return extractor
    return HeuristicExtractor()