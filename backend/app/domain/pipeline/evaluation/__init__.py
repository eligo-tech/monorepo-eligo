"""In-app AI evaluation of a candidate for a mandate (ELI-42).

The ELI-41 Bewertungs-Prompt is sent to the configured model; the answer is
parsed, CHECKED by code (`checks.py`) and stored as a pending proposal that a
recruiter accepts or discards (`propose.py`). Nothing reaches the
assessment until a person confirms it.

    base.py              the CandidateEvaluator protocol (prompt → text)
    openai_evaluator.py  the OpenAI implementation
    factory.py           provider selection; None when no model is configured
    checks.py            deterministic verification of the answer
    propose.py           the orchestration: material → model → checks → proposal
"""
