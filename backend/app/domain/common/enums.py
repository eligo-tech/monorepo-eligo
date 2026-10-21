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
    """How a recruiter touched a manager or a candidate.

    The vocabulary is the one the recruiters named in ELI-9, not a guess:
    five kinds on a manager, three on a candidate. It replaced a coarser set
    that could not tell a call to a client under contract from a cold
    business call — which is the distinction the whole of BD turns on, and
    the reason `CALL` is retired rather than reused.

    Three vocabularies described this one thing before: this enum, the
    strings the aiFind import wrote ("BD Call", "N/A", "Meeting Notes"), and
    the list in ELI-9. `normalise_interaction_type` collapses the first two
    onto the third; nothing new is ever written in the old spelling.
    """

    #: Manager — notes from a video or onsite meeting.
    MEETING = "meeting"
    #: Manager — a call with a client under a framework agreement: running
    #: processes, future projects.
    CLIENT_CALL = "client_call"
    #: Manager — a call to a company with no framework agreement. Business
    #: development: generating business, exchanging information, building a
    #: relationship.
    BUSINESS_CALL = "business_call"
    #: Candidate — a call or video meeting with a candidate.
    CANDIDATE_CALL = "candidate_call"
    #: Either — a LinkedIn or email message, in or out.
    MESSAGE = "message"
    #: Either — the person was NOT reached by phone. 170 of the 366 imported
    #: notes are these, and they must never count as contact: a profile that
    #: looks freshly touched because somebody tried and failed to call is the
    #: opposite of what `last_contact_at` is for.
    NOT_REACHED = "na"
    #: Either — a note to self. Not on the ELI-9 list, kept because the rows
    #: and the composer that writes them already exist, and because a note
    #: nobody was present for is the one kind that is definitionally not
    #: contact.
    NOTE = "note"

    #: Retired. Still stored on rows written before ELI-9, so still a member —
    #: an enum that cannot name its own history makes those rows unreadable.
    #: Never offered for a new note: `CALL` cannot say which of the three
    #: kinds of call it was, and `EMAIL` is a `MESSAGE`.
    CALL = "call"
    EMAIL = "email"
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


#: What a recruiter may file against a MANAGER (ELI-9), in the order the
#: ticket lists them. `BRIEFING` and `FEEDBACK` are absent on purpose — both
#: belong to a mandate and are written in the mandate's own panels.
MANAGER_INTERACTION_KINDS: tuple[InteractionType, ...] = (
    InteractionType.MEETING,
    InteractionType.CLIENT_CALL,
    InteractionType.BUSINESS_CALL,
    InteractionType.MESSAGE,
    InteractionType.NOT_REACHED,
    InteractionType.NOTE,
)

#: What a recruiter may file against a CANDIDATE (ELI-9). Shorter on purpose:
#: a candidate has no business calls and no client calls.
CANDIDATE_INTERACTION_KINDS: tuple[InteractionType, ...] = (
    InteractionType.CANDIDATE_CALL,
    InteractionType.MESSAGE,
    InteractionType.NOT_REACHED,
    InteractionType.NOTE,
)

#: The spellings already in the database → what they mean now.
#:
#: Left-hand side is what the aiFind import actually wrote, read off the 366
#: live rows rather than from its documentation. Three of its kinds are
#: deliberately ABSENT — "Job Spec" (27), "Client Canvas" (17) and
#: "Candidate Qualification" (1) are on neither list in ELI-9, and folding
#: them into `NOTE` would destroy a distinction 45 real notes still carry.
#: They stay as they are and display under their own name;
#: `normalise_interaction_type` returns an unknown value unchanged.
_LEGACY_INTERACTION_TYPES: dict[str, InteractionType] = {
    "n/a": InteractionType.NOT_REACHED,
    "na": InteractionType.NOT_REACHED,
    "bd call": InteractionType.BUSINESS_CALL,
    "meeting notes": InteractionType.MEETING,
    "e-mail": InteractionType.MESSAGE,
    "email": InteractionType.MESSAGE,
}


def normalise_interaction_type(raw: str | None) -> str:
    """One stored spelling → the canonical value, or itself if unrecognised.

    Returning the raw string for an unknown kind is the point: an import that
    invents a category must show up as that category rather than being
    silently absorbed into a neighbouring one, which is how a vocabulary
    quietly stops describing its own data.
    """
    if not raw:
        return InteractionType.NOTE.value
    key = raw.strip().lower()
    mapped = _LEGACY_INTERACTION_TYPES.get(key)
    if mapped is not None:
        return mapped.value
    try:
        return InteractionType(key).value
    except ValueError:
        return raw.strip()


