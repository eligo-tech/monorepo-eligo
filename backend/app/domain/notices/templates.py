"""The text a candidate receives.

⚠️ **This copy has not been reviewed by a lawyer.** It is written to carry
what GDPR Art. 14(1)–(2) requires a controller to tell someone whose data was
obtained elsewhere — identity of the controller, the categories of data, where
it came from, the purpose and legal basis, how long it is kept, and the rights
to access, rectification, erasure, objection and complaint — but drafting a
compliance notice is not a thing to take from a code comment. Read it before
the first real send; `ELIGO_NOTICE_*` settings fill in the parts that are
deployment-specific rather than editorial.

Plain text, not HTML, on purpose: a legal notice that renders differently in
two clients is two notices, and `candidate_notices.body` can only store one of
them.
"""

from __future__ import annotations

from app.core.config import Settings, settings


def opt_in_subject(controller: str) -> str:
    return f"Ihre Daten bei {controller} — bitte einmal bestätigen"


def opt_in_body(
    *,
    candidate_name: str,
    confirm_url: str,
    decline_url: str,
    source_sentence: str,
    cfg: Settings | None = None,
) -> str:
    """The notice, as it will be stored and sent.

    `source_sentence` is passed in rather than composed here: Art. 14(2)(f)
    asks for the *actual* origin, and a generic "aus öffentlichen Quellen"
    under every notice would be the kind of claim this system exists not to
    make.
    """
    cfg = cfg or settings
    controller = cfg.notice_controller_name
    contact = cfg.notice_contact_email or cfg.email_reply_to or cfg.email_from or ""
    greeting = f"Guten Tag {candidate_name}," if candidate_name else "Guten Tag,"

    return f"""{greeting}

wir sind {controller}, eine Personalberatung. Ihre Kontakt- und
Berufsdaten liegen bei uns vor, und wir möchten Sie darüber informieren —
dazu sind wir nach Art. 14 DSGVO verpflichtet, weil wir diese Daten nicht
direkt bei Ihnen erhoben haben.

Woher Ihre Daten stammen
{source_sentence}

Welche Daten wir verarbeiten
Name, Kontaktdaten und berufliche Angaben (beruflicher Werdegang,
Qualifikationen, Kenntnisse) sowie Unterlagen, die uns dazu vorliegen.

Zweck und Rechtsgrundlage
Wir nutzen diese Daten, um Sie auf passende Positionen anzusprechen.
Rechtsgrundlage ist unser berechtigtes Interesse an der Vermittlung
(Art. 6 Abs. 1 lit. f DSGVO) — und, sobald Sie unten zustimmen, Ihre
Einwilligung (Art. 6 Abs. 1 lit. a DSGVO).

Ihre Entscheidung
Bitte sagen Sie uns, ob wir Sie weiter in unserem Bewerberpool führen dürfen:

  Ja, bitte aufnehmen:
  {confirm_url}

  Nein, Daten löschen:
  {decline_url}

Wenn Sie "Nein" wählen, entfernen wir Sie aus unserem Pool und melden uns
nicht wieder. Sie müssen dafür nichts weiter tun und es entstehen Ihnen
keine Nachteile.

Ihre Rechte
Sie haben jederzeit das Recht auf Auskunft, Berichtigung, Löschung und
Einschränkung der Verarbeitung, auf Datenübertragbarkeit sowie auf
Widerspruch gegen die Verarbeitung. Eine erteilte Einwilligung können Sie
jederzeit mit Wirkung für die Zukunft widerrufen. Außerdem können Sie sich
bei einer Datenschutz-Aufsichtsbehörde beschweren.

Wie lange wir speichern
Ohne Ihre Zustimmung löschen wir Ihre Daten; mit Ihrer Zustimmung speichern
wir sie, bis Sie widersprechen oder Ihre Einwilligung widerrufen.

Bei Fragen erreichen Sie uns unter {contact}.

Freundliche Grüße
{controller}
"""
