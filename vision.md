# eligo-tech — Vision & Architektur

> KI-native Recruiting-Plattform. Vorbild/Referenzmarkt: [aifind.io](https://www.aifind.io/de/blog/).
> Dies ist die kondensierte Fassung der Architektur- & Begründungslogik.

## 1. These

Recruiting-Tools **speichern** Daten – sie **verstehen** sie nicht. Ein ATS ist eine
Datenbank mit einem Formular: es weiß, dass ein Kandidat existiert, aber nicht, ob er
passt, ob seine Kontaktdaten noch stimmen oder für welche offene Stelle er vorgestellt
werden sollte. eligo-tech dreht das um: Das **System of Record bleibt schlicht und
zuverlässig**, darüber liegt eine Schicht aus Agenten, die kontinuierlich **lesen,
anreichern, matchen und erklären**.

Der Hebel ist nicht „wir haben KI". Der Hebel ist **verifizierte KI**: andere
protokollieren, *was* der Agent gesagt hat – wir prüfen, *ob es stimmt*, bevor es einem
Recruiter oder Kunden angezeigt wird. In einem Markt, in dem Recruiting-KI rechtlich als
**Hochrisiko** gilt, ist das der Burggraben, kein Nice-to-have.

## 2. Produktoberfläche (5 Fähigkeiten)

1. **Einheitlicher Kandidatendatensatz** — ein kanonisches Profil pro Person, aus allen
   Quellen zusammengeführt und dedupliziert.
2. **Dokumenten-Intelligenz** — CVs/Referenzen/Nachweise → strukturierte Daten, plus
   Checkliste „liegt vor / fehlt".
3. **Belegte Kandidatenanalyse** — Zusammenfassung (Seniorität, Skills, Stärken, Lücken,
   Warnsignale), jede Aussage verweist auf ein Quelldokument.
4. **Bidirektionales Matching** — Kandidat → Stellen und Stelle → Kandidaten, je mit
   „warum dieser Match" und den geprüften Kriterien.
5. **Anreicherung & Marktsignale** — Lücken füllen; öffentlichen Stellenmarkt auswerten
   für frische Daten und BD-Signale.

Alles landet im **Candidate-360-Dashboard** — keine Blackbox.

## 3. Sechs-Schichten-Architektur

Die entscheidende Wahl ist die **Verifikationsschicht zwischen Agenten und Datensatz**.

| # | Schicht | Aufgabe |
|---|---------|---------|
| ① | Quellen & Ingestion | ATS-Export, Postfach/Kalender, Jobbörsen, Uploads → parsen, normalisieren, **Entitätsauflösung** (3× „J. Schmidt" → 1 Person). |
| ② | Kanonische Daten | **Postgres = einzige Quelle der Wahrheit**; pgvector für Embeddings; Objektspeicher für Rohdokumente; Event-Log. |
| ③ | Agenten | 5 enge Worker mit I/O-Vertrag — **schreiben nie direkt**, sie *schlagen vor*. |
| ④ | Intelligenz | Matching/Analyse. **Deterministischer Code entscheidet harte Kriterien; das LLM entscheidet nur die unscharfe Passung** innerhalb der bereits gefilterten Menge. |
| ⑤ | Verifikation & Governance | Postcondition-Check gegen die echte Quelle · Provenienz + Konfidenz je Feld · Human-in-the-Loop für folgenreiche Aktionen · **signierte, append-only Quittungen**. |
| ⑥ | Anwendung | Candidate-360-Dashboard, private API, MCP-Server (Recruiter fragt aus Claude/ChatGPT). |

## 4. Candidate-360-Dashboard

Ein Kandidat, vier Panels: **Status** (Pipeline-Position + Aktualitätsindikator) ·
**Gesammelte Dokumente** (Checkliste + Extraktionskonfidenz; niedrig → Human-Review) ·
**Analyse** (belegt, jede Aussage verlinkt aufs Quelldokument) · **Passende Jobs**
(priorisiert, mit „Warum" und „Achtung"). Mentales Modell: *nie veraltet* (Agenten halten
es aktuell), *nie stillschweigend falsch* (jede Aussage geprüft und belegt).

## 5. Fünf Agenten

Jeder ist ein begrenzter Worker; keiner schreibt ohne Verifikation.

- **Dokumentextraktion** — Dokument → strukturierte Felder (Pydantic-Schema, Konfidenz je
  Feld). Niedrige Konfidenz → Human-Review.
- **Anreicherung** — füllt Lücken aus Dritt-/öffentlichen Quellen; Postcondition
  (z. B. E-Mail-Zustellbarkeit) vor dem Schreiben; löst **DSGVO-Art.-14-Benachrichtigung** aus.
- **Marktkarte (Web/Wettbewerb)** — nur **öffentliche** Job-/Unternehmensdaten (robots.txt,
  ToS, Drosselung); speist Job-Graph + BD-Signale. Rechtlich riskanteste Komponente → konservativ.
- **Matching** — Kandidat/Rolle → priorisierte Shortlist mit Begründung (§6).
- **Outreach & Präsentation** — Entwürfe + kundenfertige Präsentationen. **Nichts wird
  ohne menschliche Freigabe versendet.**

## 6. Matching-Engine

1. **Repräsentation** — strukturierte Merkmale + Text-Embedding (Two-Tower / Bi-Encoder).
2. **Retrieval** — Embedding + ANN-Suche in pgvector („Python-Engineer" ≈ „Backend-Dev").
3. **Harte Filter (deterministisch)** — Arbeitserlaubnis, Standortradius, Gehaltsobergrenze,
   Zertifizierung. Verletzung = **kein Match**, nicht „schwach".
4. **Re-Ranking & Erklärung (LLM)** — rankt nur die Überlebenden, erzeugt „Warum" + „Achtung",
   belegt durch Profil/JD.
5. **Match-Quittung** — Score + Evidenz + geprüfte Kriterien → aus „94 %" wird eine
   verteidigbare statt einer Marketing-Aussage.

Ehrliche Grenzen: Qualität ∝ Eingabequalität; Kaltstart real; **Fairness ist rechtliche
Exposition** — das Modell darf nicht nach geschützten Merkmalen ranken, und das muss beweisbar sein.

## 7. Kern-Datenmodell (mandantenfähig ab Tag 1)

`Candidate` · `Job` · `Company` · `Application/Pipeline` (Zustandsmaschine sourced→placed) ·
`Document` · `EnrichmentRecord` (Feldänderung + Quelle/Konfidenz/Zeit) · `Receipt`
(append-only Nachweis: read/assert/verify/write) · `Tenant/User/Role`.
**Receipt** und **EnrichmentRecord** fehlen den meisten ATS — sie machen das System auditierbar.

## 8. Compliance ist Produktwert (EU)

- **DSGVO Art. 6** — berechtigtes Interesse mit dokumentierter Abwägung (ins Design).
- **DSGVO Art. 14** — Info bei Dritterhebung → Benachrichtigungs-Workflow ist ein Feature.
- **DSGVO Art. 22** — menschliche Aufsicht über folgenreiche automatisierte Entscheidungen.
- **EU-KI-Verordnung** — Recruiting = **Hochrisiko** (Anhang III). Die Verifikations-/
  Quittungs-/Aufsichtsschicht bildet fast 1:1 die Pflichten ab — kein Gold-Plating.
- **Scraping** — nur öffentliche Job-/Unternehmensdaten; Personen-Scraping ist juristische, nicht technische Entscheidung.
- **Datenresidenz** — EU-gehostet, Enterprise-LLM ohne Training auf Kundendaten, AVV je Unterauftragsverarbeiter.

## 9. Build-Reihenfolge (Umsatz vor Breite)

Verifikations-/Quittungs-Rückgrat läuft ab Phase 1 durch alle Phasen.

| Phase | Inhalt |
|-------|--------|
| 0 | **Einlesen & Sehen** — Daten migrieren, read-only Candidate-360. Migrationshebel gegen den Altanbieter. |
| 1 | **Dokumenten-Intelligenz** — erster sichtbarer KI-Nutzen. |
| 2 | **Matching** — deterministische Filter + LLM-Re-Ranking + „Warum". Herzstück der Demo. |
| 3 | **Anreicherung** — Lücken füllen (Art. 14). Belebt die schlafende DB. |
| 4 | **Marktkarte & BD-Signale**. |
| 5 | **Outreach & Präsentation** (menschlich freigegeben). |

Zurückgestellt bis Umsatz da ist: Durable-Orchestrierung, Voice, Conversation Intelligence.

## 10. Differenzierung & Risiken

**Gewinnt durch:** verifizierte, belegte KI mit Quittungen · Compliance-nativ · Migration
als Hebel (Phase 0 nimmt dem Kunden den Schmerz ab).
**Schwer:** rechtliche Exposition bei Anreicherung/Scraping · Matching-Qualität + Kaltstart ·
Fairness/Bias · große Produktfläche → dünne Design-Partner-Scheibe zuerst.

## 11. Offene Fragen (formen die Architektur)

Welches ATS + wie sieht der Export aus? · Segmente (Fest/Executive/Zeitarbeit/Contracting)? ·
Wo schmerzt es am meisten (Sourcing/Screening/Matching/Präsentation/Admin)? · Welche
Datenquellen werden bereits bezahlt? · Volumen (Datensätze/Rollen/Vermittlungen pro Monat)? ·
Appetit auf die Compliance-Haltung (Agentur als Datenverantwortlicher)?

---

### Status dieses Repos gegen die Vision

| Vision | Stand im Scaffold |
|--------|-------------------|
| System of Record (Postgres) | ✅ Supabase/Postgres (+ SQLite-Fallback); `Candidate/Job/Company/Application` |
| Verifikation + Receipts | ✅ append-only, hash-chained; „agents propose / verification commits" |
| Matching: harte Filter + LLM | ✅ deterministische Filter live; LLM-Boundary als Stub (`rerank_and_explain`) |
| Candidate-360 / 4 Tabs | ✅ Kandidaten · Matching · Pipeline · Reporting (Frontend, live an API) |
| Reporting (Funnel) | ✅ `GET /api/v1/reporting/{funnel,dwell,overview}` |
| Agenten (5) | ◻︎ Verträge + Stubs vorhanden; echte Konnektoren/LLM offen |
| Anreicherung (Art. 14) | ◻︎ Workflow-Flag vorhanden, Zustelldienste offen |
| pgvector-Retrieval, MCP-Server | ◻︎ geplant (Embedding-Spalte vorbereitet) |