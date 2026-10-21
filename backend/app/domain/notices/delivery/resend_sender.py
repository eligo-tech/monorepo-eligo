"""Resend (https://resend.com) — the one provider wired up today.

Talks to the REST API with `httpx` rather than the `resend` SDK: the call is a
single POST, and the SDK is synchronous, which would block the event loop on
every send.
"""

from __future__ import annotations

import httpx

from app.core.logging import get_logger
from app.domain.notices.delivery.base import EmailRejected, SentMessage

logger = get_logger(__name__)

_ENDPOINT = "https://api.resend.com/emails"


class ResendSender:
    name = "resend"

    def __init__(self, api_key: str, sender: str, timeout: float = 15.0) -> None:
        self._api_key = api_key
        self._sender = sender
        self._timeout = timeout

    async def send(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        reply_to: str | None = None,
    ) -> SentMessage:
        payload: dict[str, object] = {
            "from": self._sender,
            "to": [to],
            "subject": subject,
            "text": text,
        }
        if reply_to:
            payload["reply_to"] = reply_to

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    _ENDPOINT,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        except httpx.HTTPError as exc:
            # A timeout is NOT a failure to send — the message may be on its
            # way. Say so, so the caller records "unknown" rather than
            # inviting a second copy to the same person.
            raise EmailRejected(
                f"Resend unreachable ({type(exc).__name__}): delivery is unknown, "
                "do not retry blindly"
            ) from exc

        if response.status_code >= 400:
            # Resend answers 4xx with {"message": "...", "name": "..."}; the
            # commonest by far is an unverified sending domain.
            detail = response.text[:300]
            logger.warning("Resend refused a message (%s): %s", response.status_code, detail)
            raise EmailRejected(f"Resend {response.status_code}: {detail}")

        body = response.json() if response.content else {}
        return SentMessage(provider=self.name, message_id=body.get("id"))
