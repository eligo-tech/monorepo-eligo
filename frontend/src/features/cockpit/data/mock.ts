// The cockpit's demo baseline — the exact figures drawn in data/design/*.png.
//
// This is not throwaway scaffolding: it is the fallback the whole surface renders
// from when the backend is unreachable, and the source for the sections no
// endpoint serves yet (revenue targets, learned deal-chance, detected signals,
// market roles). Everything here is tagged `demo`, so the UI marks it as such.
// useCockpitData overlays live values on top and flips those fields to `live`.

import { t } from '@/i18n'

import { demo, type CockpitData, type PeriodKey, type ProcessStep, type RevenuePanel } from './types'

/** The nine process steps, in the order docs/process_design sets out. Single
 *  source of truth — stepper, progress ring and stage mapping all read it.
 *  **Termin vor Vorbereitung**: you agree the appointment, then prepare the
 *  candidate for it. This list had preparation first, which meant preparing
 *  someone for a meeting that did not exist yet; the backend's
 *  `pipeline/steps.py` is the same order. */
export const PROCESS_STEPS: { key: ProcessStep['key']; label: string }[] = [
  { key: 'vorgestellt', label: t('Vorgestellt') },
  { key: 'feedback-1', label: t('Feedback') },
  { key: 'interview', label: t('Interviewtermin') },
  { key: 'vorbereitung', label: t('Interview-Vorb.') },
  { key: 'feedback-2', label: t('Feedback') },
  { key: 'finaltermin', label: t('Finaltermin') },
  { key: 'final-vorb', label: t('Final-Vorb.') },
  { key: 'offer', label: t('Offer & Zusage') },
  { key: 'vertrag', label: t('Vertrag') },
]

/** Steps that carry two-party sub-chips in the mockups. */
const STEP_CHIPS: Partial<Record<ProcessStep['key'], string[]>> = {
  'feedback-1': [t('Kand.'), t('Kunde')],
  'feedback-2': [t('Kand.'), t('Kunde')],
  offer: ['Offer', t('Zusage')],
}

/**
 * Build the nine steps from a compact spec.
 *
 * @param reached  index of the furthest step that is done (0-based, -1 = none)
 * @param marker   state of the step right after the done run
 * @param meta     per-step mono captions (dates / times)
 * @param chipsDone how many of a step's two sub-chips are met (default: all if
 *                  the step is done, none otherwise)
 */
export function buildSteps(
  reached: number,
  marker: 'current' | 'blocked' | 'pending',
  meta: Partial<Record<ProcessStep['key'], string>> = {},
  chipsDone: Partial<Record<ProcessStep['key'], number>> = {},
): ProcessStep[] {
  return PROCESS_STEPS.map(({ key, label }, i) => {
    const state: ProcessStep['state'] =
      i <= reached ? 'done' : i === reached + 1 ? marker : 'pending'
    const chipLabels = STEP_CHIPS[key]
    const met = chipsDone[key] ?? (state === 'done' ? (chipLabels?.length ?? 0) : 0)
    return {
      key,
      label,
      state,
      meta: meta[key],
      chips: chipLabels?.map((cl, ci) => ({ label: cl, done: ci < met })),
    }
  })
}

// ── 01 Umsatz & Potenzial ───────────────────────────────────────────────────

/** The two deals in "Kurz vor Abschluss" (identical across periods). */
const CLOSING = [
  {
    id: 'cd-1',
    candidateRef: '#K-0588',
    mandateRef: '#A-260',
    client: 'FinTech',
    fee: demo(41000, t('Demo-Fee — kein Honorarmodell im Backend')),
    timing: t('diesen Monat'),
    chance: demo(85, t('Gelernte Abschlusschance — noch kein Signal-Store')),
    note: t('mündl. Zusage'),
  },
  {
    id: 'cd-2',
    candidateRef: '#K-0731',
    mandateRef: '#A-231',
    client: 'Scale-up',
    fee: demo(32000, t('Demo-Fee — kein Honorarmodell im Backend')),
    timing: t('diesen Monat'),
    chance: demo(78, t('Gelernte Abschlusschance — noch kein Signal-Store')),
  },
]

