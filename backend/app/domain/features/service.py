"""Gated features: a feature is on for a workspace only when every gate opens.

The gates, in order:

1. **Operator switch** (`settings.<feature>_enabled`) — off by default; the
   kill switch for every workspace at once.
2. **Allowlist** (`settings.<feature>_allowed_tenants`) — when set, only the
   listed workspaces may opt in. This is how a feature reaches design
   partners first.
3. **Workspace consent** — a workspace admin accepted the CURRENT terms. A
   new terms version needs a new acceptance; revoking closes the gate at once.

`ensure_enabled` is called by the SERVICE that owns the feature, not by a
router, so no path into the feature — HTTP, script, scheduled job — skips it.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.common.enums import ReceiptAction
from app.domain.features.models import TenantFeatureConsent
from app.domain.features.schemas import FeatureStatus
from app.domain.verification.service import append_receipt


class FeatureDisabled(Exception):
    """The feature is not enabled for this workspace; the message says why."""


class UnknownFeature(Exception):
    pass


class TermsMismatch(Exception):
    """The admin accepted a terms version that is not the current one."""


@dataclass(frozen=True)
class FeatureDef:
    key: str
    label: str
    terms_version: str
    terms: str
    switch: Callable[[], bool]
    allowlist: Callable[[], str]


INTERVIEWER_TERMS = """\
KI-Interview-Assistent — Bedingungen für Ihren Workspace

Mit der Aktivierung bestätigen Sie als Administrator:
1. Kandidaten werden VOR jedem Interview darüber informiert, dass sie mit
   einem KI-System sprechen, und stimmen ausdrücklich zu. Ohne diese
   Zustimmung startet kein Interview.
2. Der Assistent schlägt nur vor. Jede Angabe ist mit der Antwort belegt,
   aus der sie stammt; unsichere Angaben und alles, was einen vorhandenen
   Wert überschreiben würde, prüft ein Recruiter.
3. Es gibt keine automatische Absage. Entscheidungen über Kandidaten trifft
   ein Mensch (Art. 22 DSGVO).
4. Kandidaten können ihre Zustimmung jederzeit widerrufen; das Transkript
   wird dann gelöscht.
5. Die Daten bleiben in Ihrem Workspace und werden nicht für andere Zwecke
   verwendet.
6. Sie können den Assistenten jederzeit wieder deaktivieren.

