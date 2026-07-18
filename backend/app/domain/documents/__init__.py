"""Documents domain — turn an uploaded CV (PDF) into structured candidate
fields with per-field confidence.

Flow: parse PDF text → heuristic field extraction → the document-extraction
agent gates each field by confidence (low → human review) → optional persist
creates a candidate and records receipts via the verification gate.

The heuristic extractor in ``parser.py`` is the deterministic stand-in for the
LLM document-intelligence model — same output contract, swappable later.
"""