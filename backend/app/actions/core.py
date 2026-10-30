"""Registry core: `Effect`, `@action`, `ActionContext`, `invoke`.

The rule this file enforces: **an AI client (an agent actor) may read and
propose — never write.** A PROPOSE handler returns a `ProposalDraft`; this
registry stores it as a pending proposal that a human confirms in Eligo
(ADR 0003 §3.7). Committing and anything that leaves the system are never an
agent's.
The MCP server is generated from `agent_exposed()`, so what is refused here
cannot be reached from Claude at all.
"""

from __future__ import annotations

import enum
import types
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import ADMIN, RECRUITER, Actor
from app.core.context import ActorRef, current_actor_var
from app.core.database import current_tenant_var
from app.domain.common.enums import ReceiptAction


class Effect(str, enum.Enum):
    """What calling the action does to the world."""

    #: Returns data, changes nothing.
    READ = "read"
    #: Creates a pending change a human must confirm.
    PROPOSE = "propose"
    #: Changes the record.
    COMMIT = "commit"
    #: Reaches outside the system (sends, crawls, calls a provider).
    EXTERNAL = "external"


#: What an agent may call.
AGENT_EFFECTS = frozenset({Effect.READ, Effect.PROPOSE})


class UnknownAction(LookupError):
    """No action has this name."""


class ActionForbidden(PermissionError):
    """This actor may not call this action."""


class ActionInputInvalid(ValueError):
    """The arguments do not match the action's input model."""


class CatalogViolation(RuntimeError):
    """A registration breaks a rule no action may break. Raised at startup."""


#: Ingestion entry points (ARCHITECTURE.md RULE 1: a cron fills the corpus,
#: never a request). No handler may name one. `fetch_missing_` is a prefix,
#: so a new `fetch_missing_<thing>` is covered without editing this.
_INGESTION_EXACT = frozenset({"ingest", "deactivate_stale_postings"})
_INGESTION_PREFIX = "fetch_missing_"

#: Names a PROPOSE handler may not use: the session's write calls, SQL write
#: constructs, every domain function a confirm would run, and the ledger. A
#: propose handler READS (to snapshot what it saw) and returns a draft; the
#: registry stores the draft. Static, like the ingestion check below — so it
#: fails closed on innocent uses too (`set.add`, `dict.update`): such a handler
#: refuses to load. Write it another way. What a static scan cannot see (an
#: attribute set on a loaded record, raw SQL) the runtime guard in `invoke`
#: refuses.
_WRITE_NAMES = frozenset({
    "add", "add_all", "commit", "flush", "delete", "merge", "insert", "update",
    "set_step", "add_step", "remove_step", "move_stage", "transition_status",
    "set_assessment", "log_interaction", "log_candidate_interaction",
    "verify_and_commit", "append_receipt", "create", "confirm", "decline",
})

#: Most ids a receipt lists; the count is always exact.
_RECEIPT_MAX_IDS = 500


def _names_used(code: types.CodeType) -> set[str]:
    """Every global/attribute name a function and its nested functions use."""
    names = set(code.co_names)
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            names |= _names_used(const)
    return names


def _wraps_ingestion(handler: Handler) -> str | None:
    code = getattr(handler, "__code__", None)
    if code is None:
        return None
    for name in _names_used(code):
        if name in _INGESTION_EXACT or name.startswith(_INGESTION_PREFIX):
            return name
    return None


def _writes(handler: Handler) -> str | None:
    code = getattr(handler, "__code__", None)
    if code is None:
        return None
    hits = _names_used(code) & _WRITE_NAMES
    return min(hits) if hits else None


class ActionNotFound(LookupError):
    """The record does not exist in the caller's workspace.

    Deliberately the same answer for "never existed" and "belongs to another
    workspace": telling the two apart would confirm that a foreign id is real.
    """


@dataclass(frozen=True)
class ActionContext:
    """Who is calling, and the session their workspace is pinned on."""

    session: AsyncSession
    actor: Actor


Handler = Callable[[ActionContext, Any], Awaitable[Any]]


