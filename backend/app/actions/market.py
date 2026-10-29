"""Market reads from the shared public corpus. Ingestion is never an action (ARCHITECTURE.md RULE 1)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.actions.core import ActionContext, Effect, action
from app.actions.schemas import PostingList, PostingOut, Source
from app.domain.hub import service as hub


class PostingArgs(BaseModel):
    q: str | None = Field(None, description="Words in the posting title.")
    city: str | None = None
    limit: int = Field(20, ge=1, le=50)


@action(
    "market.postings",
    effect=Effect.READ,
    description="Open public job postings from the market corpus, newest first, each with its source URL. "
    "Reads what the nightly crawl stored; never fetches anything.",
    input=PostingArgs,
)
async def postings(ctx: ActionContext, args: PostingArgs) -> PostingList:
    rows = await hub.list_postings(ctx.session, q=args.q, city=args.city, limit=args.limit)
    employers: dict = {}
    for p in rows:
        if p.hub_company_id not in employers:
            company = await hub.get_company(ctx.session, hub_company_id=p.hub_company_id)
            employers[p.hub_company_id] = company.name if company else None
    return PostingList(
        postings=[
            PostingOut(
                id=p.id,
                title=p.title,
                employer=employers.get(p.hub_company_id),
                city=p.city,
                posted_at=p.posted_at,
                source=p.source,
                source_url=p.source_url,
            )
            for p in rows
        ],
        sources=[Source(type="posting", id=str(p.id), url=p.source_url) for p in rows]
        or [Source(type="corpus", id="hub_job_postings")],
    )
