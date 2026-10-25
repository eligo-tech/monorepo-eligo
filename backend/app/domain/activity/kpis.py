"""The KPI definitions — what is counted, from what, and what is not.

Four KPIs are in the design. Two of them can be measured today and two
cannot, and saying so is the point: a dashboard that shows a plausible
number for something nothing measures is worse than one that shows a blank
and the reason. `available=False` is rendered as "noch keine Quelle", never
as a zero.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

#: Event types this module knows how to count.
MANAGER_CALL = "manager_call"
CANDIDATE_PRESENTED = "candidate_presented"
EVENT_TYPES = (MANAGER_CALL, CANDIDATE_PRESENTED)

#: Note kinds that are a call WITH A MANAGER. `candidate_call` is a
#: different conversation and belongs to a different KPI; `na` is the one
#: that was not reached and must not count as a call made — the same rule
#: `isContact` applies to "letzter Kontakt".
MANAGER_CALL_KINDS = ("business_call", "client_call")

PERIODS = ("woche", "monat", "quartal")


@dataclass(frozen=True)
class Kpi:
    key: str
    #: German label; the dictionary is keyed by it, like everywhere else.
    label: str
    #: Where the number comes from, shown under it. A figure whose source a
    #: recruiter cannot name is a figure they will not trust.
    source: str
    event_type: str | None
    #: False when nothing in the record measures it yet.
    available: bool
    #: Why not — rendered instead of a number.
    unavailable_because: str = ""


KPIS: tuple[Kpi, ...] = (
    Kpi(
        key="business_calls",
        label="Business Calls",
        source="Notizen bei Managern",
        event_type=MANAGER_CALL,
        available=True,
    ),
    Kpi(
        key="candidates_presented",
        label="Vorgestellte Kandidaten",
        source="Prozess · Schritt „Vorgestellt“",
        event_type=CANDIDATE_PRESENTED,
        available=True,
    ),
    Kpi(
        key="framework_contracts",
        label="Rahmenverträge",
        source="Verträge im System",
        event_type=None,
        available=False,
        # Not "coming soon": there is no Contract entity at all, so this
        # cannot be counted, estimated or derived from anything we hold.
        unavailable_because="Rahmenverträge werden noch nirgends erfasst",
    ),
    Kpi(
        key="network_growth",
        label="Netzwerk-Wachstum",
        source="LinkedIn · neue Kontakte",
        event_type=None,
        available=False,
        unavailable_because="Noch keine LinkedIn-Anbindung",
    ),
)

BY_KEY = {k.key: k for k in KPIS}


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
