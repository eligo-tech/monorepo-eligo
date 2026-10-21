"""The seam an email provider plugs into.

Same shape as `CVExtractor` and `AtsConnector`: a protocol plus a factory, so
no vendor is named outside `delivery/`. One rule is inverted from the
extractor factory, deliberately — see `factory.get_email_sender`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class EmailNotConfigured(RuntimeError):
    """No provider is configured, so nothing can be sent.

    Raised rather than swallowed. The extractor factory degrades to a
    heuristic when OpenAI is missing because a worse answer is still an
    answer; there is no such thing as a worse email. A sender that silently
    succeeded would mark a candidate as informed when nothing left the
    building — a false entry in exactly the record the Art. 14 obligation
    rests on.
    """


class EmailRejected(RuntimeError):
    """The provider refused the message. Carries what it said."""


@dataclass(frozen=True)
class SentMessage:
    """What the provider gave back. `message_id` is how a bounce is traced."""

    provider: str
    message_id: str | None


@runtime_checkable
class EmailSender(Protocol):
    """Sends one message to one recipient. No batching, no templating.

    Templating lives in `templates.py` and the record of what was sent lives
    in `candidate_notices.body` — a provider that rendered the text would put
    the only copy of a legal notice on somebody else's server.
    """

    name: str

    async def send(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        reply_to: str | None = None,
    ) -> SentMessage: ...
