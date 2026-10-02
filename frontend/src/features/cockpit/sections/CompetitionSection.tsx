// Who else is interviewing our candidates — and therefore might become a
// client.
//
// `data/examples/metadata_quailfication.txt` asks whether a candidate has
// other active processes "im Idealfall sagt er uns wo -> so wissen wir wer
// ähnliche Profile sucht und ist für uns ein potentieller Neukunde". That is
// a sales lead hiding in a field recruiters already fill in.
//
// The numbers here are live and sourced: a company appears because candidates
// named it, and the candidates who did are listed, because the recruiter's
// next move is to ask one of them what the role was.

import { Building2 } from 'lucide-react'

import { useAsync } from '@/hooks/useAsync'
import { api } from '@/api/client'
import { Panel, SectionHeader } from '../ui/primitives'

export function CompetitionSection() {
  const { data } = useAsync(() => api.competingEmployers().catch(() => []), [])
  const rows = data ?? []
  // Nothing recorded yet is not a section worth rendering — an empty panel
  // would suggest the question has been asked and nobody is hiring.
  if (rows.length === 0) return null

  return (
    <section className="space-y-5">
      <SectionHeader
        id="section-wettbewerb"
        index="04"
        title="Wer sucht dieselben Profile"
        tone="gold"
        hint="Aus den Qualifikationsgesprächen · mögliche Neukunden"
      />
      <Panel className="px-7 py-5">
        <ul className="divide-y divide-cockpit-line">
          {rows.map((row) => (
            <li
              key={row.company}
              className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2.5 first:pt-0 last:pb-0"
            >
              <Building2 className="h-4 w-4 shrink-0 self-center text-cockpit-faint" />
              <span className="text-[15px] text-cockpit-text">{row.company}</span>
              <span className="font-mono text-[12px] text-gold-300">
                {row.candidate_count}{' '}
                {row.candidate_count === 1 ? 'Kandidat' : 'Kandidaten'}
              </span>
              <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-cockpit-faint">
                {row.candidates.join(' · ')}
              </span>
            </li>
          ))}
        </ul>
      </Panel>
    </section>
  )
}
