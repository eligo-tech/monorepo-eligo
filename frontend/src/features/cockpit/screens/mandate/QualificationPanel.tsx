// "Qualifizierung · Interessierte Kandidaten" and "Externe Recruiter ·
// Eingereichte Kandidaten".
//
// The stretch before a process starts: CV in, KI-Einschätzung, video
// interview, transcript checked against the CV, then the presentation that
// begins the nine steps. Two of those five stages exist today — a CV can be
// uploaded and parsed, and a transcript can be read for the qualification
// fields (both on the Kandidaten screen) — but nothing records WHERE a
// candidate stands in this stretch, so the pipeline itself is drawn and
// marked.
//
// The order is the design's and it is a rule, not a layout: the CV must be in
// before the video interview, because the KI prepares the questions from it.

import { Check } from 'lucide-react'

import { cn } from '@/lib/cn'
import { Chip, Panel } from '../../ui/primitives'
import { Button } from '../../ui/forms'
import { DEMO_HINT, DemoText, PanelHead } from './parts'
import type { Mandate } from '../../data/types'

const STAGES = [
  'CV-Prüfung',
  'KI-Einschätzung',
  'Video-Interview',
  'Transkript-Abgleich',
  'Vorstellen',
]

const INTERESTED = [
  {
    name: 'Marco Berger',
    role: 'Senior Data Engineer',
    source: 'LinkedIn',
    fit: 84,
    cv: 'CV gut',
    stage: 3,
    note: 'Transkript eingegangen · CV deckt sich mit dem Gespräch.',
    action: 'Weiter →',
  },
  {
    name: 'Julia Frank',
    role: 'Data Engineering Lead',
    source: 'Xing',
    fit: 79,
    cv: 'CV mangelhaft',
    stage: 1,
    note: 'Solide, CV dünn bei Cloud. Kurzer Video-Call zur Klärung empfohlen.',
    action: 'Zum Video-Call einladen →',
  },
]

const SUBMITTED = [
  {
    name: 'Tobias Renner',
    role: 'Senior Data Engineer',
    source: 'LinkedIn',
    by: 'R. Hoffmann · TalentBridge',
    check: 83,
  },
  {
    name: 'Sara Klein',
    role: 'Data Platform Engineer',
    source: 'Xing',
    by: 'M. Schulz · DevHunt',
    check: 71,
  },
]

function MiniPipeline({ stage }: { stage: number }) {
  return (
    <ol className="flex flex-wrap items-center gap-x-1 gap-y-2">
      {STAGES.map((label, i) => {
        const done = i < stage
        const current = i === stage
        return (
          <li key={label} className="flex min-w-[96px] flex-1 flex-col items-center">
            <div className="relative flex h-8 w-full items-center justify-center">
              {i > 0 && (
                <span
                  className={cn(
                    'absolute left-0 top-1/2 h-px w-1/2 -translate-y-1/2',
                    done ? 'bg-mint-600' : 'bg-cockpit-line',
                  )}
                />
              )}
              {i < STAGES.length - 1 && (
                <span
                  className={cn(
                    'absolute right-0 top-1/2 h-px w-1/2 -translate-y-1/2',
                    i < stage - 1 ? 'bg-mint-600' : 'bg-cockpit-line',
                  )}
                />
              )}
              <span
                className={cn(
                  'relative z-10 flex h-[22px] w-[22px] items-center justify-center rounded-full border-2',
                  done
                    ? 'border-mint-500 bg-mint-500 text-[#0f1a12]'
                    : current
                      ? 'border-coral-400'
                      : 'border-cockpit-line',
                )}
              >
                {done && <Check className="h-3 w-3" strokeWidth={3} />}
              </span>
            </div>
            <span
              className={cn(
                'text-center text-[11.5px]',
                done || current ? 'text-cockpit-dim' : 'text-cockpit-faint',
              )}
            >
              {label}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

export function QualificationPanel({ mandate }: { mandate: Mandate }) {
  return (
    <div className="space-y-5">
      <Panel className="px-6 py-5">
        <PanelHead
          tag="Qualifizierung"
          tone="gold"
          title={`Interessierte Kandidaten · ${mandate.ref} · ${mandate.title}`}
          note={`CV → Video → Vorstellung → Prozess · ${DEMO_HINT}`}
        />
        <p className="-mt-2 mb-4 text-[13px] leading-relaxed text-cockpit-dim">
          Der CV muss <b className="text-cockpit-text">vor</b> dem Video-Interview
          eingehen — die KI prüft die Eignung und bereitet die Fragen daraus vor. Nach
          dem Gespräch wird der CV mit dem Transkript abgeglichen und die Vorstellung
          erstellt. Mit der Vorstellung beim Kunden startet der Prozess.
        </p>

        <div className="space-y-3">
          {INTERESTED.map((person) => (
            <div
              key={person.name}
              className="rounded-xl border border-cockpit-line bg-cockpit-inset px-4 py-3.5"
            >
              <div className="flex flex-wrap items-baseline gap-2.5">
                <span className="text-[14px] font-semibold text-cockpit-text">
                  {person.name}
                </span>
                <span className="text-[13px] text-cockpit-dim">· {person.role}</span>
                <Chip>{person.source}</Chip>
                <span className="ml-auto font-mono text-[12px] text-cockpit-dim">
                  Eignung <DemoText source="Kein Eignungs-Score im Datensatz">{person.fit}%</DemoText>
                </span>
                <Chip tone={person.cv === 'CV gut' ? 'mint' : 'gold'}>{person.cv}</Chip>
              </div>

              <div className="mt-3">
                <MiniPipeline stage={person.stage} />
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-cockpit-line pt-3">
                <p className="min-w-0 flex-1 text-[13px] text-cockpit-dim">
                  <DemoText source="Keine KI-Einschätzung gespeichert">
                    {person.note}
                  </DemoText>
                </p>
                <Button disabled title="Die Qualifizierungs-Pipeline ist noch nicht angebunden">
                  {person.action}
                </Button>
              </div>
            </div>
          ))}
        </div>
      </Panel>

      <Panel className="px-6 py-5">
        <PanelHead
          tag="Externe Recruiter"
          tone="coral"
          title={`Eingereichte Kandidaten · ${mandate.ref}`}
          note={DEMO_HINT}
        />
        <p className="-mt-2 mb-4 text-[13px] leading-relaxed text-cockpit-dim">
          Externe Recruiter sehen die wichtigsten Auftragsdaten und laden passende
          Kandidaten hoch. Die KI prüft, der Recruiter entscheidet — ablehnen, direkt
          kontaktieren oder in die Qualifizierung übernehmen.
        </p>

        <div className="space-y-3">
          {SUBMITTED.map((person) => (
            <div
              key={person.name}
              className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-cockpit-line bg-cockpit-inset px-4 py-3"
            >
              <span className="text-[14px] font-semibold text-cockpit-text">
                {person.name}
              </span>
              <span className="text-[13px] text-cockpit-dim">· {person.role}</span>
              <Chip>{person.source}</Chip>
              <span className="ml-auto font-mono text-[12px] text-mint-400">
                KI-Check <DemoText source="Kein KI-Check im Datensatz">{person.check}%</DemoText>
              </span>
              <div className="w-full font-mono text-[11.5px] text-cockpit-faint">
                Eingereicht von {person.by}
              </div>
              <div className="flex w-full flex-wrap justify-end gap-2">
                <Button disabled title="Noch nicht angebunden">Ablehnen</Button>
                <Button tone="primary" disabled title="Noch nicht angebunden">
                  In Qualifizierung →
                </Button>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  )
}
