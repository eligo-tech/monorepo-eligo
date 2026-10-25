"""The text a candidate receives.

⚠️ **This copy has not been reviewed by a lawyer.** Read it before the first
real send; drafting a compliance notice is not a thing to take from a code
comment. `ELIGO_NOTICE_*` settings fill in the deployment-specific parts.

**Layered, not complete.** The mail carries the decision, the person-specific
origin, and a link; `ELIGO_NOTICE_PRIVACY_URL` carries the full Art. 14(1)-(2)
set. Art. 12(1) permits this. The first version recited all of it and ran to
forty lines of German law arriving unannounced in a stranger's inbox, which is
deleted unread — and an unread notice informs nobody. The origin stays in the
mail because it is the one mandatory item that differs per person
(Art. 14(2)(f)) and a static page cannot state where THIS person's data came
from.

Bilingual in one message rather than two, because we do not know which
language the recipient reads and guessing wrong is the same as not writing.

Plain text, not HTML, on purpose: a legal notice that renders differently in
two clients is two notices, and `candidate_notices.body` can only store one of
them.

**"Nein" means we stop contacting, NOT that we delete.** The copy used to say
"entfernen wir Sie aus unserem Pool" and "ohne Ihre Zustimmung löschen wir Ihre
Daten" while `/ablehnen` only set `status='opted_out'`: nothing in the backend
deletes a candidate, and nothing filters search or matching on that status. A
promise of erasure, with a receipt proving the subject asked and no erasure
behind it, is worse evidence against us than sending no notice at all. The
wording now matches the code (product decision, 2026-10-25) and offers erasure
on request, which Art. 17 obliges us to honour regardless.

Do not reintroduce a deletion promise unless the deletion exists. In a
re-ingesting system that means a suppression list, not a DELETE — see
ARCHITECTURE.md §3, still unbuilt.
"""

from __future__ import annotations

from app.core.config import Settings, settings


def opt_in_subject(controller: str) -> str:
    return f"Ihre Daten bei {controller} — bitte kurz bestätigen / please confirm"


def opt_in_body(
    *,
    candidate_name: str,
    confirm_url: str,
    decline_url: str,
    source_sentence: str,
    cfg: Settings | None = None,
) -> str:
    """The notice, as it will be stored and sent — short, and in both languages.

    Layered on purpose (Art. 12(1) allows it): the mail carries the decision
    and the person-specific part, the linked privacy notice carries the full
    Art. 14(1)-(2) set. The earlier version put all of it in the mail and ran
    to forty lines, which is a wall of German law landing unannounced in a
    stranger's inbox — the likeliest outcome is that it is deleted unread, and
    an unread notice informs nobody.

    `source_sentence` stays in the mail rather than on the page because it is
    the one mandatory item that differs per person (Art. 14(2)(f)); a static
    page cannot state where THIS individual's data came from.
    """
    cfg = cfg or settings
    controller = cfg.notice_controller_name
    contact = cfg.notice_contact_email or cfg.email_reply_to or cfg.email_from or ""
    name = f" {candidate_name}" if candidate_name else ""

    return f"""Guten Tag{name},

wir sind {controller}, eine Personalberatung, und haben Ihre Kontakt- und
Berufsdaten vorliegen. Dürfen wir Sie zu passenden Positionen ansprechen?
Bei "Nein" melden wir uns nicht wieder; löschen können wir Ihre Daten
jederzeit auf Ihren Wunsch ({contact}).
{source_sentence}

We are {controller}, a recruitment consultancy, and hold your contact and
professional details. May we approach you about suitable roles? If you say no,
we will not contact you again; we will delete your data whenever you ask us to
({contact}).

  Ja, gerne / Yes, please:
  {confirm_url}

  Nein, danke / No, thank you:
  {decline_url}

Alle Pflichtangaben nach Art. 14 DSGVO — Verantwortlicher, Zwecke,
Rechtsgrundlage, Speicherdauer und Ihre Rechte — stehen hier /
the full privacy notice is here:
{cfg.notice_privacy_url}

Freundliche Grüße / Kind regards
{controller}
"""
