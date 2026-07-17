"""Cross-domain enumerations.

Kept in one place so the state machines and confidence semantics are shared,
not re-invented per domain.
"""

from __future__ import annotations

import enum


class PipelineStage(str, enum.Enum):
    """Kanban board columns for an application.

    Mirrors the recruiter-facing board (German labels are the display names):
    Bewerbung -> Long List -> Short List, then the outcome stages.
    """

    BEWERBUNG = "bewerbung"      # incoming application / sourced
    LONG_LIST = "long_list"
    SHORT_LIST = "short_list"
    PRESENTED = "presented"
    INTERVIEW = "interview"
    PLACED = "placed"
    REJECTED = "rejected"


class ApplicationStatus(str, enum.Enum):
    """Lifecycle status of a candidate<->job application (state machine)."""

    SOURCED = "sourced"
    SCREENED = "screened"
    PRESENTED = "presented"
    INTERVIEW = "interview"
    PLACED = "placed"
    REJECTED = "rejected"

    @classmethod
    def transitions(cls) -> dict["ApplicationStatus", set["ApplicationStatus"]]:
        """Allowed forward/terminal transitions for the state machine."""
        return {
            cls.SOURCED: {cls.SCREENED, cls.REJECTED},
            cls.SCREENED: {cls.PRESENTED, cls.REJECTED},
            cls.PRESENTED: {cls.INTERVIEW, cls.REJECTED},
            cls.INTERVIEW: {cls.PLACED, cls.REJECTED},
            cls.PLACED: set(),
            cls.REJECTED: set(),
        }


class MatchStrength(str, enum.Enum):
    """Qualitative strength of a single match reason / overall match."""

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


class ConfidenceSource(str, enum.Enum):
    """Where a proposed field value / confidence came from.

    Used by enrichment + document extraction to make provenance explicit — a
    prerequisite for GDPR Art. 14 provenance disclosure and EU AI Act
    transparency obligations.
    """

    DOCUMENT_EXTRACTION = "document_extraction"
    THIRD_PARTY_SOURCE = "third_party_source"   # triggers GDPR Art. 14 notice
    PUBLIC_WEB = "public_web"
    HUMAN_VERIFIED = "human_verified"
    SELF_REPORTED = "self_reported"


class ReceiptAction(str, enum.Enum):
    """The four verifiable agent actions recorded in the append-only ledger."""

    READ = "read"
    ASSERT = "assert"
    VERIFY = "verify"
    WRITE = "write"


class WorkPermitStatus(str, enum.Enum):
    """Candidate right-to-work status — a deterministic hard filter input."""

    CITIZEN = "citizen"
    PERMANENT = "permanent"
    WORK_VISA = "work_visa"
    REQUIRES_SPONSORSHIP = "requires_sponsorship"
    NONE = "none"
    UNKNOWN = "unknown"