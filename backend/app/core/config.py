"""Application settings.

Uses ``pydantic-settings`` so configuration is read from environment variables
(prefix ``ELIGO_``) and an optional ``.env`` file. Every default is chosen so
the scaffold starts with ZERO external services (SQLite fallback).
"""

from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # --- CORS ------------------------------------------------------------
    cors_origins: list[str] = Field(
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
        """Allow a comma-separated string in addition to a JSON list."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return value  # let pydantic parse JSON
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return "postgresql" in self.database_url or "postgres" in self.database_url

    @property
    def safe_database_url(self) -> str:
        """Database URL with any credentials masked — safe to log."""
        import re

        return re.sub(r"://([^:/@]+):[^@]+@", r"://\1:***@", self.database_url)


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()