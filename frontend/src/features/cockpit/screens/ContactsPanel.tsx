// The people behind one employer's public ads — shared by the screens that
// ask "who do I call?".
//
// It reads ad text already in the corpus: no fetch (ARCHITECTURE.md RULE 1),
// nothing stored until a recruiter clicks "Übernehmen", which is where
// provenance and the GDPR Art. 14 notice attach. Every contact shows the ad
// line it was read from, because the parser is a regex and a recruiter should
// see in one glance whether it read the ad right.

import { useState } from 'react'
import { Check, ChevronDown, ExternalLink, Mail, Phone, UserPlus } from 'lucide-react'
import { ApiError, api } from '@/api/client'
import type { CompanyContactsDTO, ContactCandidateDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'
import { cn } from '@/lib/cn'
import { Chip } from '../ui/primitives'
import { Button } from '../ui/forms'

export const dateDe = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleDateString('de-DE', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
      })
    : '—'

export const de = (n: number) => n.toLocaleString('de-DE')

/** Where a contact came from, as recorded on the manager row. Public web owes
 *  an Art. 14 notice; the backend derives that from this value. */
const PUBLIC_SOURCE = 'public_web'

/**
 * People search on the networks, not a scrape of them. Neither LinkedIn nor
 * XING offers an API that returns contact details, and scraping breaks both
 * sites' terms — so the recruiter opens the search, checks the profile, and
 * the match is a human judgement.
 */
const searchTerms = (contact: ContactCandidateDTO, company: string) =>
  encodeURIComponent(
    [contact.first_name, contact.last_name, company.replace(/\b(GmbH|AG|SE|KG|& Co\.?|KGaA|mbH|e\.V\.)\b/g, '')]
      .filter(Boolean)
      .join(' ')
      .replace(/\s+/g, ' ')
      .trim(),
  )
const linkedInSearch = (c: ContactCandidateDTO, company: string) =>
  `https://www.linkedin.com/search/results/people/?keywords=${searchTerms(c, company)}`
const xingSearch = (c: ContactCandidateDTO, company: string) =>
  `https://www.xing.com/search/members?keywords=${searchTerms(c, company)}`

function NetworkLink({ href, label, className }: { href: string; label: string; className: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={`Auf ${label} suchen`}
      className="flex items-center gap-1.5 rounded-lg border border-cockpit-line px-2.5 py-1.5 text-[12px] text-cockpit-dim transition-colors hover:border-cockpit-edge hover:text-cockpit-text"
    >
      <span
        className={cn(
          'inline-flex h-4 w-4 items-center justify-center rounded-[3px] text-[9px] font-bold leading-none text-white',
          className,
        )}
      >
        {label === 'LinkedIn' ? 'in' : 'X'}
      </span>
      {label}
    </a>
  )
}

