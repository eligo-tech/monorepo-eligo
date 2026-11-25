"""ELI-77: one key and one spelling per LinkedIn / XING profile.

A contact is added from a pasted profile link. The same profile arrives in many
spellings: `de.linkedin.com` or `www.`, with or without a trailing slash, with
`?trk=…` or `#about`, an umlaut typed or percent-encoded, a different case. Two
of those are one person, so the duplicate check compares `profile_key`, and the
stored link is `canonical_url` — never the raw paste.

Pure string work. Nothing here fetches the profile, and nothing may: no request
handler reads LinkedIn or XING (ARCHITECTURE.md RULE 1).
"""

from __future__ import annotations

import unicodedata
from urllib.parse import SplitResult, quote, unquote, urlsplit


def _split(url: str | None) -> SplitResult | None:
    """The link parsed the way a browser does, or None. A link carrying
    credentials (`user:pw@host`) is refused: what it names as the host is
    not where it points, and no profile link has them."""
    raw = (url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
        parts.port  # noqa: B018 — raises on a malformed port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or "@" in parts.netloc:
        return None
    return parts


def network(url: str | None) -> str | None:
    """Which network a link is on — `linkedin`, `xing` — if any."""
    parts = _split(url)
    host = (parts.hostname or "") if parts else ""
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "linkedin"
    if host == "xing.com" or host.endswith(".xing.com"):
        return "xing"
    return None


def _segments(url: str) -> list[str]:
    parts = _split(url)
    if parts is None:
        return []
    # NFC: a composed and a decomposed "ü" are one letter, so one profile.
    segs = [unicodedata.normalize("NFC", unquote(s)) for s in parts.path.split("/") if s]
    # "/in/../company/acme" is not a person.
    return [] if any(s in (".", "..") for s in segs) else segs


def _profile(url: str | None) -> tuple[str, str, list[str]] | None:
    """(network, kind, the path segments that name the person) — or None
    when the link is not a person's profile (a company page, a job ad)."""
    net = network(url)
    if net is None or not url:
        return None
    segs = _segments(url)
    if len(segs) < 2:
        return None
    kind = segs[0].lower()
    if net == "linkedin" and kind == "in":
        return net, "in", segs[1:2]
    if net == "linkedin" and kind == "pub":
        # Legacy public profile: /pub/<slug>/<a>/<b>/<c> — all of it is the id.
        return net, "pub", segs[1:]
    if net == "xing" and kind == "profile":
        # /profile/<Slug>/cv, /profile/<Slug>/portfolio — the slug is the person.
        return net, "profile", segs[1:2]
    return None


def profile_key(url: str | None) -> str | None:
    """`linkedin:in/anna-berg-1a2b3c` · `xing:profile/anna_berg` — the same
    for every spelling of one profile; None if the link is not a profile."""
    found = _profile(url)
    if found is None:
        return None
    net, kind, segs = found
    return f"{net}:{kind}/" + "/".join(s.lower() for s in segs)


def canonical_url(url: str | None) -> str | None:
    """The one spelling stored in `linkedin_url` / `xing_url`: https, `www.`
    host, no query, no fragment, no trailing slash; case kept as given."""
    found = _profile(url)
    if found is None:
        return None
    net, kind, segs = found
    host = "www.linkedin.com" if net == "linkedin" else "www.xing.com"
    return f"https://{host}/{kind}/" + "/".join(quote(s, safe="") for s in segs)
