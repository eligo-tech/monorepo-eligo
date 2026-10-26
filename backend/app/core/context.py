"""Who the current request belongs to, for code too deep to be handed an Actor.

`current_tenant_var` in `core.database` exists for exactly this reason and is
read by the transaction listener; this is its sibling for attribution. Both are
ContextVars rather than module globals, so two concurrent requests can never
see each other's.

It lives in its own module to stay importable from both ends: `core.auth`
writes it and `domain.verification` reads it, and either importing the other
would close a cycle.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import NamedTuple


class ActorRef(NamedTuple):
    """The smallest attributable identity: who it was, and what to call them.

    Deliberately not the full `Actor` — a receipt has no use for the role, and
    copying the whole object here would make `core.auth` a dependency of the
    ledger.
    """

    #: Clerk `sub`. None in the auth-disabled demo, where there is no person.
    user_id: str | None
    #: What a receipt should call them; may be the raw id when the session
    #: token carries no name claim (see `auth._actor_name`).
    name: str


#: None outside a request — a cron run or a script genuinely has no actor, and
#: recording one would be a lie.
current_actor_var: ContextVar[ActorRef | None] = ContextVar(
    "current_actor", default=None
)
