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
from app.domain.atsimport.connectors.base import AtsConnector, AtsSource
from app.domain.atsimport.connectors.file_upload import FileUploadSource

#: Every way a book of business can get in — read on a schedule or brought
#: as a file. One list, because that is the question a recruiter asks
#: ("can you take our data?"), not two.
_SOURCES: dict[str, AtsSource] = {
    AiFindConnector.key: AiFindConnector(),
    FileUploadSource.key: FileUploadSource(),
}


def available() -> list[str]:
    """Every source key, stable order."""
    return sorted(_SOURCES)


def pull_sources() -> list[str]:
    """Only the ones a workspace can store a credential for.

    A file has no login, is never fetched on a schedule, and must not show
    up as something the runner could pick up.
    """
    return sorted(k for k, s in _SOURCES.items() if s.mode == "pull")


def describe() -> list[dict]:
    """What the settings screen needs to draw one row per source."""
    return [
        {
            "key": s.key,
            "label": s.label,
            "hint": getattr(s, "hint", ""),
            "mode": s.mode,
            "needs": list(getattr(s, "needs", ())),
        }
        for _, s in sorted(_SOURCES.items())
    ]


def get_source(key: str) -> AtsSource:
    source = _SOURCES.get((key or "").lower().strip())
    if source is None:
        raise ValueError(
            f"unknown ATS source {key!r}; available: {', '.join(available())}"
        )
    return source


def get_connector(key: str) -> AtsConnector:
    """A source the product can FETCH. Raises for a file source.

    The runner calls this, so a file can never be scheduled by mistake —
    there is no login to schedule.
    """
    source = get_source(key)
    if source.mode != "pull" or not isinstance(source, AtsConnector):
        raise ValueError(f"{key!r} is not fetched by the product; it is uploaded")
    return source
