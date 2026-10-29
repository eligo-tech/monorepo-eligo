"""Registry core: `Effect`, `@action`, `ActionContext`, `invoke`.

The rule this file enforces: **an AI client (an agent actor) may only read.**
Proposing a change comes later and still ends at a human (ADR 0003 §3.5);
committing and anything that leaves the system are never an agent's.
The MCP server is generated from `agent_exposed()`, so what is refused here
cannot be reached from Claude at all.
"""

from __future__ import annotations

import enum
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import ADMIN, RECRUITER, Actor


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

    async def invoke(self, name: str, ctx: ActionContext, args: dict[str, Any]) -> Any:
        """Run one action — every check before the handler, none after."""
        spec = self.get(name)
        if ctx.actor.role not in spec.roles:
            raise ActionForbidden(f"{name}: role {ctx.actor.role!r} may not call this")
        if ctx.actor.kind != "human" and not spec.agent_exposed:
            raise ActionForbidden(f"{name}: an AI client may not call a {spec.effect.value} action")
        try:
            parsed = spec.input.model_validate(args)
        except ValidationError as exc:
            raise ActionInputInvalid(f"{name}: {exc}") from exc
        return await spec.handler(ctx, parsed)


#: The one registry the application uses. Tests build their own.
REGISTRY = Registry()
action = REGISTRY.action