Hinweis: Ein KI-System zur Bewerberauswahl gilt nach der EU-KI-Verordnung
als Hochrisiko-System (Anhang III). Als Betreiber tragen Sie Pflichten zur
menschlichen Aufsicht und Information der Kandidaten.
"""

FEATURES: dict[str, FeatureDef] = {
    "interviewer": FeatureDef(
        key="interviewer",
        label="KI-Interview-Assistent",
        terms_version="2026-10-17",
        terms=INTERVIEWER_TERMS,
        switch=lambda: settings.interviewer_enabled,
        allowlist=lambda: settings.interviewer_allowed_tenants,
    ),
}


def _definition(key: str) -> FeatureDef:
    try:
        return FEATURES[key]
    except KeyError as exc:
        raise UnknownFeature(key) from exc


def _allowed(defn: FeatureDef, tenant_id: uuid.UUID) -> bool:
    raw = defn.allowlist().strip()
    if not raw:
        return True
    return str(tenant_id) in {part.strip() for part in raw.split(",") if part.strip()}


async def _active_consent(
    session: AsyncSession, *, tenant_id: uuid.UUID, key: str
) -> TenantFeatureConsent | None:
    return (
        await session.execute(
            select(TenantFeatureConsent)
            .where(
                TenantFeatureConsent.tenant_id == tenant_id,
                TenantFeatureConsent.feature == key,
                TenantFeatureConsent.revoked_at.is_(None),
            )
            .order_by(TenantFeatureConsent.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def status(
    session: AsyncSession, *, tenant_id: uuid.UUID, key: str
) -> FeatureStatus:
    defn = _definition(key)
    base = {
        "key": defn.key,
        "label": defn.label,
        "terms_version": defn.terms_version,
        "terms": defn.terms,
    }
    if not defn.switch():
        return FeatureStatus(
            **base, available=False, enabled=False,
            reason="Diese Funktion ist derzeit nicht freigeschaltet.",
        )
    if not _allowed(defn, tenant_id):
        return FeatureStatus(
            **base, available=False, enabled=False,
            reason="Diese Funktion ist für Ihren Workspace noch nicht freigegeben.",
        )

    consent = await _active_consent(session, tenant_id=tenant_id, key=key)
    if consent is None:
        return FeatureStatus(
            **base, available=True, enabled=False,
            reason="Ein Administrator muss den Bedingungen zustimmen.",
        )
    if consent.terms_version != defn.terms_version:
        return FeatureStatus(
            **base, available=True, enabled=False,
            reason="Die Bedingungen wurden geändert — bitte erneut zustimmen.",
            accepted_by=consent.accepted_by, accepted_at=consent.created_at,
        )
    return FeatureStatus(
        **base, available=True, enabled=True,
        accepted_by=consent.accepted_by, accepted_at=consent.created_at,
    )


async def list_status(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[FeatureStatus]:
    return [await status(session, tenant_id=tenant_id, key=k) for k in FEATURES]


async def ensure_enabled(session: AsyncSession, *, tenant_id: uuid.UUID, key: str) -> None:
    current = await status(session, tenant_id=tenant_id, key=key)
    if not current.enabled:
        raise FeatureDisabled(current.reason or "feature disabled")


async def accept(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    key: str,
    terms_version: str,
    actor_name: str,
    actor_user_id: str | None = None,
) -> FeatureStatus:
    """Record an admin's consent. Idempotent for the same terms version."""
    defn = _definition(key)
    current = await status(session, tenant_id=tenant_id, key=key)
    if not current.available:
        raise FeatureDisabled(current.reason or "feature unavailable")
    if terms_version != defn.terms_version:
        raise TermsMismatch(
            f"terms version {terms_version!r} is not the current {defn.terms_version!r}"
        )
    if current.enabled:
        return current

    # An acceptance of outdated terms is superseded, not left dangling.
    stale = await _active_consent(session, tenant_id=tenant_id, key=key)
    now = dt.datetime.now(dt.UTC)
    if stale is not None:
        stale.revoked_at = now
        stale.revoked_by = f"superseded by {actor_name}"

    row = TenantFeatureConsent(
        tenant_id=tenant_id,
        feature=key,
        terms_version=defn.terms_version,
        accepted_by=actor_name,
        accepted_by_user_id=actor_user_id,
    )
    session.add(row)
    await session.flush()
    await append_receipt(
        session,
        tenant_id=tenant_id,
        agent="workspace_admin",
        action=ReceiptAction.ASSERT,
        subject_type="feature",
        subject_id=key,
        verified=True,
        summary=f"feature {key} enabled — terms {defn.terms_version} accepted",
        payload={"actor": actor_name, "terms_version": defn.terms_version},
    )
    await session.commit()
    return await status(session, tenant_id=tenant_id, key=key)


async def revoke(
    session: AsyncSession, *, tenant_id: uuid.UUID, key: str, actor_name: str
) -> FeatureStatus:
    """Switch the feature off for the workspace. Effective immediately."""
    _definition(key)
    consent = await _active_consent(session, tenant_id=tenant_id, key=key)
    if consent is not None:
        consent.revoked_at = dt.datetime.now(dt.UTC)
        consent.revoked_by = actor_name
        await append_receipt(
            session,
            tenant_id=tenant_id,
            agent="workspace_admin",
            action=ReceiptAction.ASSERT,
            subject_type="feature",
            subject_id=key,
            verified=True,
            summary=f"feature {key} disabled",
            payload={"actor": actor_name},
        )
        await session.commit()
    return await status(session, tenant_id=tenant_id, key=key)
