# eligo-tech · Frontend

React + TypeScript + Vite + Tailwind. The product surface is the **Cockpit** — a
dark, full-bleed dashboard that shows what the system noticed, where revenue stands,
which mandates are fillable, which placements are running, and what to do next.

## Run

```bash
npm install
npm run dev          # http://localhost:5173  (proxies /api → http://localhost:8000)
npm run build        # type-check + production build
npm run lint         # tsc --noEmit
```

Without `VITE_CLERK_PUBLISHABLE_KEY` the app runs in no-login demo mode. To see
the cockpit while a Clerk key is present in `.env`, start it with the key blanked:
`VITE_CLERK_PUBLISHABLE_KEY= npx vite --port 5199`.

## Architecture

Feature-first. Each surface is a self-contained folder under `src/features/`; shared,
cross-feature building blocks live in `src/components/`. Nothing in `features/`
imports from another feature — shared code moves up to `components/` or `lib/`.

```
src/
├── App.tsx                     # landing page ↔ cockpit, by URL hash
├── features/cockpit/           # ← the product surface
│   ├── CockpitShell.tsx        # grid background, screen switch, hash routing (owns SCREENS)
│   ├── CommandBar.tsx          # wordmark, search, status chips, typeface switch, Clerk controls
│   ├── Navigator.tsx           # arrow cluster: ←/→ screen, ↑/↓ section, + keyboard
│   ├── useTypeface.ts          # the Jet · Mono · Heli switch
│   ├── screens/                # CockpitScreen · KandidatenweltScreen
│   ├── sections/               # SignalsPanel · Revenue (01) · JobScoring (02) · Process (03) · NextActions
│   ├── ui/                     # primitives.tsx · Gauge · ProcessStepper · ScoreBar · Carousel
│   └── data/                   # types · mock (demo baseline) · adapters (DTO joins) · useCockpitData
├── components/                 # cross-feature UI (ui/Avatar, ui/LinkedInMark, …)
├── api/                        # client.ts (typed fetch) · types.ts (DTOs) · adapters.ts
├── hooks/useAsync.ts
└── landing/                    # marketing page, self-contained CSS
```

**Adding a screen** is one entry in `SCREENS` (`CockpitShell.tsx`) plus a component
exporting its section anchor ids. Hash routing, the navigator and keyboard paging
follow automatically.

### Parked surfaces

`src/features/{candidates,matching,pipeline,reporting}/`, `components/Sidebar.tsx`
and `components/TopNav.tsx` are the previous light-themed four-tab CRM. They are
**unrouted but still compiled** — kept so the CV upload, dossier editor and
verified-edit flows can be restyled and re-added as cockpit screens one at a time.
Don't delete them, and don't import from them into `features/cockpit/`.

## Design system

All visual tokens live in `tailwind.config.js` — **use the token, never a raw hex.**

| Token | Purpose |
|-------|---------|
| `cockpit.{bg,inset,surface,raised}` | near-black, faintly warm surfaces (dark ↑ light) |
| `cockpit.{line,edge}` | hairline borders — `edge` is the hover/focus step |
| `cockpit.{text,dim,faint}` | text ladder: primary / secondary / metadata |
| `mint.*` | positive, done steps, PROGNOSE, live match scores |
| `gold.*` | potential, warnings, business-dev |
| `coral.*` | critical, blocked steps, `Vorstellen` |
| `lav.*` | approval / Freigabe |
| `bg-grid` + `bg-grid-cell` | the graph-paper overlay behind every screen |
| `shadow-panel`, `shadow-glow-*` | panel lift and gauge/ring bloom |

The legacy `brand.*`, `sidebar.*`, `accent.*`, `ink.*`, `page`, `line` tokens are
still there for the parked views — don't use them in the cockpit.

Conventions:

- **Mono is semantic.** Every number, all-caps label, chip, record reference and
  section hint is `font-mono`; names, headings and prose are `font-sans`. Both
  resolve through `--font-ui` / `--font-mono` CSS vars so the command bar's
  `Jet · Mono · Heli` control can swap faces — never hard-code a font family.
  Mono digits are `tabular-nums` (set in `index.css`) so values don't jitter.
- **Every figure carries provenance.** Displayed numbers are `Figure` objects
  (`{ value, provenance, source }`), not bare numbers, and are rendered through
  `<Figure>` / `<Money>` from `ui/primitives.tsx`. Demo values get a `°` marker
  with the reason on hover. This is the product invariant — a figure the backend
  can't vouch for must never look verified. Use `live()` / `demo()` from
  `data/types.ts` when constructing one.
- Semantics are centralised: `scoreTone()` (ScoreBar.tsx) owns the ≥70 mint /
  ≥50 gold / else coral thresholds; `STAGE_TO_STEP` (data/adapters.ts) owns the
  pipeline-stage → process-step mapping; `FEE_RATE` is the single fee assumption.
  Don't re-implement these inline.
- Charts are hand-rolled SVG (`ui/Gauge.tsx`). No chart library.
- Icons: `lucide-react` only.
- Language: UI copy is German (the target market).

## Data: mock floor, live overlay

`useCockpitData()` never returns null. `data/mock.ts` is the floor — the exact
figures from `data/design/*.png` — and live calls overlay the sections the backend
can serve, per section, so one failing endpoint degrades one section rather than
the screen. `state.live` says which sections are live and drives their header hints.

| Section | Source |
|---|---|
| 03 Laufende Prozesse | live: `/pipeline/board` joined to `/candidates`, `/jobs`, `/companies` |
| `Ø N T bis Offer` | live: `reportingOverview().dwell` |
| 02 Jobscoring score | live: `matchJob(id)` per open mandate → mean of the top 3 that cleared hard filters |
| Jobscoring delta, `M %` | none — rendered as `—`, not invented |
| 01 Umsatz, Signale, Aktionen, market roles | demo — no revenue/signal/market model in the backend yet |

The backend's `PipelineStage` enum has 7 stages; the cockpit's process has 9 steps.
`STAGE_TO_STEP` maps `presented → 1`, `interview → 4`, `placed → 9`; pre-presentation
and rejected applications get no card. Widening the enum is a one-entry change there.

## Conventions

- TypeScript strict; no `any`. Props typed inline or via a local `interface`.
- Presentational components stay pure; no data fetching inside `ui/`.
- Match the surrounding file's idiom (functional components, named exports, Tailwind).