function ContactRow({
  contact,
  companyName,
  onSave,
}: {
  contact: ContactCandidateDTO
  companyName: string
  onSave: (contact: ContactCandidateDTO) => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const held = contact.manager_id !== null

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      await onSave(contact)
    } catch {
      setError('Übernahme fehlgeschlagen.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <li className="border-b border-cockpit-line/40 py-3 last:border-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="min-w-[14rem]">
          <p className="text-[15px] text-cockpit-text">
            {contact.salutation && (
              <span className="text-cockpit-faint">{contact.salutation} </span>
            )}
            {contact.full_name}
          </p>
          {contact.role_title && (
            <p className="text-[13px] text-cockpit-dim">{contact.role_title}</p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3 font-mono text-[12px] text-cockpit-dim">
          {contact.phone && (
            <a
              href={`tel:${contact.phone.replace(/[^\d+]/g, '')}`}
              className="flex items-center gap-1 hover:text-mint-400"
            >
              <Phone className="h-3.5 w-3.5 text-cockpit-faint" />
              {contact.phone}
            </a>
          )}
          {contact.email && (
            <a href={`mailto:${contact.email}`} className="flex items-center gap-1 hover:text-mint-400">
              <Mail className="h-3.5 w-3.5 text-cockpit-faint" />
              {contact.email}
            </a>
          )}
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="flex items-center gap-1 text-cockpit-faint transition-colors hover:text-cockpit-text"
            title="Die Anzeigen, die diese Person nennen"
          >
            <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-180')} />
            in {de(contact.mention_count)} {contact.mention_count === 1 ? 'Anzeige' : 'Anzeigen'}
          </button>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <NetworkLink href={linkedInSearch(contact, companyName)} label="LinkedIn" className="bg-[#0a66c2]" />
          <NetworkLink href={xingSearch(contact, companyName)} label="XING" className="bg-[#006567]" />
          {held ? (
            <span className="flex items-center gap-1.5 px-2 font-mono text-[12px] text-mint-400">
              <Check className="h-4 w-4" />
              im Workspace
            </span>
          ) : (
            <Button tone="primary" onClick={save} disabled={saving}>
              <UserPlus className="h-4 w-4" />
              {saving ? 'Übernimmt…' : 'Übernehmen'}
            </Button>
          )}
        </div>
      </div>

      {error && <p className="mt-1.5 text-[12px] text-coral-400">{error}</p>}

      {/* The evidence: the ad line the name was read from. Ad text is
          third-party content and is rendered as text, never as markup. */}
      {open && (
        <ul className="mt-2.5 space-y-2">
          {contact.evidence.map((e) => (
            <li
              key={`${e.posting_id}-${e.origin}`}
              className="rounded-lg border border-cockpit-line bg-cockpit-inset px-3 py-2"
            >
              <div className="flex flex-wrap items-baseline gap-x-3 font-mono text-[12px] text-cockpit-faint">
                <span className="font-sans text-[13px] text-cockpit-dim">{e.posting_title}</span>
                {!e.is_active && <Chip>geschlossen</Chip>}
                <span className="ml-auto">{dateDe(e.posted_at)}</span>
                {/* Same words as Markt: "Anzeige" is the BA text, "Quelle" the
                    partner-board page the nightly job read. */}
                {e.url && (
                  <a
                    href={e.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="flex items-center gap-1 hover:text-mint-400"
                    title={
                      e.origin === 'quelle'
                        ? 'Genannt auf der Partnerseite der Anzeige'
                        : 'Genannt im Anzeigentext der Bundesagentur'
                    }
                  >
                    {e.origin === 'quelle' ? 'Quelle' : 'Anzeige'}{' '}
                    <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>
              <p className="mt-1 whitespace-pre-wrap text-[13px] leading-relaxed text-cockpit-dim">
                „{e.quote}“
              </p>
            </li>
          ))}
          {contact.mention_count > contact.evidence.length && (
            <li className="font-mono text-[12px] text-cockpit-faint">
              +{de(contact.mention_count - contact.evidence.length)} weitere Anzeigen
            </li>
          )}
        </ul>
      )}
    </li>
  )
}

/**
 * The people behind one employer's ads. Loaded on demand — the button is the
 * funnel step, and reading a large employer's ads is not free.
 */
export interface ContactsPanelCompany {
  hub_company_id: string
  /** This workspace's own company row, once adopted. null while only watched. */
  company_id: string | null
}

export function ContactsPanel({
  company,
  onAdopted,
}: {
  company: ContactsPanelCompany
  onAdopted: (companyId: string) => void
}) {
  const [reloadKey, setReloadKey] = useState(0)
  const [art14, setArt14] = useState(false)
  const result = useAsync<CompanyContactsDTO>(
    () => api.hubCompanyContacts(company.hub_company_id),
    [company.hub_company_id, reloadKey],
  )

  const save = async (contact: ContactCandidateDTO) => {
    const data = result.data
    if (!data) return
    const person = {
      full_name: contact.full_name,
      role_title: contact.role_title,
      email: contact.email,
      phone: contact.phone,
      source: PUBLIC_SOURCE,
      // The ad itself — the answer to "where did you get my data?".
      source_detail: (contact.evidence[0]?.url ?? `hub_job_postings/${contact.evidence[0]?.posting_id}`).slice(0, 500),
    }
    if (data.company_id) {
      await api.createManager({
        ...person,
        company_id: data.company_id,
        first_name: contact.first_name,
        last_name: contact.last_name,
      })
    } else {
      // Not adopted yet: the first saved contact adopts the employer too.
      // That crossing goes through the verification gate and leaves a receipt.
      try {
        const adopted = await api.adoptHubCompany(company.hub_company_id, person)
        onAdopted(adopted.company_id)
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 409)) throw e
        // Adopted meanwhile (another tab, another site of the employer):
        // reload to learn the company id, and let the user click again.
        setReloadKey((k) => k + 1)
        return
      }
    }
    setArt14(true)
    setReloadKey((k) => k + 1)
  }

  if (result.loading && !result.data) {
    return <p className="font-mono text-[13px] text-cockpit-faint">liest die Anzeigentexte…</p>
  }
  if (result.error) {
    return (
      <p className="text-[13px] text-coral-400">
        Ansprechpartner konnten nicht geladen werden — {result.error.message.slice(0, 200)}
      </p>
    )
  }
  const data = result.data
  if (!data) return null

  return (
    <div className="space-y-3">
      <p className="font-mono text-[12px] text-cockpit-faint">
        <span className="text-cockpit-text">{de(data.postings_with_text)}</span> von{' '}
        {de(data.postings_scanned)} Anzeigen mit Text gelesen ·{' '}
        <span className="text-cockpit-text">{de(data.contacts.length)}</span>{' '}
        {data.contacts.length === 1 ? 'Person' : 'Personen'} namentlich genannt
      </p>

      {data.contacts.length === 0 ? (
        <p className="max-w-2xl text-[13px] leading-relaxed text-cockpit-dim">
          {data.postings_with_text === 0
            ? 'Für dieses Unternehmen liegen noch keine Anzeigentexte vor. Der nächtliche Lauf lädt sie nach; danach erscheinen hier die genannten Ansprechpartner.'
            : 'Keine der Anzeigen nennt eine Person — nur Firmenpostfächer. Das ist bei großen Arbeitgebern mit zentralem Recruiting häufig.'}
        </p>
      ) : (
        <ul>
          {data.contacts.map((contact) => (
            <ContactRow
              key={contact.key}
              contact={contact}
              companyName={data.company_name}
              onSave={save}
            />
          ))}
        </ul>
      )}

      {data.mailboxes.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-t border-cockpit-line/60 pt-2.5">
          <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-cockpit-faint">
            Firmenpostfächer
          </span>
          {data.mailboxes.slice(0, 6).map((m) => (
            <a
              key={m.email}
              href={`mailto:${m.email}`}
              className="rounded-md border border-cockpit-line px-2 py-0.5 font-mono text-[12px] text-cockpit-dim transition-colors hover:border-mint-600 hover:text-mint-400"
            >
              {m.email}
            </a>
          ))}
        </div>
      )}

      {art14 && (
        <p className="text-[12px] leading-relaxed text-gold-400">
          Kontakt übernommen. Er stammt aus einer öffentlichen Anzeige — eine
          Information nach Art. 14 DSGVO ist fällig und unter „Manager“ vorgemerkt.
        </p>
      )}
    </div>
  )
}
