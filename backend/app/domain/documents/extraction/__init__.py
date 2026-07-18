"""CV extraction — vendor-neutral factory over swappable extractors.

The `CVExtractor` protocol has one job: text → list[ExtractedField] with
per-field confidence. Implementations (OpenAI, heuristic, …) are selected by
`get_cv_extractor()` based on `settings.llm_provider`, always falling back to the
zero-dependency heuristic parser so the feature runs offline and in CI.

Adding a provider (Anthropic, a self-hosted OSS model, …) is a new module + one
line in `factory.py` — no caller changes.
"""

from app.domain.documents.extraction.base import CVExtractor
from app.domain.documents.extraction.factory import get_cv_extractor

__all__ = ["CVExtractor", "get_cv_extractor"]