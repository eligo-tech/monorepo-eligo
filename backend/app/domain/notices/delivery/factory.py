"""Provider selection. Adding one is a module plus a line in `_BUILDERS`.

**This factory does not fall back, and that is the point.** `get_cv_extractor`
degrades to a heuristic parser when OpenAI is unavailable, because a rougher
extraction is still an extraction and the feature must work offline. Email has
no such degraded mode: the only alternatives to sending are not sending and
pretending. A sender that pretends writes `status='sent'` against a candidate
who was never told anything, which is a false entry in the very record the
Art. 14 obligation rests on. So an unconfigured deployment raises
`EmailNotConfigured`, the API answers 503, and no notice changes state.
"""

from __future__ import annotations

from app.core.config import Settings, settings
from app.core.logging import get_logger
from app.domain.notices.delivery.base import EmailNotConfigured, EmailSender

logger = get_logger(__name__)


def _build_resend(cfg: Settings) -> EmailSender | None:
    if not cfg.resend_api_key:
        logger.warning("email_provider=resend but ELIGO_RESEND_API_KEY is unset")
        return None
    if not cfg.email_from:
        logger.warning("email_provider=resend but ELIGO_EMAIL_FROM is unset")
        return None
    try:
        from app.domain.notices.delivery.resend_sender import ResendSender

        return ResendSender(api_key=cfg.resend_api_key, sender=cfg.email_from)
    except Exception as exc:  # pragma: no cover — missing httpx, bad config
        logger.warning("Resend sender unavailable (%s)", exc)
        return None


_BUILDERS = {
    "resend": _build_resend,
}


def email_is_configured(cfg: Settings | None = None) -> bool:
    """Can this deployment send at all? Drives the UI, so a recruiter sees
    'not configured' instead of a button that 503s."""
    cfg = cfg or settings
    builder = _BUILDERS.get((cfg.email_provider or "").lower())
    return builder is not None and builder(cfg) is not None


def get_email_sender(cfg: Settings | None = None) -> EmailSender:
    cfg = cfg or settings
    builder = _BUILDERS.get((cfg.email_provider or "").lower())
    sender = builder(cfg) if builder is not None else None
    if sender is None:
        raise EmailNotConfigured(
            "no email provider is configured. Set ELIGO_EMAIL_PROVIDER=resend, "
            "ELIGO_RESEND_API_KEY and ELIGO_EMAIL_FROM (a sender on a domain "
            "verified in Resend)."
        )
    return sender
