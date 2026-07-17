# eligo-tech · Frontend

React + TypeScript + Vite + Tailwind mockup of the eligo-tech recruiting CRM.
It renders the four product surfaces — **Kandidaten, Matching, Pipeline, Reporting** —
on mock data, ready to be wired to the backend API.

## Run

```bash
npm install
npm run dev          # http://localhost:5173  (proxies /api → http://localhost:8000)
npm run build        # type-check + production build
npm run lint         # tsc --noEmit
```

## Architecture

Feature-first. Each product surface is a self-contained folder under `src/features/`;
shared, cross-feature building blocks live in `src/components/`. Nothing in `features/`
imports from another feature — shared code moves up to `components/` or `lib/`.

```
src/
├── App.tsx                 # shell: sidebar + top nav + active view switch
├── components/             # cross-feature UI
│   ├── Sidebar.tsx         # dark navigation rail
│   ├── TopNav.tsx          # floating pill tabs + DE/EN switch (owns the Tab union)
│   ├── Logo.tsx
│   ├── Breadcrumb.tsx
│   └── ui/                 # primitives: Avatar, SkillBadge, VerificationScore, LinkedInMark
├── features/
│   ├── candidates/         # Kandidaten — record list/table
│   ├── matching/           # Matching — Candidate-360 + "Warum wir gematcht haben"
│   ├── pipeline/           # Pipeline — Kanban board per job
│   └── reporting/          # Reporting — funnel + charts (self-contained SVG)
├── data/                   # mock data + domain types (mirror the backend schema)
│   ├── types.ts            # Candidate, MatchReason, PipelineColumn, …
│   ├── candidates.ts
│   ├── pipeline.ts
│   └── reporting.ts
└── lib/cn.ts               # className joiner
```

## Design system

All visual tokens live in `tailwind.config.js` — **use the token, never a raw hex**.

| Token | Purpose |
|-------|---------|
| `brand.*` | muted emerald — logo, primary buttons, links, active state |
| `sidebar.*` | deep-navy rail surfaces (`DEFAULT`, `hover`, `active`, `muted`, `text`) |
| `accent.*` | warm amber — active top-tab ring, pipeline SLA dot |
| `ink.*` | text: `DEFAULT` / `soft` / `muted` / `faint` |
| `page`, `line` | app background, hairline borders |

Conventions:
- Content lives in one white `rounded-card` panel; every view starts with `pt-[76px]`
  so its header clears the floating `TopNav`.
- Skill/verification semantics are centralised: `VerificationScore` owns the
  ≥90 green / ≥75 amber / else red thresholds; `SkillBadge` owns tone→color. Don't
  re-implement these inline.
- Icons: `lucide-react` only.
- Language: UI copy is German (the target market); `TopNav` carries a DE/EN switch
  as a stub for future i18n.

## Wiring to the backend (next step)

Mock data in `src/data/` is intentionally shaped like the backend response bodies
(candidate: name/email/phone/skills/verification; match: reasons[] with
title/strength/evidence). To go live, replace the static imports with `fetch('/api/v1/...')`
calls — the Vite dev proxy already forwards `/api` to the backend on :8000. Keep the
`data/types.ts` shapes as the contract.

## Conventions

- TypeScript strict; no `any`. Props typed inline or via a local `interface`.
- Presentational components stay pure; no data fetching inside `ui/` primitives.
- Match the surrounding file's idiom (functional components, named exports, Tailwind classes).