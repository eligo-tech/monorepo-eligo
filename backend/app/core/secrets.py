"""Symmetric encryption for the few secrets the record has to hold.

A tenant's ATS password is the first of them. It cannot be hashed — the
importer has to replay it against the source's login form — so it is encrypted
at rest with a key the database never sees, and decrypted only in the process
that performs the import.

Fail-closed on purpose: with no key configured, `encrypt` raises rather than
storing a password in the clear. A workspace that cannot save its credential
is a nuisance; a workspace that saves it readable in a table everyone's
backups touch is an incident.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings


class SecretsNotConfigured(RuntimeError):
    """No `ELIGO_SECRET_KEY`, so secrets can be neither stored nor read."""


@lru_cache(maxsize=1)
def _cipher():
    from cryptography.fernet import Fernet  # lazy: only needed when used

    key = settings.secret_key
    if not key:
        raise SecretsNotConfigured(
            "ELIGO_SECRET_KEY is not set — generate one with "
            '`python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"` and set it on the service.'
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:  # malformed key is a configuration error
        raise SecretsNotConfigured(
            f"ELIGO_SECRET_KEY is not a valid Fernet key: {exc}"
        ) from exc


def configured() -> bool:
    """Whether secrets can be handled at all — checked before offering a form."""
    try:
        _cipher()
    except SecretsNotConfigured:
        return False
    return True


def encrypt(plaintext: str) -> str:
    """Plaintext → an opaque token safe to store in a normal column."""
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Token → plaintext. Raises if the key changed or the value is corrupt."""
    return _cipher().decrypt(token.encode()).decode()


def reset_cache() -> None:
    """Forget the cached cipher — for tests that change the key."""
    _cipher.cache_clear()
