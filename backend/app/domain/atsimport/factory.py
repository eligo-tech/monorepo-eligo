"""ATS-connector registry — one line per system.

Same shape as `hub/adapters/factory.py` and `documents/extraction/factory.py`:
callers name a system, the factory hands back something that satisfies
`AtsConnector`. Unknown names raise rather than silently no-op, because a
typo in a workspace's source configuration must fail loudly instead of
quietly importing nothing.

The registry is also what the product ASKS: the settings screen lists what is
here, the credential store validates against it, and the scheduled runner
dispatches on it. Nothing else in the codebase may name a vendor.
"""

from __future__ import annotations

from app.domain.atsimport.connectors.aifind import AiFindConnector
from app.domain.atsimport.connectors.base import AtsConnector

_CONNECTORS: dict[str, AtsConnector] = {
    AiFindConnector.key: AiFindConnector(),
}


def available() -> list[str]:
    """Connector keys, stable order — what a workspace may configure."""
    return sorted(_CONNECTORS)


def describe() -> list[dict]:
    """What the settings screen needs to draw a form per system."""
    return [
        {"key": c.key, "label": c.label, "needs": list(c.needs)}
        for _, c in sorted(_CONNECTORS.items())
    ]


def get_connector(key: str) -> AtsConnector:
    connector = _CONNECTORS.get((key or "").lower().strip())
    if connector is None:
        raise ValueError(
            f"unknown ATS source {key!r}; available: {', '.join(available())}"
        )
    return connector
