"""The action registry: one list of what can be done, and who may do it.

Every capability an AI client gets is an action here, so the refusals below
are the guarantees the MCP server inherits. Each test uses its own registry so
a test action can never leak into what the server exposes.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import BaseModel

from app.actions import core
from app.actions.core import ActionContext, Effect
from app.core.auth import ADMIN, RECRUITER, Actor


class _Args(BaseModel):
    limit: int = 10


def _actor(*, role: str = RECRUITER, kind: str = "human") -> Actor:
    return Actor(
        tenant_id=uuid.uuid4(),
        user_id="user_1",
        name="Test",
        role=role,
        role_known=True,
        kind=kind,
        client_id="client_1" if kind == "agent" else None,
    )


def _ctx(actor: Actor) -> ActionContext:
    return ActionContext(session=None, actor=actor)  # type: ignore[arg-type]


@pytest.fixture
def registry() -> core.Registry:
    reg = core.Registry()

    @reg.action("t.read", effect=Effect.READ, description="read", input=_Args)
    async def _read(ctx: ActionContext, args: _Args) -> dict:
        return {"limit": args.limit, "tenant": str(ctx.actor.tenant_id)}

    @reg.action(
        "t.admin_read",
        effect=Effect.READ,
        description="admin only",
        input=_Args,
        roles={ADMIN},
    )
    async def _admin_read(ctx: ActionContext, args: _Args) -> dict:
        return {"ok": True}

    for effect in (Effect.PROPOSE, Effect.COMMIT, Effect.EXTERNAL):

        @reg.action(f"t.{effect.value}", effect=effect, description=effect.value, input=_Args)
        async def _write(ctx: ActionContext, args: _Args) -> dict:
            return {"wrote": True}

    return reg


def test_actor_defaults_to_human() -> None:
    # Every existing caller builds an Actor without `kind`; they are people.
    actor = Actor(tenant_id=uuid.uuid4(), user_id="u", name="n", role=RECRUITER, role_known=True)
    assert actor.kind == "human"
    assert actor.client_id is None


async def test_a_permitted_read_runs_with_validated_args(registry) -> None:
    out = await registry.invoke("t.read", _ctx(_actor()), {"limit": 3})
    assert out["limit"] == 3


async def test_unknown_action_is_refused(registry) -> None:
    with pytest.raises(core.UnknownAction):
        await registry.invoke("t.nope", _ctx(_actor()), {})


async def test_wrong_role_is_refused(registry) -> None:
    with pytest.raises(core.ActionForbidden):
        await registry.invoke("t.admin_read", _ctx(_actor(role=RECRUITER)), {})
    # Control: the role it was written for gets through.
    assert await registry.invoke("t.admin_read", _ctx(_actor(role=ADMIN)), {})


@pytest.mark.parametrize("effect", [Effect.COMMIT, Effect.EXTERNAL])
async def test_an_agent_may_not_commit_or_reach_outside(registry, effect) -> None:
    # PR 4: an agent may read and PROPOSE (test_actions_proposals.py); a write
    # or anything leaving the system stays refused.
    with pytest.raises(core.ActionForbidden):
        await registry.invoke(f"t.{effect.value}", _ctx(_actor(kind="agent")), {})


@pytest.mark.parametrize("effect", [Effect.COMMIT])
async def test_a_human_may_call_non_read_actions(registry, effect) -> None:
    # Control for the test above: the refusal is about the agent, not the effect.
    assert await registry.invoke(f"t.{effect.value}", _ctx(_actor()), {})


async def test_invalid_args_are_refused_before_the_handler_runs(registry) -> None:
    with pytest.raises(core.ActionInputInvalid):
        await registry.invoke("t.read", _ctx(_actor()), {"limit": "many"})


def test_a_name_registers_once(registry) -> None:
    with pytest.raises(ValueError):

        @registry.action("t.read", effect=Effect.READ, description="dup", input=_Args)
        async def _dup(ctx: ActionContext, args: _Args) -> dict:
            return {}


def test_agent_exposed_lists_reads_and_proposals_only(registry) -> None:
    names = {spec.name for spec in registry.agent_exposed()}
    assert names == {"t.read", "t.admin_read", "t.propose"}
