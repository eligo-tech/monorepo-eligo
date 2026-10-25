# Recruiter-Cockpit – Prozess & MVP-Scope

Für die Umsetzung durch den AI Engineer. Ziel: den End-to-End-Prozess der Personalvermittlung abbilden – von der Marktopportunity bis zur Rechnung. Bewusst so einfach wie möglich gehalten (Basisfunktionalität zuerst).

---

## 1. Der Prozess in 4 Phasen

### Phase 1 – Akquise (Business Development)
1. **Opportunity prüfen** – offene Stelle am Markt, die wir besetzen wollen.
2. **Unternehmen anlegen** in der Datenbank (zur Opportunity).
3. **Manager hinzufügen** – die verantwortlichen Ansprechpartner beim Unternehmen.
4. **Kunde gewinnen** – kontaktieren, überzeugen, **Rahmenvertrag** schließen.

### Phase 2 – Mandat & Briefing
5. **Briefing** mit einstellendem Manager und/oder HR (HR je nach Firmengröße unterschiedlich involviert) → daraus die **Job-Parameter / das Suchprofil** festlegen.

### Phase 3 – Kandidatensuche
6. **Ansprache** – Kandidaten über eigene Datenbank + Plattformen kontaktieren.
7. **Qualifizierung** – prüfen, ob passend (CV, Erstgespräch/Video).
8. **Vorstellung** beim Kunden.

### Phase 4 – Prozess (Laufende Prozesse / Cockpit)
9. Ab der Vorstellung läuft die **Pipeline** (siehe Abschnitt 3).
10. Bei unterschriebenem **Vertrag** → **Rechnung** an den Kunden.

---

## 2. Kern-Entitäten (Datenmodell)

Minimal, mit den wichtigsten Feldern und Beziehungen:

| Entität | Wichtigste Felder | Beziehung |
|---|---|---|
| **Company** (Unternehmen) | Name, HRB, USt-ID, Kontakt (Tel/Mail), Standorte, Tochterfirmen | – |
| **Manager** (Ansprechpartner) | Name, Rolle, Kontakt, Anrede (Du/Sie) | → Company |
| **Contract** (Rahmenvertrag) | Konditionen: Honorar, Basis, Zahlungsziel, Garantie; Status | → Company |
| **Job / Mandat** | Titel, Stellenanzeige, Suchprofil (Muss / Nice-to-have / harte Fakten), Briefing, Status | → Company, → Manager |
| **Candidate** (Kandidat) | Stammdaten, Skills, Standort, Verfügbarkeit, Gehalt, Quelle, Score | – |
| **Process** (Prozess) | aktuelle Stage, Termine, Feedback, Fee-Wert | → Candidate, → Job |
| **Invoice** (Rechnung) | Betrag, Status (erstellt/gesendet) | → Process, → Contract |

Kern-Datenfluss: **Company → Manager → Contract → Job/Briefing → Candidate → Process → Invoice.**

---

## 3. Status-Pipeline „Laufende Prozesse" (einfachste Form)

Eine Prozess-Instanz = **1 Kandidat auf 1 Job**. Die Stages sind eine Checkliste, die der Reihe nach abgehakt wird (Termin vor Vorbereitung):

1. **Vorgestellt** *(Datum)*
2. **Feedback Kunde** *(nur Kunde – Kandidat wurde gerade erst vorgestellt)*
3. **Interviewtermin** *(Datum + Uhrzeit)*
4. **Interview-Vorbereitung**
5. **Feedback** *(Kunde + Kandidat)*
6. **Finaltermin** *(Datum + Uhrzeit)*
7. **Final-Vorbereitung**
8. **Offer & Zusage** *(Offer vom Kunden + mündliche Zusage des Kandidaten)*
9. **Vertrag** *(von beiden Parteien unterschrieben)* → Deal gewonnen → **Rechnung**

Hinweis: Deal zählt erst mit unterschriebenem Vertrag. Mündliche Zusage = noch kein Deal.

Mehrere Kandidaten auf denselben Job werden unter dem Job gruppiert dargestellt. Der Job erscheint in „Laufende Prozesse", sobald der erste Kandidat vorgestellt ist.

---

## 4. MVP – was zuerst gebaut wird

Halte es einfach: **CRUD + Status-Wechsel.**

- Company, Manager, Contract, Job, Candidate **anlegen / bearbeiten**.
- Job an Company + Manager hängen; Candidate an Job hängen.
- **Prozess-Instanz** mit den 9 Stages; Stages abhakbar, Datum/Uhrzeit erfassbar, Feedback als Textfeld.
- Bei Stage „Vertrag" → **Rechnung** aus den Company-Konditionen erzeugen (zunächst als Anzeige/PDF).

### Bewusst NICHT im MVP (später)
- KI-gestützte Ansprache & Stil-Lernen
- Multi-Portal-Suche (LinkedIn, Xing, Arbeitsagentur, Stepstone …) & Daten-Anreicherung
- Automatische Qualifizierung (CV-Check, Transkript-Abgleich)
- Externe Recruiter (eigener, eingeschränkter Zugang) & White-Label
- DATEV-Schnittstelle / automatischer Rechnungsversand
- Scoring/Analytics, Umsatz-Dashboard

