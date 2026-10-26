"""What a crash report is allowed to carry out of this process.

The record holds candidates' names, e-mail addresses, telephone numbers and
salary expectations, belonging to tenants who are not us. An error tracker
serialises the request that failed and the stack that failed it, so without
care it is a supported, authenticated export of exactly that — straight past
the RLS the rest of the system is built on.

These tests are therefore mostly negative: they assert what is ABSENT. Several
pin an SDK default rather than our own code, deliberately, because the default
is what would hurt us and an SDK is free to change its mind in a minor
release. `test_a_candidate_in_a_frame_would_leak_by_default` is the one that
earns its place: it shows the leak happening when the setting is off, so the
setting is never mistaken for decoration.
"""

from __future__ import annotations

import json
import uuid

import pytest
import sentry_sdk

from app.core import observability
from app.core.context import ActorRef, current_actor_var
from app.core.database import current_tenant_var

CANDIDATE_EMAIL = "nesim.celik@hotmail.de"
CANDIDATE_NAME = "Nesim Celik"
CANDIDATE_SALARY = 70000


@pytest.fixture(autouse=True)
def _clean_context():
    """No ambient tenant or actor; each test states its own."""
    t = current_tenant_var.set(None)
    a = current_actor_var.set(None)
    yield
    current_tenant_var.reset(t)
    current_actor_var.reset(a)


@pytest.fixture
def captured(monkeypatch) -> list[dict]:
    """Initialise the SDK against an in-process transport and collect events."""
    events: list[dict] = []
    sentry_sdk.init(
        dsn="https://key@localhost/1",
        transport=events.append,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        traces_sample_rate=0.0,
        before_send=observability._scrub,
    )
    yield events
    sentry_sdk.init(dsn=None)  # tear the client down again


# ── the switch ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("dsn", [None, "", "   "])
def test_without_a_dsn_the_sdk_is_never_initialised(monkeypatch, dsn) -> None:
    """Off means no client, no hooks, no network — not "a client with no DSN".

    Asserted by watching whether we call `init` at all, rather than by asking
    the SDK afterwards: `sentry_sdk.init(dsn=None)` still reports an active
    client, so that question has a misleading answer.

    A variable present but empty — the usual shape of an unset value in a
    deploy config — counts as absent.
    """
    monkeypatch.setattr(observability.settings, "sentry_dsn", dsn)
    called: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: called.append(kw))
    observability.configure_error_reporting()
    assert called == []


def test_a_dsn_initialises_it_with_every_guard_on(monkeypatch) -> None:
    """The four options this module exists to set, pinned as a group."""
    monkeypatch.setattr(
        observability.settings, "sentry_dsn", "https://key@glitchtip.internal/1"
    )
    called: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: called.append(kw))
    observability.configure_error_reporting()

    assert len(called) == 1
    opts = called[0]
    assert opts["send_default_pii"] is False
    assert opts["include_local_variables"] is False
    assert opts["max_request_body_size"] == "never"
    assert opts["traces_sample_rate"] == 0.0
    assert opts["before_send"] is observability._scrub


def test_a_broken_dsn_does_not_stop_the_app(monkeypatch) -> None:
    """Reporting a failure must never become one."""
    monkeypatch.setattr(observability.settings, "sentry_dsn", "not-a-dsn")
    observability.configure_error_reporting()  # must not raise
    sentry_sdk.init(dsn=None)


# ── the leak that matters most ────────────────────────────────────────────


def _raise_holding_a_candidate(email: str, salary: int) -> None:
    """Values arrive as ARGUMENTS, the way they do in production.

    Not as literals in this function's body: Sentry sends the source lines
    around a failing frame (`pre_context` / `context_line` / `post_context`)
    quite separately from the locals, so a literal here would leak through
    the source and the test would be measuring the wrong thing. It did, in
    the first draft, which is how this comment came to exist.
    """
    raise ValueError("could not save candidate")


def test_a_candidate_in_a_failing_frame_never_reaches_the_wire(captured) -> None:
    try:
        _raise_holding_a_candidate(CANDIDATE_EMAIL, CANDIDATE_SALARY)
    except ValueError:
        sentry_sdk.capture_exception()
    sentry_sdk.flush()

    blob = json.dumps(captured, default=str)
    assert CANDIDATE_EMAIL not in blob
    assert str(CANDIDATE_SALARY) not in blob
    # Still worth sending: without these the report is useless and the trade
    # would not be worth making.
    assert "could not save candidate" in blob
    assert "_raise_holding_a_candidate" in blob


