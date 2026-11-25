"""ELI-73: which ad in the corpus a pasted job-ad link points at.

The inverse of `schemas.source_detail_url`: from the source's own page for an
ad back to the reference the corpus stores it under — `(source, external_id)`,
the unique, indexed key of `hub_job_postings`. Pure string work: the link is
never opened (ARCHITECTURE.md RULE 1), so an ad Markt does not hold is simply
"not in Markt".

Deliberately NOT matched: `hub_job_postings.source_url` (the partner-board copy
a BA ad points to, e.g. StepStone). That column has no index, and an equality
scan over ~700k rows per keystroke on a Disk-IO-bound database is not a
lookup. A link Markt cannot place this way gets the paste-the-text path.
"""

from __future__ import annotations

from urllib.parse import unquote, urlsplit


def _parts(url: str | None) -> tuple[str, list[str]] | None:
    raw = (url or "").strip()
    if not raw or " " in raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    try:
        split = urlsplit(raw)
    except ValueError:
        return None
    # Credentials: what the text names as the host is not where it points.
    if split.scheme.lower() not in ("http", "https") or "@" in split.netloc:
        return None
    host = (split.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return host, [unquote(s) for s in split.path.split("/") if s]


def posting_ref(url: str | None) -> tuple[str, str] | None:
    """`(source, external_id)` of the ad a link is the source's own page for,
    or None. Query strings, fragments, `www.` and a trailing slash are noise."""
    found = _parts(url)
    if found is None:
        return None
    host, segs = found

    def at(*prefix: str) -> str | None:
        """The one segment after `prefix`, if the path is exactly that."""
        n = len(prefix)
        if len(segs) == n + 1 and [s.lower() for s in segs[:n]] == list(prefix):
            return segs[n]
        return None

    if host == "arbeitsagentur.de":
        refnr = at("jobsuche", "jobdetail")
        return ("bundesagentur", refnr) if refnr else None
    if host == "europa.eu":
        jv = at("eures", "portal", "jv-se", "jv-details")
        return ("eures", jv) if jv else None
    for suffix in (".jobs.personio.de", ".jobs.personio.com"):
        if host.endswith(suffix):
            slug, job = host[: -len(suffix)], at("job")
            return ("personio", f"{slug}:{job}") if slug and "." not in slug and job else None
    if host in ("job-boards.greenhouse.io", "boards.greenhouse.io", "job-boards.eu.greenhouse.io"):
        if len(segs) == 3 and segs[1].lower() == "jobs":
            return "greenhouse", f"{segs[0]}:{segs[2]}"
        return None
    # Board slugs are stored lower-case (each adapter's `valid_slug`); the
    # apply page is the same ad.
    if host == "jobs.ashbyhq.com":
        if len(segs) == 3 and segs[2].lower() == "application":
            segs = segs[:2]
        return ("ashby", f"{segs[0].lower()}:{segs[1]}") if len(segs) == 2 else None
    if host in ("jobs.lever.co", "jobs.eu.lever.co"):
        if len(segs) == 3 and segs[2].lower() == "apply":
            segs = segs[:2]
        if len(segs) != 2:
            return None
        segs = [segs[0].lower(), segs[1]]
        prefix = "eu:" if host == "jobs.eu.lever.co" else ""
        return "lever", f"{prefix}{segs[0]}:{segs[1]}"
    return None
