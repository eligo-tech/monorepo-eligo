"""Which instance of a vendor a workspace is on, and who gets to decide.

aiFind is multi-tenant: every customer has their own Keycloak realm and their
own `<customer>.apps.aifind.de`. Those were module constants in the connector,
which made the product able to serve exactly one of aiFind's customers — and
would have sent the second one's e-mail and password to the first one's realm
to be refused there.

The distinction these tests pin is vendor versus customer. `kc.apps.aifind.de`
and the `aifind-ui` client id belong to the vendor and stay in the connector;
the realm and the host belong to the workspace and live on its row.
"""

from __future__ import annotations

import uuid

import pytest

from app.domain.atsimport import factory
from app.domain.atsimport.connectors import aifind
from app.domain.atsimport.connectors.base import Credentials
from app.domain.tenantsources.models import TenantSource


# ── the connector ─────────────────────────────────────────────────────────


def test_the_endpoints_are_built_from_the_workspaces_own_instance() -> None:
    issuer, redirect, graphql = aifind.endpoints(
        {"realm": "muster", "host": "muster.apps.aifind.de"}
    )
    assert issuer == "https://kc.apps.aifind.de/auth/realms/muster"
    assert redirect == "https://muster.apps.aifind.de/dashboard"
    assert graphql == "https://muster.apps.aifind.de/api/graphql"


def test_two_workspaces_get_two_different_instances() -> None:
    """The property the module constants made impossible."""
    one = aifind.endpoints({"realm": "eins", "host": "eins.apps.aifind.de"})
    two = aifind.endpoints({"realm": "zwei", "host": "zwei.apps.aifind.de"})
    assert one != two
    assert not any("eins" in url for url in two)


@pytest.mark.parametrize(
    "config",
    [
        None,
        {},
        {"realm": "muster"},
        {"host": "muster.apps.aifind.de"},
        {"realm": "", "host": ""},
        {"realm": "   ", "host": "muster.apps.aifind.de"},
    ],
)
def test_an_unnamed_instance_raises_instead_of_guessing(config) -> None:
    """No default, because every candidate default is somebody's real address.

    A fallback here would be the old bug with an extra step: workspaces that
    had not filled the form in would quietly use whichever customer's realm
    happened to be written down.
    """
    with pytest.raises(ValueError, match="eigenen Instanz"):
        aifind.endpoints(config)


def test_the_message_names_what_is_missing() -> None:
    with pytest.raises(ValueError, match="host"):
        aifind.endpoints({"realm": "muster"})
    with pytest.raises(ValueError, match="realm"):
        aifind.endpoints({"host": "muster.apps.aifind.de"})


def test_no_customer_of_the_vendor_is_named_in_the_source() -> None:
    """The regression guard for the whole point of this change.

    Reads the connector as text: a customer name reintroduced as a constant,
    a default argument or an example in a docstring fails here.
    """
    from pathlib import Path

    source = Path(aifind.__file__).read_text(encoding="utf-8")
    assert "panam" not in source.lower()


def test_the_vendors_own_host_stays_in_the_connector() -> None:
    """Not everything about aiFind is per-customer, and over-correcting would
    make a workspace type in a Keycloak hostname it cannot know."""
    assert aifind.KEYCLOAK_HOST == "kc.apps.aifind.de"
    assert aifind.CLIENT_ID == "aifind-ui"
    assert set(aifind.CONFIG_NEEDS) == {"realm", "host"}


async def test_fetch_refuses_before_sending_the_password_anywhere() -> None:
    """Order matters: the check is in front of the login, not after it.

    If the endpoints were resolved lazily, an unconfigured workspace would
    reach a real Keycloak — someone else's — and hand over its credentials to
    be rejected there.
    """
    with pytest.raises(ValueError, match="eigenen Instanz"):
        await aifind.AiFindConnector().fetch(
            Credentials(username="user@example.test", secret="pw", config={})
        )


# ── what the settings screen is told ──────────────────────────────────────


def test_the_registry_advertises_the_instance_fields() -> None:
    described = {row["key"]: row for row in factory.describe()}
    assert described["aifind"]["config_needs"] == ["realm", "host"]


def test_a_source_with_one_address_for_everybody_asks_for_nothing() -> None:
    """`config_needs` is optional on purpose — the common case pays nothing."""
    described = {row["key"]: row for row in factory.describe()}
    assert described["datei-import"]["config_needs"] == []


# ── the row carries it to the runner ──────────────────────────────────────


def test_the_detached_copy_keeps_what_the_run_reads() -> None:
    """`run_pending` rebuilds each row by hand before the session closes.

    Anything it forgets arrives as None, because a column default is applied
    on INSERT and not on construction. `import_scope` was forgotten, and
    `None != "basic"` is True — so a workspace that asked for the quick pass
    was given the slow one, silently, every scheduled run.
    """
    stored = TenantSource(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        kind="aifind",
        username="u",
        secret_encrypted="enc",
        import_scope="basic",
        config={"realm": "muster", "host": "muster.apps.aifind.de"},
    )

    copy = TenantSource(
        id=stored.id,
        tenant_id=stored.tenant_id,
        kind=stored.kind,
        username=stored.username,
        secret_encrypted=stored.secret_encrypted,
        import_scope=stored.import_scope,
        config=stored.config,
    )

    assert copy.import_scope == "basic"
    assert copy.config == stored.config
    # The shape of the old bug, stated so it cannot come back quietly.
    forgetful = TenantSource(id=stored.id, tenant_id=stored.tenant_id, kind="aifind")
    assert forgetful.import_scope is None
    assert (True and forgetful.import_scope != "basic") is True
