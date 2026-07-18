"""Tests for CV extraction: the vendor-neutral factory and the laufwise gate."""

from __future__ import annotations

from app.core.config import Settings
from app.domain.documents import gate
from app.domain.documents.extraction.factory import get_cv_extractor


def test_factory_falls_back_to_heuristic_without_key():
    """openai provider + no API key must not fail — it degrades to heuristic."""
    cfg = Settings(llm_provider="openai", openai_api_key=None)
    assert get_cv_extractor(cfg).name == "heuristic"


def test_factory_forces_heuristic_when_requested():
    cfg = Settings(llm_provider="heuristic")
    assert get_cv_extractor(cfg).name == "heuristic"


def test_precondition_blocks_empty_document():
    outcomes = gate.evaluate(gate.PRECONDITIONS, {"document": {"text_chars": 0}})
    assert outcomes and outcomes[0].ok is False


def test_precondition_passes_with_text():
    outcomes = gate.evaluate(gate.PRECONDITIONS, {"document": {"text_chars": 42}})
    assert all(o.ok for o in outcomes)


def test_postconditions_over_result_state():
    # Real-state fixture: a valid e-mail and two accepted fields.
    fixture = {"email": {"valid": True}, "accepted": ["full_name", "email"]}
    outcomes = gate.evaluate(gate.POSTCONDITIONS, fixture)
    assert all(o.ok for o in outcomes)

    # An invalid e-mail must fail its postcondition (routes to human review).
    bad = gate.evaluate(gate.POSTCONDITIONS, {"email": {"valid": False}, "accepted": ["full_name"]})
    assert any(not o.ok for o in bad)


def test_email_validator():
    assert gate.email_is_valid("a.b@example.com") is True
    assert gate.email_is_valid("2009 - 2012") is False
    assert gate.email_is_valid(None) is False