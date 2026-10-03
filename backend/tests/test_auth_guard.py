"""The one fail-open in the stack, closed.

`auth_enabled` defaults to False so tests and the SQLite demo need no setup.
With auth off, `get_current_tenant` hands every anonymous caller the DEFAULT
tenant — fine against a scratch file, catastrophic against the production
database, and silent either way: nothing errors, the wrong workspace is simply
served to whoever asks.
"""

from __future__ import annotations

import pytest

from app.core import auth
from app.core.config import Settings


def _apply(monkeypatch, **overrides) -> None:
    monkeypatch.setattr(auth, "settings", Settings(**overrides))


def test_postgres_without_auth_refuses_to_start(monkeypatch) -> None:
    _apply(
        monkeypatch,
        auth_enabled=False,
        database_url="postgresql+asyncpg://u:p@db.example/eligo",
    )
    with pytest.raises(auth.InsecureConfiguration) as raised:
        auth.assert_auth_configured()
    # The message has to tell the operator what to set; a bare refusal gets
    # "fixed" by deleting the check.
    assert "ELIGO_AUTH_ENABLED" in str(raised.value)
    # And it must not print the password.
    assert ":p@" not in str(raised.value)


def test_postgres_with_auth_is_fine(monkeypatch) -> None:
    _apply(
        monkeypatch,
        auth_enabled=True,
        database_url="postgresql+asyncpg://u:p@db.example/eligo",
    )
    auth.assert_auth_configured()


def test_sqlite_without_auth_is_the_demo_and_still_boots(monkeypatch) -> None:
    """This is the path CI itself runs on."""
    _apply(monkeypatch, auth_enabled=False, database_url="sqlite+aiosqlite:///./x.db")
    auth.assert_auth_configured()


def test_a_local_postgres_can_opt_out_explicitly(monkeypatch) -> None:
    _apply(
        monkeypatch,
        auth_enabled=False,
        allow_insecure_no_auth=True,
        database_url="postgresql+asyncpg://u:p@localhost/eligo",
    )
    auth.assert_auth_configured()