@dataclass(frozen=True)
class ActionSpec:
    name: str
    effect: Effect
    description: str
    input: type[BaseModel]
    handler: Handler
    roles: frozenset[str] = field(default_factory=lambda: frozenset({ADMIN, RECRUITER}))

    @property
    def agent_exposed(self) -> bool:
        return self.effect in AGENT_EFFECTS


class Registry:
    def __init__(self) -> None:
        self._specs: dict[str, ActionSpec] = {}

    def action(
        self,
        name: str,
        *,
        effect: Effect,
        description: str,
        input: type[BaseModel],
        roles: set[str] | frozenset[str] | None = None,
    ) -> Callable[[Handler], Handler]:
        """Register a handler. A name registers once; a second is a bug."""

        def register(handler: Handler) -> Handler:
            if name in self._specs:
                raise ValueError(f"action {name!r} is already registered")
            self._specs[name] = ActionSpec(
                name=name,
                effect=effect,
                description=description,
                input=input,
                handler=handler,
                roles=frozenset(roles) if roles else frozenset({ADMIN, RECRUITER}),
            )
            return handler

        return register

    def get(self, name: str) -> ActionSpec:
        try:
            return self._specs[name]
        except KeyError:
            raise UnknownAction(name) from None

    def all(self) -> list[ActionSpec]:
        return sorted(self._specs.values(), key=lambda s: s.name)

    def agent_exposed(self) -> list[ActionSpec]:
        return [s for s in self.all() if s.agent_exposed]

    def check(self) -> None:
        """Refuse a catalog that breaks a standing rule. Run at import of the catalog.

        Static, over the handlers' code: it sees a call written in the handler
        or a closure inside it, not one buried in a helper elsewhere. That is
        the honest limit; the review checklist covers the rest.
        """
        if AGENT_EFFECTS & {Effect.COMMIT, Effect.EXTERNAL}:
            raise CatalogViolation("an agent may never commit or reach outside")
        for spec in self.all():
            if spec.effect is Effect.PROPOSE:
                wrote = _writes(spec.handler)
                if wrote:
                    raise CatalogViolation(
                        f"{spec.name}: a propose handler uses {wrote!r} — it may only "
                        "read and return a ProposalDraft; a human confirms in Eligo"
                    )
            hit = _wraps_ingestion(spec.handler)
            if hit:
                raise CatalogViolation(
                    f"{spec.name}: calls {hit!r} — ingestion is a scheduled job, never an action"
                )

    async def invoke(self, name: str, ctx: ActionContext, args: dict[str, Any]) -> Any:
        """Run one action — every check before the handler.

        For an AI client, also append one READ receipt (tool, user, OAuth
        client, record ids returned) and commit it with the read. If the
        receipt cannot be written the data is not returned: an unreceipted AI
        read is the thing this layer exists to rule out.
        """
        spec = self.get(name)
        if ctx.actor.role not in spec.roles:
            raise ActionForbidden(f"{name}: role {ctx.actor.role!r} may not call this")
        if ctx.actor.kind != "human" and not spec.agent_exposed:
            raise ActionForbidden(f"{name}: an AI client may not call a {spec.effect.value} action")
        try:
            parsed = spec.input.model_validate(args)
        except ValidationError as exc:
            # Location and reason only: pydantic's own text echoes the input,
            # which may be a person's details, into logs and crash reports.
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc'])) or 'input'}: {e['msg']}"
                for e in exc.errors(include_input=False, include_url=False)
            )
            raise ActionInputInvalid(f"{name}: {problems}") from None
        # Pin the workspace and the person for everything below: RLS re-reads
        # `current_tenant_var` at the start of every transaction (the handler's
        # commit and the receipt's open new ones), and receipts written deeper
        # down read `current_actor_var`. So no caller can get this wrong.
        tenant_token = current_tenant_var.set(str(ctx.actor.tenant_id))
        actor_token = current_actor_var.set(
            ActorRef(user_id=ctx.actor.user_id, name=ctx.actor.name)
        )
        try:
            if spec.effect is Effect.PROPOSE:
                out = await _run_read_only(ctx, spec, parsed)
            else:
                out = await spec.handler(ctx, parsed)
            if spec.effect is Effect.PROPOSE:
                # The proposal's own receipt replaces the read receipt.
                return await _store_proposal(ctx, spec, out)
            if ctx.actor.kind != "human":
                await _receipt_agent_read(ctx, spec, parsed, out)
            return out
        finally:
            current_actor_var.reset(actor_token)
            current_tenant_var.reset(tenant_token)


