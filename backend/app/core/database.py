"""Async SQLAlchemy 2.0 engine, session factory, and declarative ``Base``.

The engine is driven by ``settings.database_url``. The default (SQLite +
aiosqlite) means the app boots with no external services; switching to
``postgresql+asyncpg://...`` makes Postgres the system-of-record without any
code change.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(AsyncAttrs, DeclarativeBase):
    """Declarative base for every ORM model in the platform."""


# SQLite needs ``check_same_thread=False`` when used with an async pool.
_connect_args: dict[str, object] = (
    {"check_same_thread": False} if settings.is_sqlite else {}
)

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug and not settings.is_sqlite,
    future=True,
    connect_args=_connect_args,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped async session."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def create_all() -> None:
    """Create all tables. Scaffold convenience — replace with Alembic in prod.

    Importing the model registry here guarantees every table is registered on
    ``Base.metadata`` before ``create_all`` runs.
    """
    from app.domain import registry  # noqa: F401  (side-effect: model imports)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)