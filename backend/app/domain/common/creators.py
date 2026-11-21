"""ELI-69 "Angelegt von": who added a lead, a manager or a company.

`CreatedByMixin` stamps the account at insert; this module reads it back for
the lists — the filter (`created_by=<user id>|me`) and its choices. Always
inside one workspace: the choices and the filter both carry `tenant_id`, so
an account of another workspace never appears, even by its id.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

#: The value of `created_by` that means the logged-in account ("Ich").
ME = "me"


class Creator(BaseModel):
    """One choice of the "Angelegt von" filter."""

    user_id: str
    name: str


def resolve(created_by: str | None, actor_user_id: str | None) -> str | None:
    """The account id to filter on, or None for no filter.

    "me" without an account (the auth-disabled demo) is nobody: "" matches no
    stored id, so the list is empty rather than everyone's or the
    unattributed rows."""
    if created_by is None or not created_by.strip():
        return None
    if created_by.strip() == ME:
        return actor_user_id or ""
    return created_by.strip()


async def creators(session: AsyncSession, model, *, tenant_id: uuid.UUID, where=()) -> list[dict]:
    """Every account that added a row of `model` here, A–Z by name.

    One entry per account, under the name on its newest row: the name is
    copied at creation time, and a renamed account is still one person."""
    rows = (
        await session.execute(
            select(model.created_by_user_id, model.created_by_name)
            .where(model.tenant_id == tenant_id, model.created_by_user_id.is_not(None), *where)
            .order_by(model.created_at.desc())
        )
    ).all()
    named: dict[str, str] = {}
    for user_id, name in rows:
        named.setdefault(user_id, name or user_id)
    return [
        {"user_id": user_id, "name": name}
        for user_id, name in sorted(named.items(), key=lambda kv: (kv[1].lower(), kv[0]))
    ]