def _receipt_args(args: BaseModel) -> dict[str, Any]:
    """The arguments as the ledger may keep them: names always, values only if not free text.

    Receipts cannot be erased (GDPR Art. 17) and an AI client will search for a
    person by name, so a free-text value is recorded as "given", never as
    itself. Ids, numbers and booleans are references, not personal data.
    """
    kept: dict[str, Any] = {}
    for key, value in args.model_dump(mode="python").items():
        if value is None:
            continue
        if isinstance(value, (bool, int, float, uuid.UUID)):
            kept[key] = str(value) if isinstance(value, uuid.UUID) else value
        else:
            kept[key] = "(given)"
    return kept


async def _receipt_agent_read(
    ctx: ActionContext, spec: ActionSpec, args: BaseModel, out: Any
) -> None:
    from app.domain.verification import service as verification

    sources = getattr(out, "sources", None)
    if not sources:
        raise CatalogViolation(f"{spec.name}: an agent-visible output must name its sources")
    returned = [{"type": s.type, "id": s.id} for s in sources]
    await verification.append_receipt(
        ctx.session,
        tenant_id=ctx.actor.tenant_id,
        agent=f"ai-client:{ctx.actor.client_id or 'unknown'}"[:100],
        action=ReceiptAction.READ,
        subject_type="action",
        subject_id=spec.name,
        verified=True,
        summary=f"{spec.name} returned {len(returned)} record(s) to an AI client",
        payload={
            "tool": spec.name,
            "client_id": ctx.actor.client_id,
            "args": _receipt_args(args),
            "returned_count": len(returned),
            "returned": returned[:_RECEIPT_MAX_IDS],
        },
        actor_user_id=ctx.actor.user_id,
        actor_name=ctx.actor.name,
    )
    await ctx.session.commit()


async def _run_read_only(ctx: ActionContext, spec: ActionSpec, args: BaseModel) -> Any:
    """Run a PROPOSE handler with every write refused while it runs.

    Two holes the static check cannot close: a statement that is not a SELECT
    (raw SQL included) is refused as it executes, and an object the handler
    added, changed or deleted is refused before the registry's own commit
    could carry it into the record.
    """
    sync_session = ctx.session.sync_session

    def _refuse_writes(state) -> None:  # noqa: ANN001 — ORMExecuteState
        if not state.is_select:
            raise CatalogViolation(f"{spec.name}: a propose handler ran a write")

    event.listen(sync_session, "do_orm_execute", _refuse_writes)
    try:
        out = await spec.handler(ctx, args)
    finally:
        event.remove(sync_session, "do_orm_execute", _refuse_writes)
    if ctx.session.new or ctx.session.dirty or ctx.session.deleted:
        await ctx.session.rollback()
        raise CatalogViolation(f"{spec.name}: a propose handler changed a record")
    return out


async def _store_proposal(ctx: ActionContext, spec: ActionSpec, draft: Any) -> Any:
    """Turn a PROPOSE handler's draft into a pending proposal. The only write."""
    from app.actions.schemas import ProposalOut
    from app.domain.proposals import service as proposals

    if not isinstance(draft, proposals.ProposalDraft):
        raise CatalogViolation(f"{spec.name}: a propose handler must return a ProposalDraft")
    row = await proposals.create(
        ctx.session,
        tenant_id=ctx.actor.tenant_id,
        draft=draft,
        tool=spec.name,
        asked_by_user_id=ctx.actor.user_id,
        asked_by_name=ctx.actor.name,
        client_id=ctx.actor.client_id,
    )
    return ProposalOut.from_row(row)


#: The one registry the application uses. Tests build their own.
REGISTRY = Registry()
action = REGISTRY.action