def test_a_candidate_in_a_frame_would_leak_by_default() -> None:
    """The inverse, so the setting is never mistaken for decoration.

    `include_local_variables` defaults to TRUE in the Python SDK. If this test
    ever fails because the leak stopped happening, the SDK changed its default
    and our option became redundant — worth knowing either way.
    """
    events: list[dict] = []
    sentry_sdk.init(dsn="https://key@localhost/1", transport=events.append)
    try:
        _raise_holding_a_candidate(CANDIDATE_EMAIL, CANDIDATE_SALARY)
    except ValueError:
        sentry_sdk.capture_exception()
    sentry_sdk.flush()
    sentry_sdk.init(dsn=None)

    assert CANDIDATE_EMAIL in json.dumps(events, default=str)


# ── the scrubber ──────────────────────────────────────────────────────────


def test_a_name_in_the_query_string_is_removed() -> None:
    """The candidate search puts a person's name in the URL.

    No SDK option covers this. `send_default_pii` does not, because a URL is
    not PII in general — it is here.
    """
    event = observability._scrub(
        {
            "request": {
                "url": f"https://api.eligolabs.com/api/v1/candidates?q={CANDIDATE_NAME}",
                "query_string": f"q={CANDIDATE_NAME}",
                "method": "GET",
            }
        },
        {},
    )
    blob = json.dumps(event)
    assert CANDIDATE_NAME not in blob
    assert "Celik" not in blob
    # The route itself is the useful half and survives.
    assert event["request"]["url"].endswith("/api/v1/candidates")
    assert event["request"]["method"] == "GET"


@pytest.mark.parametrize("field", ["cookies", "headers", "data", "env"])
def test_request_fields_that_carry_the_record_are_dropped(field) -> None:
    event = observability._scrub(
        {"request": {"url": "https://x/y", field: {"secret": CANDIDATE_EMAIL}}}, {}
    )
    assert field not in event["request"]
    assert CANDIDATE_EMAIL not in json.dumps(event)


def test_an_event_with_no_request_is_left_alone() -> None:
    """A crash in a cron job has no request; the scrubber must not assume one."""
    assert observability._scrub({"message": "cron failed"}, {}) == {
        "message": "cron failed"
    }


# ── what we DO want to know ───────────────────────────────────────────────


def test_the_tenant_is_tagged_as_an_opaque_id() -> None:
    """Enough to answer "whose workspace?", not enough to learn who they are."""
    tenant = uuid.uuid4()
    current_tenant_var.set(str(tenant))
    event = observability._scrub({}, {})
    assert event["tags"]["tenant"] == str(tenant)


def test_the_actor_is_tagged_but_never_named() -> None:
    """The Clerk subject identifies a user to US and to nobody else.

    `current_actor_var` also carries the person's name, because the receipt
    ledger needs it. A crash reporter does not, so it does not get it.
    """
    current_actor_var.set(ActorRef(user_id="user_3H4n", name="Thomas Bausch"))
    event = observability._scrub({}, {})
    assert event["tags"]["actor"] == "user_3H4n"
    assert "Thomas Bausch" not in json.dumps(event)


def test_a_job_with_no_tenant_is_tagged_with_nothing() -> None:
    assert "tags" not in observability._scrub({}, {})


def test_the_failing_source_line_is_sent(captured) -> None:
    """Not a leak, but worth stating: the SOURCE around the failure goes too.

    `include_local_variables=False` withholds the values of locals; it does
    not withhold the code. That is the half that makes a report readable, and
    it is only acceptable because the collector is ours — shipping this
    product's source to a third-party SaaS would be a separate decision
    nobody has taken.
    """
    try:
        _raise_holding_a_candidate(CANDIDATE_EMAIL, CANDIDATE_SALARY)
    except ValueError:
        sentry_sdk.capture_exception()
    sentry_sdk.flush()

    frames = captured[0]["exception"]["values"][0]["stacktrace"]["frames"]
    assert any(f.get("context_line") for f in frames)
