// "Stammdaten · Firma · Manager · Job · Konditionen"
//
// The master data a recruiter needs in front of them before they call anyone.
// Firma, Manager and Job come from the record; the register details
// (HRB/USt-ID), the Konditionen and the seniority/employment type have no
// column yet and are drawn as the design draws them, marked.
//
// Briefing-Vollständigkeit is NOT a demo number: it counts how much of the
// Suchprofil this mandate actually carries. That makes it the one figure on
// the panel that improves when you fill the form in — which is the point.

import { t } from '@/i18n'

import { ExternalLink, Globe, Linkedin } from 'lucide-react'

import type { CompanyDTO, ManagerDTO } from '@/api/types'
import { Panel } from '../../ui/primitives'
import { Button } from '../../ui/forms'
import { DemoText, PanelHead, StammRow } from './parts'
import { SetContact } from './SetContact'
import type { Mandate } from '../../data/types'

/** How complete the mandate record is, as a percentage of what matters.
 *
 *  Seven things a search cannot be run well without. Deliberately a plain
 *  count rather than a weighted score: a recruiter can see which of the seven
 *  is missing by looking at the panel, and a weighting nobody agreed would
 *  just be a number with an opinion baked in. */
export function briefingCompleteness(mandate: Mandate, manager?: ManagerDTO): number {
  const checks = [
    !!mandate.title,
    !!mandate.client,
    mandate.mustHave.length > 0,
    !!mandate.location,
    mandate.salaryMin !== null || mandate.salaryMax !== null,
    !!manager,
    !!manager?.email || !!manager?.phone,
  ]
  return Math.round((checks.filter(Boolean).length / checks.length) * 100)
}

export function StammdatenPanel({
  mandate,
  company,
  manager,
  managers,
  onChanged,
}: {
  mandate: Mandate
  company?: CompanyDTO
  /** The mandate's OWN contact, read off `jobs.manager_id`. */
  manager?: ManagerDTO
  /** Everyone recorded at this client, to pick one from. */
  managers?: ManagerDTO[]
  onChanged?: () => void
}) {
  const complete = briefingCompleteness(mandate, manager)
  const band =
    mandate.salaryMin !== null && mandate.salaryMax !== null
      ? `${Math.round(mandate.salaryMin / 1000)}–${Math.round(mandate.salaryMax / 1000)}k`
      : null

  return (
    <Panel className="px-6 py-5">
      <PanelHead tag={t('Stammdaten')} title={t('Firma · Manager · Job · Konditionen')} />

      <StammRow
        label={t('Firma')}
        sub={
          <>
            <DemoText source={t('Handelsregister — noch keine Quelle angebunden')}>
              HRB — · USt-ID —
            </DemoText>
            {company?.location && ` · Standort: ${company.location}`}
            {company?.industry && ` · Branche: ${company.industry}`}
          </>
        }
      >
        <b className="font-semibold">{mandate.client}</b>
        {company?.domain && (
          <>
            {' · '}
            <a
              href={`https://${company.domain}`}
              target="_blank"
              rel="noreferrer"
              className="text-mint-400 hover:underline"
            >
              {company.domain}
            </a>
          </>
        )}
      </StammRow>

      <StammRow label="Manager">
        {manager ? (
          <>
            <b className="font-semibold">{manager.full_name}</b>
            {manager.role_title && ` · ${manager.role_title}`}
            {manager.email && ` · ${manager.email}`}
            {manager.linkedin_url && (
              <>
                {' · '}
                <a
                  href={manager.linkedin_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-mint-400 hover:underline"
                >
                  <Linkedin className="h-3.5 w-3.5" /> LinkedIn
                </a>
              </>
            )}
          </>
        ) : mandate.jobId ? (
          <>
            <span className="text-cockpit-faint">
              Kein Ansprechpartner hinterlegt.{' '}
            </span>
            <SetContact
              jobId={mandate.jobId}
              jobTitle={mandate.title}
              companyId={mandate.companyId}
              companyName={mandate.client}
              candidates={managers ?? []}
              onDone={() => onChanged?.()}
            />
          </>
        ) : (
          <span className="text-cockpit-faint">{t('Kein Ansprechpartner hinterlegt.')}</span>
        )}
      </StammRow>

      <StammRow label={t('Job')}>
        <b className="font-semibold">{mandate.title}</b>
        {mandate.location && ` · ${mandate.location}`}
        {band && ` · ${band}`}
        {' · '}
        <DemoText source={t('Seniorität und Anstellungsart sind am Mandat noch nicht erfasst')}>
          {t('Lead / Head · Festanstellung')}
        </DemoText>
      </StammRow>

      <StammRow label={t('Briefing')}>
        Vollständigkeit{' '}
        <b className={complete >= 70 ? 'text-mint-300' : 'text-gold-300'}>{complete}%</b>
        <span className="ml-2 text-cockpit-faint">
          — aus Titel, Kunde, Muss-Kriterien, Ort, Band und Ansprechpartner
        </span>
      </StammRow>

      <StammRow label={t('Konditionen')} tone="lav">
        <DemoText source={t('Kein Vertragsmodell im Datensatz — Rahmenvertrag folgt')}>
          25 % vom Bruttojahresgehalt · Basis — · 14 Tage netto · 6 Monate Garantie
        </DemoText>
      </StammRow>

      <div className="mt-3 flex flex-wrap gap-2">
        <Button disabled title={t('Firmendaten-Anreicherung ist noch nicht angebunden')}>
          <Globe className="h-4 w-4" /> Firma aus Internet
        </Button>
        <Button disabled title={t('LinkedIn-Anreicherung ist noch nicht angebunden')}>
          <ExternalLink className="h-4 w-4" /> Manager via LinkedIn
        </Button>
      </div>
    </Panel>
  )
}
