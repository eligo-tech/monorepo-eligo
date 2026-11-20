"""The KPI definitions — what is counted, from what, and what is not.

ELI-15 started with four KPIs, two of which nothing measured. ELI-64 gave
every KPI the ticket names a source in the record (a fee on the deal, a
dated mark on the company, the creator of a lead) — and kept the rule that
a KPI nothing measures shows a blank and the reason: `available=False` is
rendered as "noch keine Quelle", never as a zero.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

#: What each measurable KPI counts. These are not event types in a table of
#: their own — they name a query over the row that already records the fact.
MANAGER_CALL = "manager_call"
CANDIDATE_PRESENTED = "candidate_presented"
#: ELI-64.
REVENUE = "revenue"
CONTACT_POINT = "contact_point"
LEAD_ADDED = "lead_added"
FRAMEWORK_CONTRACT = "framework_contract"
MANDATE_ADDED = "mandate_added"
COUNTABLE = (
    MANAGER_CALL,
    CANDIDATE_PRESENTED,
    REVENUE,
    CONTACT_POINT,
    LEAD_ADDED,
    FRAMEWORK_CONTRACT,
    MANDATE_ADDED,
)

#: The process step that means a candidate was put in front of the client.
PRESENTED_STEP = "vorgestellt"
#: The step that means the deal closed — its date is when the Umsatz lands.
DEAL_STEP = "vertrag"

#: Note kinds that are a call WITH A MANAGER. `candidate_call` is a
#: different conversation and belongs to a different KPI; `na` is the one
#: that was not reached and must not count as a call made — the same rule
#: `isContact` applies to "letzter Kontakt".
#: ELI-61: a Gesprächsnotiz is "Manager erreicht" — a conversation that
#: happened, so it counts with the two calls.
_MANAGER_CALL_CANONICAL = ("business_call", "client_call", "conversation")
#: ELI-64: "Business Call oder Meeting" — the calls plus a video or onsite
#: meeting, which is the same BD conversation held in a room.
_CALL_OR_MEETING_CANONICAL = (*_MANAGER_CALL_CANONICAL, "meeting")


def spellings_for(canonical: tuple[str, ...] | frozenset[str]) -> tuple[str, ...]:
    """Every stored spelling that MEANS one of `canonical`.

    The canonical values are not enough, and assuming they were made the
    call KPI read zero while 133 real business calls sat in the record. The
    aiFind importer writes the source's own words — "BD Call" — and
    `normalise_interaction_type` folds them on READ, in Python. A KPI that
    filters in SQL never sees that fold.

    So the filter is derived from the same mapping rather than restated:
    anything that normalises into `canonical` counts, whatever it is
    spelled like in the column. That stays true after a normalisation pass
    and stays true if the next importer writes raw words again.
    """
    from app.domain.common.enums import (
        _LEGACY_INTERACTION_TYPES,
        normalise_interaction_type,
    )

    spellings = set(canonical)
    for raw in _LEGACY_INTERACTION_TYPES:
        if normalise_interaction_type(raw) in canonical:
            # Stored with the source's capitalisation ("BD Call"), so the
            # query compares case-insensitively — see `service._notes`.
            spellings.add(raw)
    return tuple(sorted(spellings))


def manager_call_spellings() -> tuple[str, ...]:
    """Every stored spelling that means a call with a manager."""
    return spellings_for(_MANAGER_CALL_CANONICAL)


def call_or_meeting_spellings() -> tuple[str, ...]:
    """ELI-64: a call with a manager, or a meeting with one."""
    return spellings_for(_CALL_OR_MEETING_CANONICAL)


def contact_spellings() -> tuple[str, ...]:
    """ELI-64 "Kontaktpunkte": every kind that means somebody was reached.

    The backend's `CONTACT_INTERACTION_KINDS` — the rule that moves "letzter
    Kontakt" — so the KPI and the contact date cannot disagree. Unanswered
    ("na"), a note to self and feedback about a candidate are not contact.
    """
    from app.domain.common.enums import CONTACT_INTERACTION_KINDS

    return spellings_for(frozenset(CONTACT_INTERACTION_KINDS))


#: Kept for callers that only need the canonical pair (the migration's
#: backfill, and the frontend's own vocabulary).
MANAGER_CALL_KINDS = _MANAGER_CALL_CANONICAL

PERIODS = ("woche", "monat", "quartal")

#: The three groups the ticket names, in its order.
GROUPS = ("business", "bd", "prozess")


@dataclass(frozen=True)
class Kpi:
    key: str
    #: German label; the dictionary is keyed by it, like everywhere else.
    label: str
    #: Where the number comes from, shown under it. A figure whose source a
    #: recruiter cannot name is a figure they will not trust.
    source: str
    #: Which query counts it, or None when nothing can.
    counts: str | None
    #: False when nothing in the record measures it yet.
    available: bool
    #: Why not — rendered instead of a number.
    unavailable_because: str = ""
    #: "business" · "bd" · "prozess" — the ticket's three headings.
    group: str = "bd"
    #: "count" or "eur" — how the number is printed.
    unit: str = "count"


KPIS: tuple[Kpi, ...] = (
    Kpi(
        key="revenue",
        label="Umsatz",
        source="Prozess · Schritt „Vertrag“ · Honorar (€)",
        counts=REVENUE,
        available=True,
        group="business",
        unit="eur",
    ),
    Kpi(
        key="contact_points",
        label="Kontaktpunkte mit Leads oder Managern",
        source="Notizen bei Leads und Managern · ohne „nicht erreicht“",
        counts=CONTACT_POINT,
        available=True,
    ),
    Kpi(
        key="business_calls",
        label="Business Call oder Meeting",
        source="Notizen bei Managern · Business Call, Kundencall, Gesprächsnotiz, Meeting",
        counts=MANAGER_CALL,
        available=True,
    ),
    Kpi(
        key="leads_added",
        label="Leads hinzugefügt",
        source="Leads · angelegt (aus Markt übernommen oder von Hand)",
        counts=LEAD_ADDED,
        available=True,
    ),
    Kpi(
        key="framework_contracts",
        label="Rahmenvertrag abgeschlossen",
        source="Unternehmen · „Rahmenvertrag abgeschlossen am“",
        counts=FRAMEWORK_CONTRACT,
        available=True,
    ),
    Kpi(
        key="mandates_added",
        label="Mandat hinzugefügt",
        source="Mandate · angelegt (ohne Importe)",
        counts=MANDATE_ADDED,
        available=True,
    ),
    Kpi(
        key="candidates_presented",
        label="Vorgestellte Kandidaten",
        source="Prozess · Schritt „Vorgestellt“",
        counts=CANDIDATE_PRESENTED,
        available=True,
        group="prozess",
    ),
)

BY_KEY = {k.key: k for k in KPIS}

#: The Prozess funnel (ELI-64): "das Verhältnis … und die Zeit zwischen jedem
#: einzelnen Schritt". Milestone key → label, in order; each consecutive
#: pair is one transition.
FUNNEL: tuple[tuple[str, str], ...] = (
    ("vorgestellt", "CV gesendet (vorgestellt)"),
    ("interview_1", "1. Interview"),
    ("interview_2", "2. Interview"),
    ("final", "Final Interview"),
    ("offer", "Angebot"),
    ("deal", "Deal"),
)
FUNNEL_SOURCE = "Prozess · Schrittdaten (erledigt, sonst geplant)"

_FIXED_MILESTONES = {
    "vorgestellt": "vorgestellt",
    "interview": "interview_1",
    "finaltermin": "final",
    "offer": "offer",
    DEAL_STEP: "deal",
}


def milestone_for(step_key: str, label: str | None = None) -> str | None:
    """Which funnel milestone one process step is, if any.

    The canonical steps map one-to-one. There is no canonical "2. Interview"
    step: a second round is stored as an extra round ("interviewtermin_2",
    "interviewtermin_3") or as a step the process added for itself, named by
    the recruiter ("2. Interview", "Zweitgespräch"). Any of those counts —
    the earliest one is the second interview.
    """
    from app.domain.pipeline import steps as steps_mod

    if step_key in _FIXED_MILESTONES:
        return _FIXED_MILESTONES[step_key]
    if step_key.startswith(steps_mod.EXTRA_ROUND_PREFIX):
        return "interview_2"
    if steps_mod.is_custom(step_key):
        name = (label or step_key).lower()
        if "final" in name:
            return None
        if "interview" in name or "zweit" in name:
            return "interview_2"
    return None


#: Tiles a person can put on their Cockpit: every KPI, plus the funnel.
PROCESS_TILE = "process"
TILES: tuple[str, ...] = (*(k.key for k in KPIS), PROCESS_TILE)
#: What the Cockpit shows before somebody chooses (the ticket's priorities).
DEFAULT_TILES: tuple[str, ...] = ("revenue", "business_calls", "leads_added")


def window(period: str, at: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """[start, end) for the period `at` falls in.

    Calendar periods, not rolling ones. "This month" has to mean the same
    thing to the consultant and to whoever set the target, and a rolling
    30 days means neither of them can check the other's number.

    Weeks start Monday (ISO), because that is what a German work week is.
    """
    if period not in PERIODS:
        raise ValueError(f"unknown period {period}")
    day = at.astimezone(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "woche":
        start = day - dt.timedelta(days=day.weekday())
        return start, start + dt.timedelta(days=7)
    if period == "monat":
        start = day.replace(day=1)
        end = (start + dt.timedelta(days=32)).replace(day=1)
        return start, end
    first_month = 3 * ((day.month - 1) // 3) + 1
    start = day.replace(month=first_month, day=1)
    end_month = first_month + 3
    end = (
        start.replace(year=start.year + 1, month=end_month - 12)
        if end_month > 12
        else start.replace(month=end_month)
    )
    return start, end
