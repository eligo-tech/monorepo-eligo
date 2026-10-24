"""Which advert reader to use — the same selection the CV extractor makes.

Any provider that cannot be constructed degrades to the heuristic rather
than failing the request. Pasting a link must always do something.
"""

from __future__ import annotations

from app.core.config import Settings, settings
from app.core.logging import get_logger
from app.domain.jobs.jobspec.heuristic import HeuristicJobSpecExtractor

logger = get_logger(__name__)


def _build_openai(cfg: Settings):
    if not cfg.openai_api_key:
        logger.warning("llm_provider=openai but OPENAI_API_KEY is unset — heuristic")
        return None
    try:
        from app.domain.jobs.jobspec.openai_extractor import OpenAIJobSpecExtractor

        return OpenAIJobSpecExtractor(api_key=cfg.openai_api_key, model=cfg.llm_model)
    except Exception as exc:
        logger.warning("OpenAI job-spec extractor unavailable (%s) — heuristic", exc)
        return None


_BUILDERS = {"openai": _build_openai}


def get_job_spec_extractor(cfg: Settings | None = None):
    cfg = cfg or settings
    builder = _BUILDERS.get(cfg.llm_provider.lower())
    if builder is not None:
        extractor = builder(cfg)
        if extractor is not None:
            return extractor
    return HeuristicJobSpecExtractor()
