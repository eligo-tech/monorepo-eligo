// "Kandidatenprofil · CI" on the settings screen (ELI-20): the logo, the
// colour, the footer line and the AGB paragraph every cover sheet carries.
//
// Stored per workspace in the database, never in the server's environment:
// it is the customer's text and changes without a deploy. The AGB field has
// no placeholder text on purpose — it is a legal clause, and only the agency
// can say what theirs is.

import { useCallback, useEffect, useRef, useState } from 'react'
import { ImageUp, Trash2 } from 'lucide-react'

import { t } from '@/i18n'
import { ApiError, api } from '@/api/client'
import type { BrandingDTO } from '@/api/types'
import { Button, FieldLabel, TextArea, TextInput } from '../ui/forms'
import { Panel } from '../ui/primitives'

const HEX = /^#[0-9A-Fa-f]{6}$/

function describe(e: unknown): string {
  if (!(e instanceof ApiError)) return t('Fehlgeschlagen — keine Antwort vom Server.')
  if (e.status === 403) return t('Nur Administratoren können das CI ändern.')
  if (e.status === 422) return t('Nicht gespeichert: Logo als PNG oder JPEG bis 1 MB, Farbe als #RRGGBB.')
  return t('Fehlgeschlagen (HTTP {status}).', { status: String(e.status) })
}

export function BrandingPanel({ admin }: { admin: boolean }) {
  const [branding, setBranding] = useState<BrandingDTO | null>(null)
  const [companyName, setCompanyName] = useState('')
  const [companyLine, setCompanyLine] = useState('')
  const [legalText, setLegalText] = useState('')
  const [color, setColor] = useState('#1F4E5A')
  const [phone, setPhone] = useState('')
  const [logoUrl, setLogoUrl] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const adopt = useCallback((b: BrandingDTO) => {
    setBranding(b)
    setCompanyName(b.company_name ?? '')
    setCompanyLine(b.company_line ?? '')
    setLegalText(b.legal_text ?? '')
    setColor(b.primary_color)
    setPhone(b.contact_phone ?? '')
  }, [])

  const loadLogo = useCallback(async (has: boolean) => {
    const blob = has ? await api.brandingLogo().catch(() => null) : null
    setLogoUrl((old) => {
      if (old) URL.revokeObjectURL(old)
      return blob ? URL.createObjectURL(blob) : null
    })
  }, [])

  useEffect(() => {
    api
      .branding()
      .then((b) => {
        adopt(b)
        void loadLogo(b.has_logo)
      })
      .catch(() => setError(t('Fehlgeschlagen — keine Antwort vom Server.')))
  }, [adopt, loadLogo])

  async function run(call: () => Promise<BrandingDTO | void>, done: string) {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const next = await call()
      if (next) {
        adopt(next)
        await loadLogo(next.has_logo)
      }
      setNotice(done)
    } catch (e) {
      setError(describe(e))
    }
    setBusy(false)
  }

  const save = () => {
    if (!HEX.test(color)) return setError(t('Farbe bitte als #RRGGBB angeben.'))
    void run(
      () =>
        api.saveBranding({
          company_name: companyName,
          company_line: companyLine,
          legal_text: legalText,
          primary_color: color,
          contact_phone: phone,
        }),
      t('CI gespeichert.'),
    )
  }

  if (branding === null && !error) return null

  return (
    <Panel className="px-6 py-5">
      <p className="text-[13px] text-cockpit-dim">
        {t('So sieht das Kandidatenprofil aus, das Ihr Team aus dem Kandidaten-Dossier als PDF lädt: Logo oben rechts, Ihre Farbe, unten Firmenzeile und AGB-Hinweis.')}
      </p>

      <div className="mt-5 grid gap-5 sm:grid-cols-[220px_1fr]">
        <div>
          <FieldLabel>{t('Logo')}</FieldLabel>
          <div className="flex h-24 items-center justify-center rounded-xl border border-cockpit-line bg-white p-3">
            {logoUrl ? (
              <img src={logoUrl} alt={t('Logo')} className="max-h-full max-w-full object-contain" />
            ) : (
              <span className="text-[12px] text-cockpit-faint">{t('Kein Logo')}</span>
            )}
          </div>
          {admin && (
            <div className="mt-2 flex flex-wrap gap-2">
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  e.target.value = ''
                  if (f) void run(() => api.uploadLogo(f), t('Logo gespeichert.'))
                }}
              />
              <Button onClick={() => fileRef.current?.click()} disabled={busy}>
                <ImageUp className="h-4 w-4" /> {t('Logo hochladen')}
              </Button>
              {branding?.has_logo && (
                <Button
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      await api.deleteLogo()
                      return { ...branding, has_logo: false }
                    }, t('Logo entfernt.'))
                  }
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
          )}
          <p className="mt-2 font-mono text-[11px] text-cockpit-faint">{t('PNG oder JPEG · max. 1 MB')}</p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <TextInput label={t('Firmenname')} value={companyName} onChange={setCompanyName} />
          <div className="grid grid-cols-[1fr_auto] items-end gap-2">
            <TextInput label={t('Primärfarbe')} value={color} onChange={setColor} />
            <input
              type="color"
              aria-label={t('Primärfarbe')}
              value={HEX.test(color) ? color : '#1F4E5A'}
              onChange={(e) => setColor(e.target.value.toUpperCase())}
              disabled={!admin}
              className="h-10 w-12 cursor-pointer rounded-lg border border-cockpit-line bg-cockpit-inset"
            />
          </div>
          <div className="sm:col-span-2">
            <TextInput
              label={t('Fußzeile (Firma · Adresse · Website)')}
              value={companyLine}
              onChange={setCompanyLine}
            />
          </div>
          <TextInput label={t('Telefon im Kontaktfeld (Standard)')} value={phone} onChange={setPhone} />
        </div>
      </div>

      <div className="mt-4">
        <FieldLabel>{t('AGB-Hinweis unter dem Profil')}</FieldLabel>
        <TextArea value={legalText} onChange={setLegalText} rows={5} />
        <p className="mt-1.5 text-[12px] text-cockpit-faint">
          {t('Den Text Ihrer Agentur hier einfügen — Eligo gibt keinen vor.')}
        </p>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        {admin ? (
          <Button tone="primary" onClick={save} disabled={busy}>
            {t('CI speichern')}
          </Button>
        ) : (
          <p className="text-[13px] text-cockpit-dim">
            {t('Nur Administratoren können das CI ändern.')}
          </p>
        )}
        {branding?.updated_by_name && (
          <span className="font-mono text-[11px] text-cockpit-faint">
            {t('Zuletzt geändert von {name}', { name: branding.updated_by_name })}
          </span>
        )}
      </div>
      {(error || notice) && (
        <p className={`mt-3 text-[13px] ${error ? 'text-coral-400' : 'text-mint-300'}`}>{error ?? notice}</p>
      )}
    </Panel>
  )
}
