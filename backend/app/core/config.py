"""Application settings.

Uses ``pydantic-settings`` so configuration is read from environment variables
(prefix ``ELIGO_``) and an optional ``.env`` file. Every default is chosen so
the scaffold starts with ZERO external services (SQLite fallback).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application configuration."""

    model_config = SettingsConfigDict(
        env_prefix="ELIGO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,  # allow constructing by field name, not only env alias
    )

    # --- App -------------------------------------------------------------
    app_name: str = "eligo-tech"
    env: str = "local"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # --- Database --------------------------------------------------------
    # Default is async SQLite so the app runs with no external dependencies.
    # Swap for Postgres (`postgresql+asyncpg://...`) as system-of-record.
    database_url: str = "sqlite+aiosqlite:///./eligo.db"

    # Create tables automatically on startup. Fine for the scaffold / SQLite;
    # in production this is replaced by Alembic migrations.
    auto_create_tables: bool = True

    # Echo SQL to logs. Off by default — set ELIGO_DB_ECHO=true to debug queries.
    db_echo: bool = False

    # Require TLS for the DB connection. Managed Postgres (e.g. Supabase) needs
    # this; ignored for SQLite. Set ELIGO_DB_SSL=true when using Supabase.
    db_ssl: bool = False
    # Verify the server certificate. Supabase's pooler presents a chain that
    # isn't in the default trust store, so dev connections set this false.
    # In production, pin the Supabase CA via ELIGO_DB_SSL_ROOT_CERT instead.
    db_ssl_verify: bool = True
    db_ssl_root_cert: str | None = None

    # DB role to run tenant-scoped queries as (via SET LOCAL ROLE) so Row-Level
    # Security is actually enforced. Managed Postgres often connects as a
    # BYPASSRLS superuser (Supabase `postgres`), for which RLS is ignored; set
    # ELIGO_DB_APP_ROLE to a NOBYPASSRLS role (e.g. `eligo_app`) to make it bite.
    # Unset → no role switch (RLS off / single-tenant demo). Postgres-only.
    #
    # Two ways to get RLS-enforced isolation, weakest → strongest:
    #   1. SET LOCAL ROLE (legacy): connect as `postgres`, set ELIGO_DB_APP_ROLE.
    #      Only fail-closed for transactions that pin a tenant; an un-pinned query
    #      runs as the BYPASSRLS connection role and sees ALL tenants (fail-open).
    #   2. Dedicated login role (preferred, fail-closed): point ELIGO_DATABASE_URL
    #      at the NOBYPASSRLS role itself, and ELIGO_ADMIN_DATABASE_URL at an
    #      owner/superuser for DDL. Then the connection can NEVER bypass RLS, so an
    #      un-pinned query returns zero rows no matter what the app code does.
    db_app_role: str | None = None

    # Password used by scripts/apply_rls to provision the app role as a LOGIN role
    # (so ELIGO_DATABASE_URL can connect *as* it — mode 2 above). Provisioning-only;
    # unset → the role is created/kept NOLOGIN (mode 1). Never logged.
    db_app_role_password: str | None = None

    # Owner/superuser connection used ONLY for DDL (migrations, create_all) and
    # cross-tenant admin scripts — never for request traffic. Supabase `postgres`.
    # Unset → falls back to ``database_url`` (single-connection dev / SQLite).
    admin_database_url: str | None = None

    # --- LLM extraction --------------------------------------------------
    # Vendor-neutral: the factory selects an extractor by provider. "openai"
    # uses the OpenAI-backed extractor; "heuristic" forces the offline parser.
    # Any provider falls back to the heuristic parser if unavailable.
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    # Read the standard OPENAI_API_KEY (unprefixed) so the SDK's own default and
    # our config agree. Never logged. Absent → the factory falls back to heuristic.
    openai_api_key: str | None = Field(
        default=None, validation_alias="OPENAI_API_KEY"
    )

    # --- Auth (Clerk) ----------------------------------------------------
    # When false, requests run as the default tenant (no login) — the scaffold
    # default so tests/demo work with no auth provider. Set true in production.
    auth_enabled: bool = False
    clerk_secret_key: str | None = Field(
        default=None, validation_alias="CLERK_SECRET_KEY"
    )
    # The publishable key is public (client-side). Read either name.
    clerk_publishable_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "ELIGO_CLERK_PUBLISHABLE_KEY",
            "VITE_CLERK_PUBLISHABLE_KEY",
            "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
        ),
    )
    # JWKS URL + issuer are derived from the publishable key when unset.
    clerk_jwks_url: str | None = None
    clerk_issuer: str | None = None

    # --- CORS ------------------------------------------------------------
    # NoDecode stops pydantic-settings from JSON-parsing the env value at the
    # source level (which would reject a plain/comma-separated string before the
    # validator runs). _split_cors below accepts both a JSON array and a plain,
    # comma-separated list — e.g. ELIGO_CORS_ORIGINS=https://a.app,https://b.app.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:5173",
        ]
    )

    # --- Multi-tenancy ---------------------------------------------------
    # Default tenant used by demo/seed endpoints. Every core table carries a
    # ``tenant_id``; real requests would resolve it from auth context.
    default_tenant_id: UUID = UUID("00000000-0000-0000-0000-000000000001")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, value: object) -> object:
        """Accept a JSON array OR a plain comma-separated string.

        With NoDecode on the field, pydantic-settings no longer JSON-parses the
        env value for us, so this validator owns both forms. A bare value like
        ``https://a.app,https://b.app`` becomes ``["https://a.app", ...]``.
        """
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                import json

                return json.loads(stripped)  # explicit JSON-array form
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return "postgresql" in self.database_url or "postgres" in self.database_url

    @property
    def admin_url(self) -> str:
        """Connection used for DDL + cross-tenant admin work. Falls back to the
        runtime URL when no separate owner connection is configured."""
        return self.admin_database_url or self.database_url

    @staticmethod
    def _mask(url: str) -> str:
        import re

        return re.sub(r"://([^:/@]+):[^@]+@", r"://\1:***@", url)

    @property
    def safe_database_url(self) -> str:
        """Database URL with any credentials masked — safe to log."""
        return self._mask(self.database_url)


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()