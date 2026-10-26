"""Crash reporting, with the record's data kept out of it.

An error tracker is the one component that reads every other component's data:
it serialises the request that failed and the stack that failed it, and both
are full of whatever the product happens to hold. What this product happens to
hold is candidates' names, e-mail addresses, telephone numbers, dates of birth
and salary expectations — belonging to tenants who are not us, obtained under
GDPR Art. 14, and kept apart by RLS that an exporter walks straight past.

So the default is OFF (`ELIGO_SENTRY_DSN` unset → the SDK is never
initialised), the target is a collector inside our own estate rather than a
SaaS we would have to name as a processor, and four separate things are turned
off before the first event can leave:

==========================  =======================================
what                        why it matters HERE
==========================  =======================================
`send_default_pii=False`    cookies, client IP, the session's user
`include_local_variables`   a frame mid-`update_candidate` holds the
  `=False`                  candidate — the single biggest leak, and
                            on by default in the Python SDK
`max_request_body_size`     `PATCH /candidates/{id}` is a body made
  `="never"`                entirely of one person's personal data
`before_send=_scrub`        the query string: `/candidates?q=Nesim`
                            is a name, and nothing above removes it
==========================  =======================================

What is deliberately KEPT: the exception type, the stack frames, the route
template, the HTTP method, and two opaque identifiers — the tenant's UUID and
the actor's Clerk `sub`. Those answer "whose workspace, which user, which
endpoint" without telling the collector a single thing about a human being.
The actor's NAME is dropped even though `current_actor_var` carries it, for
exactly that reason.

The cost is real: a stack trace without locals is harder to debug. For a
record holding other people's personal data that is the right way round, and
the tenant tag usually narrows it enough to reproduce.

If the collector is unreachable the SDK drops events and the request is
unaffected — reporting a failure must never become one.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.context import current_actor_var
from app.core.database import current_tenant_var
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Request fields that cannot survive contact with this product's data. Sentry
#: already drops cookies when `send_default_pii` is off; the rest it keeps.
_DROP_FROM_REQUEST = ("cookies", "headers", "data", "env")


def _scrub(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:  # noqa: ARG001
    """Last gate before an event leaves the process.

    Everything here is belt-and-braces over an SDK option that should already
    have handled it, except the query string, which no option covers: the
    candidate search puts a person's name in the URL, and a URL is the one
    field every tracker records.
    """
    request = event.get("request")
    if isinstance(request, dict):
        for key in _DROP_FROM_REQUEST:
            request.pop(key, None)
        # `/api/v1/candidates?q=Nesim+Celik` — the name is the query.
        request.pop("query_string", None)
        url = request.get("url")
        if isinstance(url, str) and "?" in url:
            request["url"] = url.split("?", 1)[0]

    tenant = current_tenant_var.get()
    if tenant:
        # The UUID, never the workspace's name. It answers "whose?" for us and
        # nothing at all for the collector.
        event.setdefault("tags", {})["tenant"] = str(tenant)

    actor = current_actor_var.get()
    if actor is not None and actor.user_id:
        # The Clerk subject only. `actor.name` is a real person's name and is
        # deliberately left behind.
        event.setdefault("tags", {})["actor"] = actor.user_id

    return event


def configure_error_reporting() -> None:
    """Initialise crash reporting if a DSN is configured. Otherwise do nothing.

    Never raises. A misconfigured reporter must not stop the API serving — it
    exists to tell us about failures, not to cause them.
    """
    dsn = (settings.sentry_dsn or "").strip()
    if not dsn:
        logger.info("error reporting off (no ELIGO_SENTRY_DSN)")
        return

    try:
        import sentry_sdk
    except ImportError:
        # The dependency lives in the `monitoring` extra, so a scaffold install
        # that sets a DSN would otherwise fail at startup over a reporter.
        logger.warning(
            "ELIGO_SENTRY_DSN is set but sentry-sdk is not installed "
            '(pip install ".[monitoring]") — error reporting is off'
        )
        return

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=settings.env,
            # sentry-sdk 2.73 deprecates this in favour of `data_collection`
            # and warns about it. Still honoured, and the replacement's shape
            # is not verified here — changing it blind would be changing the
            # one option that keeps cookies and client IPs out.
            send_default_pii=False,
            include_local_variables=False,
            max_request_body_size="never",
            # Errors only. GlitchTip's tracing support is partial, and
            # transaction volume is the thing that exhausts a small instance.
            traces_sample_rate=0.0,
            before_send=_scrub,
        )
    except Exception as exc:  # noqa: BLE001 — a reporter may not break startup
        logger.warning("error reporting could not start: %s", exc)
        return

    logger.info("error reporting on (%s), PII stripped before send", settings.env)
