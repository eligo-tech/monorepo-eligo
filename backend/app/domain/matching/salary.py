"""Does the money work? One rule, two readers.

The recruiter's own evaluation does this comparison by hand —
`data/examples/KandidatenInfo.txt` reads "aktuell >105k; Minimum 92–95k,
Wunsch ~100k. Über der GE-Orientierung (~90k)" and then decides. Both numbers
are in the record now, so the comparison is arithmetic and belongs in code:
deterministic facts stay out of the model's hands (CLAUDE.md §2.2).

**A wish above the band is not an exclusion.** That is the distinction this
module exists for. The hard filter used to drop anyone whose
`salary_expectation` exceeded `salary_max` — which, now that a floor is
recorded, throws away exactly the candidate the GE example calls a rare full
match: wish 100k against a 90k orientation, but "ausdrücklich verhandlungs-
und stufenmodell-bereit" with a floor of 92k. Only the FLOOR excludes.

Pure, no DB, no I/O: the per-job view and the matcher read the same verdict,
so the cockpit can never show "verhandelbar" for someone the matcher dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: unknown  — not enough numbers to say anything
#: fits     — the wish is inside the band
#: negotiable — the wish is above the ceiling, but the floor is not
#: above_band — the floor itself exceeds the ceiling: no deal at this price
SalaryStatus = Literal["unknown", "fits", "negotiable", "above_band"]


@dataclass(frozen=True)
class SalaryFit:
    status: SalaryStatus
    #: One German sentence for the cockpit. None when there is nothing to say.
    detail: str | None = None

    @property
    def excludes(self) -> bool:
        """Whether this is a hard failure rather than something to negotiate."""
        return self.status == "above_band"


def _money(amount: int, currency: str | None, *, symbol: bool = True) -> str:
    """"92000" → "92.000 €". The lower end of a band drops the symbol, so a
    range reads "80.000–95.000 €" rather than twice."""
    figure = f"{amount:,}".replace(",", ".")
    if not symbol:
        return figure
    sign = "€" if (currency or "EUR").upper() == "EUR" else (currency or "")
    return f"{figure} {sign}".strip()


def _band(job_min: int | None, job_max: int | None, currency: str | None) -> str:
    if job_min is not None and job_max is not None:
        return f"{_money(job_min, currency, symbol=False)}–{_money(job_max, currency)}"
    if job_max is not None:
        return f"bis {_money(job_max, currency)}"
    return f"ab {_money(job_min or 0, currency)}"


def salary_fit(
    *,
    minimum: int | None,
    wish: int | None,
    job_min: int | None,
    job_max: int | None,
    currency: str | None = "EUR",
) -> SalaryFit:
    """Compare what the candidate needs with what the mandate pays."""
    # No ceiling means no constraint to breach; no figure from the candidate
    # means nothing to compare. Either way the answer is "not known", never
    # an optimistic "fits".
    if job_max is None or (minimum is None and wish is None):
        return SalaryFit("unknown")

    band = _band(job_min, job_max, currency)
    if minimum is not None and minimum > job_max:
        return SalaryFit(
            "above_band",
            f"Minimum {_money(minimum, currency)} über dem Band ({band})",
        )
    if wish is not None and wish > job_max:
        floor = (
            f" — Minimum {_money(minimum, currency)} passt" if minimum is not None else ""
        )
        return SalaryFit(
            "negotiable",
            f"Wunsch {_money(wish, currency)} über dem Band ({band}){floor}",
        )
    asked = wish if wish is not None else minimum
    return SalaryFit("fits", f"{_money(asked or 0, currency)} im Band ({band})")
