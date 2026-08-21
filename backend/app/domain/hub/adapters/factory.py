"""Source-adapter registry — one line per source.

Same shape as `documents/extraction/factory.py`: callers name a source, the
factory builds it. Unknown names raise rather than silently no-op, because a
typo in a crawl config must fail loudly instead of quietly ingesting nothing.
"""

from __future__ import annotations

from collections.abc import Callable

from app.domain.hub.adapters.base import SourceAdapter
from app.domain.hub.adapters.bundesagentur import BundesagenturAdapter

_BUILDERS: dict[str, Callable[[], SourceAdapter]] = {
    BundesagenturAdapter.name: BundesagenturAdapter,
}


def available_sources() -> list[str]:
    return sorted(_BUILDERS)


def get_source_adapter(name: str) -> SourceAdapter:
    builder = _BUILDERS.get(name.lower().strip())
    if builder is None:
        raise ValueError(
            f"unknown hub source {name!r}; available: {', '.join(available_sources())}"
        )
    return builder()
