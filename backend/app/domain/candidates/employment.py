"""Anstellungsform: the one question with only three answers.

`data/examples/metadata_quailfication.txt` asks for "Festanstellung oder
Freelance oder beides". The column held whatever the source said — the real
data is 618 × "Permanent", 20 × "Contract, Permanent", 10 × "Contract", and a
tail of "Full-time" and "Founder" — which no filter can act on. "Wer von
diesen Leuten macht Freelance?" is not answerable from free text.

So the source's own words stay in `employment_type` (provenance: what the
import said) and the decidable value lands in `employment_form`. Normalizing
in place would have been simpler and would have thrown away the two rows
nothing maps.

The normalizer is deliberately narrow. A phrase it does not recognise yields
`None` — the recruiter picks. Guessing that "Founder" means Festanstellung
would be a silent wrong answer in a field meant for filtering.
"""

from __future__ import annotations

from app.domain.common.enums import EmploymentForm

#: Source vocabulary → the form it means. Lower-cased, trimmed.
#: "Temporary" is an employment contract, not freelance work — a befristete
#: Anstellung is still an Anstellung. "Full-time" and "Part-time" are NOT in
#: here: they describe working hours, and a freelancer can work full time.
_PERMANENT = {
    "permanent",
    "festanstellung",
    "unbefristet",
    "temporary",
    "befristet",
}
_FREELANCE = {
    "contract",
    "contractor",
    "freelance",
    "freiberuflich",
    "selbstständig",
    "selbststaendig",
    "interim",
}


def normalize_employment_form(raw: str | None) -> str | None:
    """"Contract, Permanent" → beides. "Founder" → None (nobody knows)."""
    if not raw:
        return None
    parts = [p.strip().lower() for p in raw.replace("/", ",").split(",") if p.strip()]
    if not parts:
        return None
    permanent = any(p in _PERMANENT for p in parts)
    freelance = any(p in _FREELANCE for p in parts)
    if permanent and freelance:
        return EmploymentForm.BEIDES.value
    if permanent:
        return EmploymentForm.FESTANSTELLUNG.value
    if freelance:
        return EmploymentForm.FREELANCE.value
    return None
