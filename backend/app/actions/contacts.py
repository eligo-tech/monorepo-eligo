"""Contact reads (ELI-23) — who this workspace knows, where, and who is due a call."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.actions.core import ActionContext, Effect, action
from app.actions.schemas import ContactList, ContactSummary, Source
from app.domain.hub import call_list


class ListArgs(BaseModel):
    company: str | None = Field(None, description="Only contacts at companies whose name contains this text.")
    q: str | None = Field(None, description="Search name, role or company.")
    due_only: bool = Field(False, description="Only contacts whose agreed call-back is due now.")
    limit: int = Field(50, ge=1, le=200)


@action(
    "contacts.list",
    effect=Effect.READ,
    description="List the workspace's contacts (people at client and prospect companies), newest first: "
    "company, role, when added, the last call's outcome and the next agreed call. Filter by company, "
    "search, or only those due a call. No contact data (e-mail, phone, address) is returned.",
    input=ListArgs,
)
async def list_contacts(ctx: ActionContext, args: ListArgs) -> ContactList:
    page = await call_list.contacts(
        ctx.session, tenant_id=ctx.actor.tenant_id, company_name=args.company, q=args.q,
        due_only=args.due_only, limit=args.limit,
    )
    return ContactList(
        contacts=[ContactSummary(**{k: r[k] for k in ContactSummary.model_fields}) for r in page["rows"]],
        total=page["total"],
        truncated=page["truncated"],
        sources=[Source(type="manager", id=str(r["manager_id"])) for r in page["rows"]]
        or [Source(type="workspace", id=str(ctx.actor.tenant_id))],
    )
