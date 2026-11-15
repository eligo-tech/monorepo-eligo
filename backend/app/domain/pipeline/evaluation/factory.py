"""Which evaluator to use — the selection the CV extractor makes.

Unlike extraction there is no heuristic fallback: an evaluation guessed by
rules would be a made-up verdict about a person. With no model configured
this returns None and the feature degrades to the ELI-41 copy-prompt — the
recruiter takes the prompt to Claude by hand.
"""

from __future__ import annotations

from app.core.config import Settings, settings
from app.core.logging import get_logger
from app.domain.pipeline.evaluation.base import CandidateEvaluator

logger = get_logger(__name__)


def _build_openai(cfg: Settings) -> CandidateEvaluator | None:
    if not cfg.openai_api_key:
        return None
    try:
        from app.domain.pipeline.evaluation.openai_evaluator import OpenAIEvaluator

        return OpenAIEvaluator(api_key=cfg.openai_api_key, model=cfg.llm_model)
    except Exception as exc:  # missing SDK, bad config
        logger.warning("OpenAI evaluator unavailable (%s)", type(exc).__name__)
        return None


#: Add a provider here (a module + one line) and nothing else changes.
_BUILDERS = {"openai": _build_openai}


def get_evaluator(cfg: Settings | None = None) -> CandidateEvaluator | None:
    cfg = cfg or settings
    builder = _BUILDERS.get(cfg.llm_provider.lower())
    return builder(cfg) if builder is not None else None
