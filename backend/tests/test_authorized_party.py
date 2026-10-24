"""ADR 0002 §7.7 — a session token names the origin it was minted for.

Clerk signs tokens for an INSTANCE, not for an application. The signature
proves Clerk issued it; it does not prove our frontend asked for it. `azp`
is the origin that did, and without checking it a token picked up on any
other site sharing the instance is a valid credential against this API.

That is tolerable while the instance is a development one whose keys rotate
and whose only consumer is localhost. It stops being tolerable the day the
production instance exists, which is why this closes now.
"""

from __future__ import annotations

import pytest

from app.core import auth
from app.core.config import Settings


def _apply(monkeypatch, **overrides) -> None:
    monkeypatch.setattr(auth, "settings", Settings(**overrides))


ORIGINS = ["https://eligolabs.com", "https://www.eligolabs.com"]


def test_a_token_from_our_own_frontend_passes(monkeypatch) -> None:
    _apply(monkeypatch, cors_origins=ORIGINS)
    auth.check_authorized_party({"azp": "https://eligolabs.com"})


def test_a_token_minted_for_someone_else_is_refused(monkeypatch) -> None:
    _apply(monkeypatch, cors_origins=ORIGINS)
    with pytest.raises(auth.UnauthorizedParty) as raised:
        auth.check_authorized_party({"azp": "https://evil.example"})
    # The message must name the list to fix, or the operator sees a bare 401
    # and starts debugging their login.
    assert "evil.example" in str(raised.value)
    assert "ELIGO_CORS_ORIGINS" in str(raised.value)


def test_a_trailing_slash_is_the_same_origin(monkeypatch) -> None:
    # Pasting an origin out of a browser bar gets you the slash. Treating
    # that as a different origin would lock out the real frontend.
    _apply(monkeypatch, cors_origins=["https://eligolabs.com/"])
    auth.check_authorized_party({"azp": "https://eligolabs.com"})
    auth.check_authorized_party({"azp": "https://eligolabs.com/"})


def test_an_explicit_list_overrides_the_cors_one(monkeypatch) -> None:
    _apply(
        monkeypatch,
        cors_origins=["https://eligolabs.com"],
        clerk_authorized_parties=["https://admin.eligolabs.com"],
    )
    auth.check_authorized_party({"azp": "https://admin.eligolabs.com"})
    with pytest.raises(auth.UnauthorizedParty):
        auth.check_authorized_party({"azp": "https://eligolabs.com"})


def test_a_comma_separated_env_value_is_a_list(monkeypatch) -> None:
    # Railway and Vercel both hand you a plain string.
    s = Settings(clerk_authorized_parties="https://a.example, https://b.example")
    assert s.clerk_authorized_parties == ["https://a.example", "https://b.example"]


def test_a_token_without_azp_is_not_refused(monkeypatch) -> None:
    # Machine and backend-API tokens carry no `azp`. Rejecting them would
    # break callers this check was never aimed at, and Clerk's own guidance
    # is to skip rather than fail when the claim is absent.
    _apply(monkeypatch, cors_origins=ORIGINS)
    auth.check_authorized_party({"sub": "user_123"})


def test_no_allow_list_means_no_check(monkeypatch) -> None:
    # The SQLite demo and local dev have no origin to compare against.
    _apply(monkeypatch, cors_origins=[])
    auth.check_authorized_party({"azp": "https://anything.example"})