#: Kinds that mean the person was actually REACHED, and so move
#: `last_contact_at` forward.
#:
#: `NOT_REACHED` is the whole reason this set is explicit: it is the single
#: commonest kind in the record, and counting an unanswered call as contact
#: would mark 170 managers as freshly touched by nobody. `NOTE` and
#: `FEEDBACK` are out for the same reason — nobody was on the other end.
CONTACT_INTERACTION_KINDS = frozenset(
    {
        InteractionType.MEETING.value,
        InteractionType.CLIENT_CALL.value,
        InteractionType.BUSINESS_CALL.value,
        InteractionType.CANDIDATE_CALL.value,
        InteractionType.MESSAGE.value,
        InteractionType.BRIEFING.value,
        # Retired spellings still arriving from older rows and re-imports.
        InteractionType.CALL.value,
        InteractionType.EMAIL.value,
    }
)


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


class JobStatus(str, enum.Enum):
    """Where a mandate stands. Two values, because the recruiters have two.

    `ACTIVE` is live business: on the books, whether or not anybody is pushing
    it this week. `INACTIVE` is finished — and **finished is final**. ELI-7
    says it plainly: "inaktiv kann nicht wieder geöffnet werden, muss neu
    angelegt werden". The way to work the role again is a new mandate, which
    is what `jobs.service.copy_job` is for. The rule itself lives in
    `update_job`; an enum cannot see where a row is coming from.

    It was ("open", "active", "closed") for a day, and ("open", "on_hold",
    "filled", "cancelled") before that. Three values split "is this live
    business" across two members that nothing on screen could tell apart:
    `LIVE_JOB_STATUSES` had to name both, the Jobs filter offered both, and
    `active` had no rows anywhere because the importer only has a boolean.

    Why there is no `filled` or `cancelled`: both are *reasons* a mandate went
    inactive, not states it sits in, and the one place the difference matters
    — "this was filled, open the next" — reads it off the pipeline, where the
    placement actually happened.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"


#: Spellings in the record and what they mean now. Read off the live
#: workspace, not off the importer's documentation: 61 rows say "open" and 18
#: say "closed", written by the aiFind importer from its `is_open` boolean.
#: `normalise_job_status` folds them, and migration 0039 rewrites them.
_STORED_JOB_STATUSES: dict[str, "JobStatus"] = {
    "open": JobStatus.ACTIVE,
    "closed": JobStatus.INACTIVE,
}

#: Spellings that were only ever in the code. They are deliberately NOT
#: accepted on the way in: "filled" has no rows to heal, and quietly storing
#: it as `inactive` would answer a question the sender asked ("why did it
#: close?") by discarding it.
RETIRED_JOB_STATUSES = frozenset({"on_hold", "filled", "cancelled"})


def normalise_job_status(raw: str | None) -> str:
    """A stored status in today's vocabulary. Unknown values pass through.

    Passing an unknown value through rather than defaulting it is what keeps
    `update_job` able to refuse it: a normaliser that answered `active` for
    anything it did not recognise would turn a typo into live business.
    """
    value = (raw or "").strip()
    if not value:
        return JobStatus.ACTIVE.value
    stored = _STORED_JOB_STATUSES.get(value.lower())
    if stored is not None:
        return stored.value
    try:
        return JobStatus(value.lower()).value
    except ValueError:
        return value


def job_status_spellings(canonical: str) -> frozenset[str]:
    """Every spelling in the record that means `canonical`.

    A query filters the COLUMN, not the normaliser. `WHERE status =
    'inactive'` finds none of the 18 rows that say "closed" until migration
    0039 has run, and a status filter that returns the wrong book of business
    is a thing nobody reports, because it looks like an answer.
    """
    wanted = normalise_job_status(canonical)
    return frozenset(
        {wanted}
        | {
            raw
            for raw, mapped in _STORED_JOB_STATUSES.items()
            if mapped.value == wanted
        }
    )


#: Mandates that still count as business. The cockpit's mandate figure and a
#: manager's `open_job_count` are both "how much is running", and this is the
#: one place that decides it — including the legacy spelling, so a row the
#: migration has not reached does not quietly drop out of the count.
LIVE_JOB_STATUSES = job_status_spellings(JobStatus.ACTIVE.value)
