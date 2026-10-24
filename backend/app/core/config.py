"""Application settings.

Uses ``pydantic-settings`` so configuration is read from environment variables
(prefix ``ELIGO_``) and an optional ``.env`` file. Every default is chosen so
the scaffold starts with ZERO external services (SQLite fallback).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from pydantic import AliasChoices, Field, field_validator, model_validator
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
    app_name: str = "Eligo Labs"
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

    # --- Interviewer agent (gated feature) -------------------------------
    # Three gates, all of which must open (see `domain/features`):
    #   1. this switch — the operator's kill switch, OFF unless set;
    #   2. the allowlist — when non-empty, only these workspaces (comma-
    #      separated tenant UUIDs) may opt in; empty means any workspace may;
    #   3. a workspace admin's recorded consent to the current terms.
    # And per interview, the candidate's own recorded consent.
    interviewer_enabled: bool = False
    interviewer_allowed_tenants: str = ""

    # --- Information hub (public-source ingestion) -----------------------
    # Identify the crawler honestly: Nominatim and most public APIs require a
    # real User-Agent with a contact route, and it is what makes a rate-limit
    # complaint a conversation rather than a block.
    hub_user_agent: str = "eligolabs-hub/0.1 (+https://eligolabs.com)"
    hub_http_timeout: float = 20.0

    # Bundesagentur für Arbeit Jobsuche API. The client id is the agency's own
    # public one (community-documented at jobsuche.api.bund.dev); no signup.
    hub_ba_base_url: str = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
    hub_ba_api_key: str = "jobboerse-jobsuche"

    # --- Auth (Clerk) ----------------------------------------------------
    # When false, requests run as the default tenant (no login) — the scaffold
    # default so tests/demo work with no auth provider. Set true in production.
    auth_enabled: bool = False
    #: Escape hatch for the startup guard below: a real database served with
    #: authentication off. Only ever right for a local Postgres you own.
    allow_insecure_no_auth: bool = False

    #: May an organization the record has never seen mint itself a workspace?
    #:
    #: It used to, unconditionally: ``tenants.get_or_create`` ran on the request
    #: path, so presenting a token with any ``org_id`` created a tenant. Nothing
    #: leaked — RLS kept the new workspace empty and separate — but nobody
    #: *admitted* anyone either, and "they saw nothing" was true only because
    #: there was nothing there yet. Sign-up plus "create organization" was a
    #: self-service route into the production database.
    #:
    #: Closed by default. Provisioning is an operator action:
    #: ``python -m scripts.provision_tenant org_xxx "Name"``. Every organization
    #: already using the product has a row, so closing this refuses only the
    #: ones that were never admitted. Set true to re-open it for an onboarding
    #: session; each mint is then logged with the org id.
    auto_provision_tenants: bool = False

    #: Fernet key for secrets the record must be able to replay — today only a
    #: tenant's ATS password. Unset means credentials cannot be stored at all,
    #: which is the safe default (see `app/core/secrets.py`).
    secret_key: str | None = None
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
    #: Origins a session token may name as its authorized party (`azp`).
    #: ADR 0002 §7.7. Empty — the default — falls back to `cors_origins`,
    #: because the frontends we serve ARE the parties allowed to mint tokens
    #: for this API, and keeping one list avoids the failure where somebody
    #: adds an origin to CORS and locks it out here.
    clerk_authorized_parties: Annotated[list[str], NoDecode] = Field(
        default_factory=list
    )

    # --- Machine credentials ---------------------------------------------
    # Cron has no Clerk user. A session JWT is the wrong credential for a
    # scheduled backfill — short-lived, tied to a person, revoked when they
    # leave — so non-interactive ingest callers present this shared secret
    # instead. UNSET (the default) disables the machine path entirely: only a
    # Clerk-authenticated human can trigger ingestion. Never logged.
    #
    # Generate one with:  python -c "import secrets; print(secrets.token_urlsafe(32))"
    ingest_token: str | None = None
    # Tenant a machine-authenticated ingest writes into. Falls back to the
    # default tenant; set it explicitly once more than one tenant exists.
    ingest_tenant_id: UUID | None = None

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

    # --- Outbound email (candidate notices) ------------------------------
    #: Which provider carries a notice. Empty means the deployment cannot
    #: send, and every send attempt answers 503 rather than pretending — see
    #: `domain/notices/delivery/factory.py` on why this one does not fall back.
    email_provider: str = ""
    resend_api_key: str | None = None
    #: The From address. Must be on a domain verified in the provider, or the
    #: provider refuses every message (the commonest setup mistake by far).
    email_from: str | None = None
    #: Where a candidate's reply goes — a human mailbox, not the sender.
    email_reply_to: str | None = None
    #: Origin the opt-in link points at. The link travels in an email, so it
    #: cannot be relative and must not be guessed from the inbound request.
    #:
    #: It must be the host that serves **`/api/v1`**, because that is where
    #: the two opt-in routes live — not the cockpit's origin. Pointing it at
    #: the Vercel site produces a link that 404s for every candidate, which
    #: is exactly what the first default here did.
    notice_link_base_url: str = "https://monorepo-eligo-production.up.railway.app"
    #: Name of the controller as it appears in the notice. Art. 13/14 require
    #: the candidate to be told who holds their data; "Eligo Labs" is the
    #: platform, not necessarily the controller.
    notice_controller_name: str = "Eligo Labs"
    #: Where a candidate exercises their rights. Falls back to reply-to.
    notice_contact_email: str | None = None

    @field_validator("ingest_token")
    @classmethod
    def _reject_weak_ingest_token(cls, value: str | None) -> str | None:
        """A short shared secret is worse than none — it looks like protection.

        Refuse to start rather than expose a write endpoint (which also makes
        outbound calls to a public API) behind a guessable string.
        """
        if value is not None and len(value.strip()) < 32:
            raise ValueError(
                "ELIGO_INGEST_TOKEN must be at least 32 characters; generate one "
                'with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        return value.strip() if value else None

    @model_validator(mode="after")
    def _opt_in_links_must_point_at_this_api(self) -> "Settings":
        """Refuse a notice link base that is one of our CORS origins.

        A CORS origin is by definition a DIFFERENT origin that calls this
        API; the API's own public origin can never legitimately appear in
        that list. So an overlap means somebody set the link base to the
        cockpit — and the two opt-in routes are backend routes, so every
        candidate's link would 404.

        This is the check that would have caught the first default here
        (`https://eligo-tech.vercel.app`, a domain that does not even
        resolve). A unit test could not: it would have to read the same
        setting it was checking. Failing at startup is proportionate because
        the symptom otherwise appears in somebody else's inbox, days later,
        with no error anywhere in our logs.
        """
        base = (self.notice_link_base_url or "").rstrip("/")
        if base and base in {o.rstrip("/") for o in self.cors_origins}:
            raise ValueError(
                f"ELIGO_NOTICE_LINK_BASE_URL ({base}) is one of "
                "ELIGO_CORS_ORIGINS, so it is the cockpit's origin, not this "
                "API's. The opt-in links are backend routes "
                "(/api/v1/notices/...) and would 404 for every candidate. "
                "Set it to the host that serves /api/v1."
            )
        return self

    @field_validator("cors_origins", "clerk_authorized_parties", mode="before")
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