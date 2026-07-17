"""Agent layer.

Each agent is a NARROW worker with an explicit input/output contract. The
cardinal rule: **agents cannot write to the system-of-record directly**. They
return an :class:`~app.agents.base.AgentResult` carrying *proposed* changes,
which the verification domain checks and commits (recording a Receipt).
"""

from app.agents.base import Agent, AgentResult

__all__ = ["Agent", "AgentResult"]