"""Matching domain.

Two clearly separated stages:
  1. DETERMINISTIC hard filters in plain Python (work permit, location radius,
     salary cap, required certifications, must-have skills). No LLM. Auditable,
     reproducible, and the basis for GDPR Art. 22 explainability.
  2. SOFT re-ranking + "why matched" explanation — the ``rerank_and_explain``
     boundary where an LLM plugs in. Stubbed here; never auto-decides.

Every match produces a Match Receipt recording the decision.
"""