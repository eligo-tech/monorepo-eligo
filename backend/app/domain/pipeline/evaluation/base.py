"""The evaluator interface: a prompt in, the model's answer out.

Vendor-neutral, the same shape as `documents.extraction.CVExtractor`: callers
depend on this protocol, `factory.py` picks the implementation. The answer is
plain text in the Kandidatenauswertung schema; everything that decides what
happens to it is deterministic code downstream (`checks.py`).
"""

from __future__ import annotations

from typing import Protocol


class CandidateEvaluator(Protocol):
    #: Provider key, e.g. "openai".
    name: str
    #: The model that answered, recorded on the proposal for provenance.
    model: str

    def evaluate(self, prompt: str) -> str:
        """The model's answer to the Bewertungs-Prompt. Raises on failure."""
        ...