const revenuePanel = (
  key: PeriodKey,
  caption: string,
  actual: number,
  potential: number,
  target: number,
): RevenuePanel => ({
  key,
  caption,
  actual: demo(actual, t('Kein Umsatzmodell im Backend')),
  potential: demo(potential, 'Gewichtete Pipeline — Demo'),
  target: demo(target, 'Zielvorgabe — Demo'),
  yearActual: demo(840000, t('Kein Umsatzmodell im Backend')),
  yearTarget: demo(1200000, 'Zielvorgabe — Demo'),
  closing: CLOSING,
  pipelineTotal: demo(89000, 'Restpipeline — Demo'),
  pipelineWeighted: demo(46200, t('Gewichtet mit Abschlusschance — Demo')),
})

const REVENUE_PANELS: Record<PeriodKey, RevenuePanel> = {
  jahr: revenuePanel('jahr', '2026', 840000, 260000, 1200000),
  quartal: revenuePanel('quartal', 'Q3', 245000, 158000, 350000),
  monat: revenuePanel('monat', t('JULI'), 62000, 73000, 100000),
  tag: revenuePanel('tag', t('HEUTE'), 4200, 9800, 6500),
}

// ── The baseline ────────────────────────────────────────────────────────────

export const MOCK_COCKPIT: CockpitData = {
  status: {
    pendingChanges: demo(5, 'Datenlauf-Queue — Demo'),
    humanInTheLoop: true,
    address: 'Sie',
    initials: 'TB',
  },

  signals: [
    {
      id: 'sig-1',
      kind: 'email',
      label: t('E-Mail · vor 2 Std'),
      text: t('Manager (Scale-up) kündigt Offer für #K-0731 an — Stage „Offer” vorschlagen?'),
      refs: ['#K-0731'],
      action: t('Übernehmen'),
      provenance: 'demo',
    },
    {
      id: 'sig-2',
      kind: 'note',
      label: t('Telefonnotiz'),
      text: t('Bei #A-238 Budget bestätigt. Gelernt: Manager braucht Ø 21 Tage bis Offer → Abschluss eher August.'),
      refs: ['#A-238'],
      action: t('Prüfen'),
      provenance: 'demo',
    },
  ],

  slides: [
    {
      id: 'slide-umsatz',
      title: t('Umsatz & Potenzial'),
      kind: 'revenue',
      panels: REVENUE_PANELS,
    },
    // The mockup shows four dots under this panel. These three are the declared
    // extension points — add a `kind: 'revenue'`-style panel (or a new kind) and
    // the carousel picks it up with no component changes.
    {
      id: 'slide-besetzung',
      title: t('Besetzungsquote'),
      kind: 'placeholder',
      hint: t('Platzhalter — braucht Platzierungs-Historie pro Mandat.'),
    },
    {
      id: 'slide-tto',
      title: t('Time-to-Offer'),
      kind: 'placeholder',
      hint: t('Platzhalter — speist sich später aus den Verweilzeiten im Reporting.'),
    },
    {
      id: 'slide-bd',
      title: t('BD-Signale'),
      kind: 'placeholder',
      hint: t('Platzhalter — kommt mit dem Market-Map-Agenten.'),
    },
  ],

  jobScores: [
    {
      id: 'js-1',
      mandateRef: '#A-231',
      title: 'VP Engineering',
      score: demo(88),
      delta: demo(6),
      managerChance: demo(74),
    },
    {
      id: 'js-2',
      mandateRef: '#A-238',
      title: 'Head of Data Engineering',
      score: demo(74),
      delta: demo(2),
      managerChance: demo(61),
    },
    {
      id: 'js-3',
      mandateRef: '#A-260',
      title: 'Team Lead Frontend',
      score: demo(66),
      delta: demo(0),
      managerChance: demo(47),
    },
    {
      id: 'js-4',
      mandateRef: '#A-205',
      title: 'Interim CFO',
      score: demo(39),
      delta: demo(-9),
      managerChance: demo(22),
    },
    {
      id: 'js-5',
      mandateRef: '#A-244',
      title: 'Interim CTO',
      score: demo(81),
      delta: demo(3),
      managerChance: demo(52),
    },
    {
      id: 'js-6',
      mandateRef: '#A-219',
      title: 'Senior Architect',
      score: demo(71),
      delta: demo(1),
      managerChance: demo(58),
    },
    {
      id: 'js-7',
      mandateRef: '#A-212',
      title: 'DevOps Engineer',
      score: demo(58),
      delta: demo(-2),
      managerChance: demo(39),
    },
    {
      id: 'js-8',
      mandateRef: '#A-198',
      title: 'Head of Sales',
      score: demo(34),
      delta: demo(-4),
      managerChance: demo(28),
    },
  ],

  // Grouped on load by `mandatesFromCards` — computing it here would make the
  // mock import the adapters that import the mock.
  mandates: [],

  processes: [
    {
      id: 'pc-1',
      candidateRef: '#K-0588',
      candidateName: 'Michael Vogel',
      role: 'DevOps Lead',
      mandateRef: '#A-260',
      client: 'FinTech',
      paceLabel: t('Ø 9 T bis Offer'),
      pacePro: 'demo',
      progress: demo(92),
      fee: demo(41000, t('Demo-Fee — kein Honorarmodell im Backend')),
      statusNote: t('Mündl. Zusage · Vertrag ausstehend'),
      steps: buildSteps(7, 'current', {
        vorgestellt: '27.06',
        interview: '15.07 · 10:00',
        finaltermin: '29.07 · 14:00',
      }),
    },
    {
      id: 'pc-2',
      candidateRef: '#K-0731',
      candidateName: 'Sarah Bergmann',
      role: 'Cloud Architect',
      mandateRef: '#A-231',
      client: 'Scale-up',
      paceLabel: t('Ø 11 T bis Offer'),
      pacePro: 'demo',
      progress: demo(83),
      fee: demo(32000, t('Demo-Fee — kein Honorarmodell im Backend')),
      // Offer raus, Zusage fehlt → der Schritt blockiert.
      steps: buildSteps(
        6,
        'blocked',
        {
          vorgestellt: '09.07',
          interview: '24.07 · 11:30',
          finaltermin: '30.07 · 15:00',
        },
        { offer: 1 },
      ),
    },
    {
      id: 'pc-3',
      candidateRef: '#K-1042',
      candidateName: 'Daniel Krause',
      role: 'Lead Data Engineer',
      mandateRef: '#A-238',
      client: 'Nexval',
      paceLabel: t('Ø 21 T bis Offer'),
      pacePro: 'demo',
      progress: demo(50),
      fee: demo(28000, t('Demo-Fee — kein Honorarmodell im Backend')),
      // Kandidatenfeedback da, Kundenfeedback fehlt → blockiert bei Feedback 2.
      steps: buildSteps(
        3,
        'blocked',
        {
          vorgestellt: '02.07',
          interview: '21.07 · 09:30',
          finaltermin: '—',
        },
        { 'feedback-2': 1 },
      ),
    },
  ],

  actions: [
    {
      id: 'na-1',
      title: t('M. Wagner (CTO · Nexval) anrufen'),
      detail: t('Migrationsprojekt Q3 erwähnt · letzter Kontakt vor 26 Tagen.'),
      category: 'business-dev',
      provenance: 'demo',
    },
    {
      id: 'na-2',
      title: t('#K-0731 · Offer nachfassen'),
      detail: t('Kunde hat Offer angekündigt (aus E-Mail) · mündliche Zusage einholen.'),
      category: 'abschluss',
      provenance: 'demo',
    },
    {
      id: 'na-3',
      title: t('Anonyme Ansprache für #A-238 freigeben'),
      detail: t('3 Entwürfe warten auf Prüfung, bevor sie rausgehen.'),
      category: 'freigabe',
      provenance: 'demo',
    },
    {
      id: 'na-4',
      title: t('5 Kandidaten mit geändertem Jobtitel'),
      detail: t('Aus dem Datenlauf erkannt · Profile aktualisieren.'),
      category: 'datenlauf',
      provenance: 'demo',
    },
    {
      id: 'na-5',
      title: t('Interview-Feedback Technoparc GmbH einpflegen'),
      detail: t('Schärft Briefing und Suchprofil.'),
      category: 'feedback',
      provenance: 'demo',
    },
  ],

}
