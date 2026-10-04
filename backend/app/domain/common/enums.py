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


class InteractionType(str, enum.Enum):
    """How a recruiter touched a manager.

    Deliberately coarse. The mailbox/calendar integration will want finer
    grain, and guessing that shape before it exists produces categories nobody
    fills in.
    """

    CALL = "call"
    EMAIL = "email"
    MEETING = "meeting"
    MESSAGE = "message"
    NOTE = "note"
    #: The conversation that defines a mandate (Prozess-Doku, Phase 2). Its
    #: own kind rather than a call with a job attached, because it is the one
    #: a recruiter goes looking for: "what did they actually ask for?"
    BRIEFING = "briefing"
    #: What was said about ONE CANDIDATE on one mandate — by the client after
    #: a presentation, or by the candidate after an interview. Carries a
    #: `candidate_id`; a briefing does not. Its own kind because the two
    #: answer different questions ("what does the client want?" vs "what did
    #: they think of him?") and are read in different panels.
    #:
    #: It is a row per remark rather than the step's `note`, which is one
    #: field: the second piece of feedback on the same step used to overwrite
    #: the first.
    FEEDBACK = "feedback"


#: Provenances that constitute EVIDENCE for a field: somebody or something
#: checked the value against a source that can be named. A bulk import is not
#: in this set — it asserts what another system held, which is a claim, not a
#: check. That distinction is the whole of `verification_score`: without it
#: the number counts rows, and a number that counts rows is a completeness
#: measure wearing the word "verified".
EVIDENCE_SOURCES = frozenset(
    {
        ConfidenceSource.DOCUMENT_EXTRACTION,  # read off a CV we hold
        ConfidenceSource.HUMAN_VERIFIED,  # a person checked it
        ConfidenceSource.PUBLIC_WEB,  # a page we can cite
        ConfidenceSource.THIRD_PARTY_SOURCE,  # a provider we can name
    }
)


def is_evidence(source: ConfidenceSource | str | None) -> bool:
    """True when a field established this way counts as verified."""
    if source is None:
        return False
    if isinstance(source, str):
        try:
            source = ConfidenceSource(source)
        except ValueError:
            return False
    return source in EVIDENCE_SOURCES


#: Provenances that owe a GDPR Art. 14 notification when they carry personal
#: data: the subject did not give it to us, so they must be told we hold it.
#: One definition, used by both the enrichment agent and the managers domain —
#: two copies of this set would drift and the drift would be a compliance gap.
ART14_SOURCES = frozenset(
    {ConfidenceSource.THIRD_PARTY_SOURCE, ConfidenceSource.PUBLIC_WEB}
)


def owes_art14_notice(source: ConfidenceSource | str | None) -> bool:
    """True when personal data from this source owes an Art. 14 notice."""
    if source is None:
        return False
    if isinstance(source, str):
        try:
            source = ConfidenceSource(source)
        except ValueError:
            return False
    return source in ART14_SOURCES


class DocumentKind(str, enum.Enum):
    """What an uploaded file IS.

    `candidate_documents` held only CVs, so "the newest file" and "the CV"
    were the same row. The moment a Zeugnis or a Zertifikat is attached that
    stops being true, and a reader asking for the CV would get back whatever
    was uploaded last. The kind is what keeps that question answerable.

    `TRANSKRIPT` is the Gesprächsnotiz from the Qualifikationsgespräch — the
    second source the qualification data is read from, next to the CV.
    """

    CV = "cv"
    TRANSKRIPT = "transkript"
    ZEUGNIS = "zeugnis"
    ZERTIFIKAT = "zertifikat"
    SONSTIGES = "sonstiges"


class EmploymentForm(str, enum.Enum):
    """Festanstellung, Freelance, or both — the Anstellungsform a candidate
    will actually consider.

    Three values because the business has three answers. The imported source
    string ("Permanent", "Contract, Permanent", "Founder") stays where it was;
    this is the normalized form a filter can use. See
    `candidates/employment.py` for the mapping and why it refuses to guess.
    """

    FESTANSTELLUNG = "festanstellung"
    FREELANCE = "freelance"
    BEIDES = "beides"
