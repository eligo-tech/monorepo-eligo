"""The startup guard that refuses to serve data the database cannot isolate.

The probe needs a live Postgres; the judgement does not, and the judgement is
the part that can be wrong in a way anyone notices — either a deploy blocked
over nothing, or a workspace served another's rows because a new table shipped
without a policy.

`ALL_GOOD` mirrors what production actually reports today (21 tenant-scoped
tables, every one enabled + forced + policed), so a regression that drops a
policy shows up here as a failure rather than as a silent fail-open.
"""

from __future__ import annotations

import pytest

from app.core.database import isolation_problems

#: (name, rls_enabled, rls_forced, has_policy)
ALL_GOOD = [
    ("candidates", True, True, True),
    ("managers", True, True, True),
    ("receipts", True, True, True),
]


def test_a_sound_database_has_no_problems():
    assert isolation_problems("eligo_app", False, ALL_GOOD) == []


def test_a_bypassrls_runtime_role_is_a_problem():
    # The whole fail-closed story rests on this one property: without it an
    # un-pinned query returns every tenant's rows instead of none.
    problems = isolation_problems("postgres", True, ALL_GOOD)
    assert len(problems) == 1
    assert "BYPASSRLS" in problems[0]
    assert "postgres" in problems[0]


def test_a_table_with_no_policy_is_caught():
    # The create_all gap: a new table appears with the models and no migration
    # ever gave it a policy.
    tables = [*ALL_GOOD, ("interviews", True, True, False)]
    problems = isolation_problems("eligo_app", False, tables)
    assert problems == ["interviews is missing a tenant_isolation policy"]


def test_rls_enabled_but_not_forced_is_caught():
    # The subtle one. A policy exists and looks right in the dashboard, but
    # without FORCE the table owner silently bypasses it — which is exactly
    # the connection migrations and scripts use.
    problems = isolation_problems(
        "eligo_app", False, [("candidates", True, False, True)]
    )
    assert problems == ["candidates is missing FORCE ROW LEVEL SECURITY"]


def test_a_table_missing_everything_reports_everything():
    problems = isolation_problems(
        "eligo_app", False, [("projects", False, False, False)]
    )
    assert problems == [
        "projects is missing a tenant_isolation policy and ROW LEVEL SECURITY "
        "and FORCE ROW LEVEL SECURITY"
    ]


def test_problems_accumulate_across_role_and_tables():
    problems = isolation_problems(
        "postgres", True, [("candidates", True, True, False)]
    )
    assert len(problems) == 2


@pytest.mark.asyncio
async def test_the_guard_is_a_no_op_off_postgres():
    """The SQLite demo and this very test suite are single-tenant.

    If this ever raises, every test in the repo fails at import time — which
    is the point of pinning it.
    """
    from app.core.database import assert_runtime_rls_enforced

    await assert_runtime_rls_enforced()


# --- the probe that cannot run (review 2026-10-31 #5) -------------------------
#
# Before: a probe that could not RUN logged a warning and the app served
# anyway — "I could not check" was treated as "fine". In production that is
# the one answer the guard must never give. It now retries, then refuses.


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def one(self):
        return self._rows[0]

    def all(self):
        return self._rows


class _Conn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, statement):
        if "current_user" in str(statement):
            return _Result([("eligo_app", False)])
        return _Result(ALL_GOOD)


class _FlakyEngine:
    """Fails `failures` times, then connects."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.attempts = 0

    def connect(self):
        self.attempts += 1
        if self.attempts <= self.failures:
            raise OSError("connection refused")
        return _Conn()


@pytest.fixture
def production(monkeypatch):
    from app.core import database
    from app.core.config import settings

    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://app@db/eligo")
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "allow_insecure_rls", False)
    monkeypatch.setattr(database, "_PROBE_RETRY_SECONDS", 0)
    return database


async def test_a_probe_that_cannot_run_refuses_to_start(production, monkeypatch) -> None:
    flaky = _FlakyEngine(failures=99)
    monkeypatch.setattr(production, "engine", flaky)
    with pytest.raises(production.TenantIsolationNotEnforced, match="could not verify"):
        await production.assert_runtime_rls_enforced()
    assert flaky.attempts == production._PROBE_ATTEMPTS


async def test_a_brief_outage_at_boot_is_retried_not_fatal(production, monkeypatch) -> None:
    flaky = _FlakyEngine(failures=production._PROBE_ATTEMPTS - 1)
    monkeypatch.setattr(production, "engine", flaky)
    await production.assert_runtime_rls_enforced()  # does not raise
    assert flaky.attempts == production._PROBE_ATTEMPTS


async def test_the_explicit_override_still_lets_it_start(production, monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "allow_insecure_rls", True)
    monkeypatch.setattr(production, "engine", _FlakyEngine(failures=99))
    await production.assert_runtime_rls_enforced()  # logged, not raised
