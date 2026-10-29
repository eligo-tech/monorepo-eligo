"""Registry core: `Effect`, `@action`, `ActionContext`, `invoke`.

The rule this file enforces: **an AI client (an agent actor) may only read.**
Proposing a change comes later and still ends at a human (ADR 0003 §3.5);
committing and anything that leaves the system are never an agent's.
The MCP server is generated from `agent_exposed()`, so what is refused here
cannot be reached from Claude at all.
"""

from __future__ import annotations

import enum
import types
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import ADMIN, RECRUITER, Actor
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


#: What an agent may call. PROPOSE joins this set in PR 4, not before.
AGENT_EFFECTS = frozenset({Effect.READ})


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
            if spec.agent_exposed and spec.effect is Effect.EXTERNAL:
                raise CatalogViolation(f"{spec.name}: external action exposed to agents")
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
            raise ActionInputInvalid(f"{name}: {exc}") from exc
        out = await spec.handler(ctx, parsed)
        if ctx.actor.kind != "human":
            await _receipt_agent_read(ctx, spec, parsed, out)
        return out


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
            "args": args.model_dump(mode="json"),
            "returned_count": len(returned),
            "returned": returned[:_RECEIPT_MAX_IDS],
        },
        actor_user_id=ctx.actor.user_id,
        actor_name=ctx.actor.name,
    )
    await ctx.session.commit()


#: The one registry the application uses. Tests build their own.
REGISTRY = Registry()
action = REGISTRY.action