---

## 5. Zuordnung zu den Cockpit-Bereichen (Orientierung)

- **Business Development** → Phase 1 (Opportunity, Company, Manager, Rahmenvertrag).
- **Mandat & Kandidatensuche (Job-Workspace)** → Phase 2 + 3 (Stammdaten, Briefing/Suchprofil, Ansprache, Qualifizierung, Vorstellung).
- **Kandidatenwelt** → Kandidaten-zentrierte Sicht (Suche/Filter, passende Jobs).
- **Kommandozentrale** → Übersicht (Umsatz, Laufende Prozesse, nächste Aktionen, Scoring).

---

## 6. Aktivitäts-Tracking (KPIs pro Recruiter)

Grundprinzip: **Jede Kennzahl entsteht aus einem Ereignis, das im System ohnehin erfasst wird** – keine manuelle Zählung. Jedes Ereignis speichert `recruiter_id`, `timestamp` und den Bezug (Company, Manager, Job, Candidate). Ausgewertet wird pro Recruiter und Zeitraum (Woche / Monat / Quartal) gegen ein hinterlegtes Ziel.

### Kern-KPIs (Anzeige als Instrument: Ist vs. Ziel)

| KPI | Gemessen durch (Ereignis) | Quelle |
|---|---|---|
| **Business Calls** | Notiz vom Typ „Call" bei einem Manager angelegt | CRM / Manager-Notizen |
| **Vorgestellte Kandidaten** | Prozess-Stage „Vorgestellt" gesetzt | Prozess |
| **Rahmenverträge** | Contract-Status auf „geschlossen" | Verträge |
| **Netzwerk-Wachstum** | Neue LinkedIn-Verbindungen im Zeitraum | LinkedIn-Anbindung |

### Ergänzende KPIs (Vorschlag, ebenfalls ereignisbasiert)

| KPI | Gemessen durch |
|---|---|
| Kandidaten-Ansprachen + Response-Rate | Ansprache versendet / Antwort erhalten |
| Erstgespräche Kandidaten | Video-Interview in Qualifizierung stattgefunden |
| Kundeninterviews | Stage „Interviewtermin" gesetzt |
| Neue Briefings | Briefing angelegt |
| Conversion Vorstellung → Interview | Verhältnis der beiden Stages |
| Time-to-Submit | Zeit von Briefing bis erster Vorstellung |
| Kontakte ohne Follow-up | Manager ohne Notiz seit > 30 Tagen |
| Placements / Umsatz pro Placement | Stage „Vertrag" + Rechnungsbetrag |

### Stage-Tracking (Prozess-Funnel)

Ziel: erkennen, **wo der Prozess hakt und wer warum rausfliegt**. Gemessen wird jeder Übergang zwischen zwei Stages:

| Übergang | Leitfrage | Gemessen |
|---|---|---|
| CV vorgestellt → 1. Interview | Haben wir die Anforderungen verstanden? | Quote + Ø Dauer |
| 1. Interview → 2. Interview | Passt der Kandidat ins Team? | Quote + Ø Dauer |
| 2. Interview → Finale | Überzeugt er im Vergleich? | Quote + Ø Dauer |
| Finale → Angebot | Entscheidet sich der Kunde? | Quote + Ø Dauer |
| Angebot → Annahme | Sagt der Kandidat zu? | Quote + Ø Dauer |

- **Quote** = Anzahl Prozesse, die die nächste Stage erreichen / Anzahl in der aktuellen Stage (im Zeitraum).
- **Dauer** = Differenz der Zeitstempel beider Stages, gemittelt. Summe ergibt die Time-to-Hire.
- **Absagegrund**: Wird ein Prozess beendet, ist ein Grund Pflicht (Auswahlliste, z. B. fachlich nicht passend, Gehalt, Kultur/Fit, anderer Kandidat, Gegenangebot, Kandidat zurückgezogen) plus Freitext aus dem Feedback im Mandat. Gespeichert wird, **in welcher Stage** und **von wem** (Kunde oder Kandidat) abgesagt wurde.
- Jeder Übergang hat eine Zielquote. Der Übergang mit der größten Abweichung wird als „Hier hakt es" markiert.
- Auswertbar nach Recruiter, Kunde, Job und Zeitraum.

Hinweis: Die Prozess-Pipeline braucht dafür eine optionale Stage **„2. Interview"** zwischen Interviewtermin und Finaltermin (kann übersprungen werden, wenn der Kunde direkt ins Finale geht).

### Datenmodell-Ergänzung
- **ActivityEvent**: `type`, `recruiter_id`, `timestamp`, `ref_type`, `ref_id`
- **StageChange**: `process_id`, `from_stage`, `to_stage`, `timestamp`
- **Dropout**: `process_id`, `stage`, `by` (Kunde/Kandidat), `reason`, `note`
- **Target**: `recruiter_id`, `kpi`, `period`, `value`
- **Recruiter / User** (inkl. Rolle: intern, 360°-Consultant, externer Recruiter)

Für den MVP reicht: Events beim Speichern von Notiz, Stage-Wechsel und Vertragsstatus schreiben; Ziele manuell pflegen. LinkedIn-Wachstum kommt mit der späteren Anbindung.
