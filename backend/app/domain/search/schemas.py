"""Wire contract of the global search: enough to name a record and open it.

Deliberately no e-mail, phone or address — a hit is a pointer to the record,
whose own screen shows what the viewer may see.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SearchHit(BaseModel):
    id: str
    label: str
    subtitle: str | None = None


class ContactHit(SearchHit):
    #: `lead` = a bus-dev contact taken from Markt; `manager` = vetted.
    kind: Literal["lead", "manager"]


class SearchResults(BaseModel):
    candidates: list[SearchHit] = []
    jobs: list[SearchHit] = []
    companies: list[SearchHit] = []
    contacts: list[ContactHit] = []
