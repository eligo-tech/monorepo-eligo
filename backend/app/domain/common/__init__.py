"""Shared domain primitives: ORM mixins and cross-domain enums."""

from app.domain.common.enums import (
    ApplicationStatus,
    ConfidenceSource,
    MatchStrength,
    PipelineStage,
    ReceiptAction,
    WorkPermitStatus,
)
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin

__all__ = [
    "ApplicationStatus",
    "ConfidenceSource",
    "MatchStrength",
    "PipelineStage",
    "ReceiptAction",
    "WorkPermitStatus",
    "IDMixin",
    "TenantMixin",
    "TimestampMixin",
]