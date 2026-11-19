// "Stammdaten · Firma · Manager · Job · Konditionen"
//
// The master data a recruiter needs in front of them before they call anyone.
// Firma, Manager and Job come from the record. The register details
// (HRB/USt-ID) come from the company's Impressum (ELI-39), read by the daily
// job — Markt's reading, else the company's own — and link to the page and
// the day it was read; until one is verified they show "—". The Konditionen
// and the seniority/employment type have no column yet and are drawn as the
// design draws them, marked.
//
// How complete the briefing is lives in the Briefing panel below
// (Briefing-Bewertung, ELI-47) — one score, computed by the backend.

import { t } from '@/i18n'

import { ExternalLink, Globe, Linkedin } from 'lucide-react'

import { api } from '@/api/client'
import type { CompanyDTO, ManagerDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { date } from '@/i18n/format'
import { registerFacts } from '../../ui/switchboard'
import { Panel } from '../../ui/primitives'
import { Button } from '../../ui/forms'
import { DemoText, PanelHead, StammRow } from './parts'
import { SetContact } from './SetContact'
import type { Mandate } from '../../data/types'

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
  // Reads only — the daily job fills it; nothing here fetches a website.
  const board = useAsync(
    () => (company ? api.companyRegister(company.id) : Promise.resolve(null)),
    [company?.id],
  ).data
  const register = registerFacts(board)
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
            {register && board ? (
              <a
                href={board.impressum_url ?? undefined}
                target="_blank"
                rel="noreferrer"
                className="hover:text-mint-400"
                title={`${t('Laut Impressum, abgerufen am')} ${date(board.checked_at)}`}
              >
                {register.register ?? t('HRB —')} · {t('USt-ID')} {register.vat ?? '—'}
              </a>
            ) : (
              <span title={t('Noch nicht aus dem Impressum bestätigt — der tägliche Abgleich liest es.')}>
                {t('HRB — · USt-ID —')}
              </span>
            )}
            {company?.location && ` · ${t('Standort')}: ${company.location}`}
            {company?.industry && ` · ${t('Branche')}: ${company.industry}`}
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
              {t('Kein Ansprechpartner hinterlegt.')}{' '}
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

      <StammRow label={t('Konditionen')} tone="lav">
        <DemoText source={t('Kein Vertragsmodell im Datensatz — Rahmenvertrag folgt')}>
          {t('25 % vom Bruttojahresgehalt · Basis — · 14 Tage netto · 6 Monate Garantie')}
        </DemoText>
      </StammRow>

      <div className="mt-3 flex flex-wrap gap-2">
        <Button disabled title={t('Website, HRB und USt-ID kommen täglich automatisch aus dem Impressum — kein Abruf per Klick')}>
          <Globe className="h-4 w-4" /> {t('Firma aus Internet')}
        </Button>
        <Button disabled title={t('LinkedIn-Anreicherung ist noch nicht angebunden')}>
          <ExternalLink className="h-4 w-4" /> {t('Manager via LinkedIn')}
        </Button>
      </div>
    </Panel>
  )
}
