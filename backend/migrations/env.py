"""Alembic environment — async, driven by app settings.

Reuses the app's async engine (so Supabase TLS / driver config is identical) and
the ORM metadata (via the model registry) as the autogenerate target.

**The default target is `settings.admin_url`, which on a developer machine is
the LIVE database** — `.env` holds the Supabase credentials, DDL has to run as
the owner rather than the NOBYPASSRLS app role, and `DATABASE_URL` is the app
role, so it deliberately is not read here. The consequence caught somebody out:
`DATABASE_URL=sqlite:///tmp.db alembic upgrade head`, typed to rehearse a
migration against a scratch database, silently migrated production instead.

`ALEMBIC_DATABASE_URL` is the way to point this somewhere else. It overrides
the target and nothing else; unset, behaviour is exactly as before, which is
what Railway runs on deploy.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.database import Base, admin_engine
from app.domain import registry  # noqa: F401 — imports every model onto Base.metadata

#: An explicit scratch target. Only this overrides the admin URL — see above.
_OVERRIDE = os.environ.get("ALEMBIC_DATABASE_URL") or None

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL without a DB connection (alembic upgrade --sql)."""
    context.configure(
        url=_OVERRIDE or settings.admin_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    # DDL runs on the owner/admin connection, not the (NOBYPASSRLS) app role.
    engine = create_async_engine(_OVERRIDE) if _OVERRIDE else admin_engine
    if _OVERRIDE:
        print(f"alembic: ALEMBIC_DATABASE_URL is set — migrating {_OVERRIDE.split('@')[-1]}")
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
