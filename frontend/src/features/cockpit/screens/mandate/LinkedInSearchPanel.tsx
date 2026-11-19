// "LinkedIn-Suche" and "Ansprache" (ELI-51), side by side.
//
// The left half turns the mandate's own fields into a people search the
// recruiter opens in a new tab — their browser, their LinkedIn account. The
// right half drafts the first message from the same fields, to copy and send
// by hand. Eligo never fetches LinkedIn, stores nothing from it and has no
// send action: this panel builds a URL and a text, and that is all it does.
// The logic lives in `linkedinSearch.ts`; this file is the form around it.

import { t } from '@/i18n'

import { useMemo, useRef, useState } from 'react'
import { Copy, ExternalLink, Plus, X } from 'lucide-react'

import { cn } from '@/lib/cn'
import { useRemembered } from '@/hooks/useRemembered'
import { Panel } from '../../ui/primitives'
import { Button } from '../../ui/forms'
import { PanelHead } from './parts'
import type { Mandate } from '../../data/types'
import {
  CONNECTION_NOTE_LIMIT,
  draftMessage,
  linkedInPeopleSearchUrl,
  searchKeywords,
  sourceLabel,
  suggestTerms,
  xingPeopleSearchUrl,
  type DraftOptions,
  type SearchTerm,
} from './linkedinSearch'

function Toggle<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[]
  value: T
  onChange: (value: T) => void
}) {
  return (
    <div className="inline-flex gap-1 rounded-xl border border-cockpit-line bg-cockpit-inset p-1">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          aria-pressed={value === option.value}
          className={cn(
            'rounded-lg px-3 py-1.5 text-[13px] transition-colors',
            value === option.value
              ? 'bg-white/[0.07] text-cockpit-text'
              : 'text-cockpit-dim hover:text-cockpit-text',
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

const LINK =
  'inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-[13px] font-medium transition-colors'

function SearchHalf({ mandate }: { mandate: Mandate }) {
  const [shut, setShut] = useRemembered('eligo.panel.linkedinSuche.collapsed', false)
  const [terms, setTerms] = useState<SearchTerm[]>(() => suggestTerms(mandate))
  const [own, setOwn] = useState('')
  // A hand edit of the keywords box wins until a chip changes again.
  const [override, setOverride] = useState<string | null>(null)

  const keywords = override ?? searchKeywords(terms)
  const ready = keywords.trim() !== ''

  const change = (next: SearchTerm[]) => {
    setTerms(next)
    setOverride(null)
  }
  const toggle = (key: string) =>
    change(terms.map((term) => (term.key === key ? { ...term, selected: !term.selected } : term)))
  const remove = (key: string) => change(terms.filter((term) => term.key !== key))
  const addOwn = () => {
    const text = own.replace(/\s+/g, ' ').trim()
    if (!text) return
    const key = `own:${text.toLowerCase()}`
    if (!terms.some((term) => term.key === key)) {
      change([...terms, { key, text, source: 'own', selected: true }])
    }
    setOwn('')
  }

  return (
    <Panel className="px-6 py-5">
      <PanelHead
        tag={t('LinkedIn-Suche')}
        tone="lav"
        title={t('Suchbegriffe aus dem Mandat')}
        note={t('{n} von {total} aktiv', {
          n: terms.filter((term) => term.selected).length,
          total: terms.length,
        })}
        collapsed={shut}
        onToggle={() => setShut((s) => !s)}
      />
      {shut ? null : (
        <>
          {terms.length === 0 ? (
            <p className="text-[13px] text-cockpit-faint">
              {t('Das Mandat hat noch keinen Titel, keine Muss-Kriterien und keinen Ort — eigene Begriffe unten eingeben.')}
            </p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {terms.map((term) => (
                <span
                  key={term.key}
                  className={cn(
                    'flex items-center rounded-lg border text-[12.5px] transition-colors',
                    term.selected
                      ? 'border-cockpit-edge bg-white/[0.06] text-cockpit-text'
                      : 'border-cockpit-line text-cockpit-faint',
                  )}
                >
                  <button
                    type="button"
                    onClick={() => toggle(term.key)}
                    aria-pressed={term.selected}
                    title={term.selected ? t('Aus der Suche nehmen') : t('In die Suche aufnehmen')}
                    className="flex items-baseline gap-1.5 px-2.5 py-1"
                  >
                    {term.text}
                    <span className="font-mono text-[10.5px] text-cockpit-faint">
                      {sourceLabel(term.source)}
                    </span>
                  </button>
                  {term.source === 'own' && (
                    <button
                      type="button"
                      onClick={() => remove(term.key)}
                      aria-label={t('Begriff entfernen')}
                      className="pr-2 text-cockpit-faint hover:text-coral-300"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </span>
              ))}
            </div>
          )}

          <form
            className="mt-3 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              addOwn()
            }}
          >
            <input
              value={own}
              onChange={(e) => setOwn(e.target.value)}
              placeholder={t('Eigenen Begriff hinzufügen …')}
              className="min-w-0 flex-1 rounded-lg border border-cockpit-line bg-cockpit-inset px-3 py-2 text-[13px] text-cockpit-text placeholder:text-cockpit-faint focus:border-cockpit-edge focus:outline-none"
            />
            <Button type="submit" disabled={!own.trim()}>
              <Plus className="h-3.5 w-3.5" />
            </Button>
          </form>

          <label className="mt-4 block">
            <span className="font-mono text-[10.5px] uppercase tracking-[0.06em] text-cockpit-faint">
              {t('Suchanfrage')}
            </span>
            <input
              value={keywords}
              onChange={(e) => setOverride(e.target.value)}
              spellCheck={false}
              className="mt-1.5 w-full rounded-lg border border-cockpit-line bg-cockpit-inset px-3 py-2 font-mono text-[12.5px] text-cockpit-text focus:border-cockpit-edge focus:outline-none"
            />
          </label>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <a
              href={ready ? linkedInPeopleSearchUrl(keywords) : undefined}
              target="_blank"
              rel="noopener noreferrer"
              aria-disabled={!ready}
              className={cn(
                LINK,
                ready
                  ? 'border-lav-600 bg-lav-800/30 text-lav-400 hover:border-lav-400'
                  : 'pointer-events-none border-cockpit-line text-cockpit-faint opacity-50',
              )}
            >
              {t('Auf LinkedIn suchen')}
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
            <a
              href={ready ? xingPeopleSearchUrl(keywords) : undefined}
              target="_blank"
              rel="noopener noreferrer"
              aria-disabled={!ready}
              className={cn(
                LINK,
                ready
                  ? 'border-cockpit-line text-cockpit-dim hover:border-cockpit-edge hover:text-cockpit-text'
                  : 'pointer-events-none border-cockpit-line text-cockpit-faint opacity-50',
              )}
            >
              {t('Auf Xing suchen')}
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>

          <p className="mt-3 border-t border-cockpit-line pt-3 text-[12px] leading-relaxed text-cockpit-faint">
            {t('Öffnet die Personensuche in einem neuen Tab — in Ihrem Browser, mit Ihrem eigenen Konto. Eligo ruft LinkedIn nicht ab und speichert nichts von dort.')}
          </p>
        </>
      )}
    </Panel>
  )
}

function MessageHalf({ mandate }: { mandate: Mandate }) {
  const [shut, setShut] = useRemembered('eligo.panel.ansprache.collapsed', false)
  const [form, setForm] = useState<DraftOptions['form']>('Sie')
  const [length, setLength] = useState<DraftOptions['length']>('short')
  // The recruiter's edit of the current draft; a new form or length starts over.
  const [edited, setEdited] = useState<string | null>(null)
  const [copied, setCopied] = useState<'ok' | 'failed' | null>(null)
  const box = useRef<HTMLTextAreaElement>(null)

  const draft = useMemo(() => draftMessage(mandate, { form, length }), [mandate, form, length])
  const text = edited ?? draft
  const over = length === 'short' && text.length > CONNECTION_NOTE_LIMIT

  const restart = () => {
    setEdited(null)
    setCopied(null)
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied('ok')
    } catch {
      // No clipboard permission (or an old browser): leave the text marked
      // so Ctrl+C does it.
      box.current?.select()
      setCopied('failed')
    }
  }

  return (
    <Panel className="px-6 py-5">
      <PanelHead
        tag={t('Ansprache')}
        tone="gold"
        title={t('Nachricht an Kandidaten')}
        note={t('{form}-Form', { form })}
        collapsed={shut}
        onToggle={() => setShut((s) => !s)}
      />
      {shut ? null : (
        <>
          <div className="flex flex-wrap gap-2">
            <Toggle
              options={[
                { value: 'Sie', label: 'Sie' },
                { value: 'Du', label: 'Du' },
              ]}
              value={form}
              onChange={(v) => {
                setForm(v)
                restart()
              }}
            />
            <Toggle
              options={[
                { value: 'short', label: t('Kontaktanfrage') },
                { value: 'long', label: t('Nachricht') },
              ]}
              value={length}
              onChange={(v) => {
                setLength(v)
                restart()
              }}
            />
          </div>

          <textarea
            ref={box}
            value={text}
            onChange={(e) => {
              setEdited(e.target.value)
              setCopied(null)
            }}
            rows={length === 'short' ? 5 : 11}
            className="mt-3 w-full resize-y rounded-xl border border-cockpit-line bg-cockpit-inset px-4 py-3 text-[13.5px] leading-relaxed text-cockpit-text focus:border-cockpit-edge focus:outline-none"
          />

          <div className="mt-2 flex flex-wrap items-center gap-3">
            <Button tone="primary" onClick={() => void copy()}>
              <Copy className="h-3.5 w-3.5" />
              {copied === 'ok' ? t('Kopiert') : t('Kopieren')}
            </Button>
            {edited !== null && (
              <button
                type="button"
                onClick={restart}
                className="font-mono text-[12px] text-cockpit-faint transition-colors hover:text-cockpit-text"
              >
                {t('Entwurf zurücksetzen')}
              </button>
            )}
            <span
              className={cn(
                'ml-auto font-mono text-[11px]',
                over ? 'text-coral-300' : 'text-cockpit-faint',
              )}
            >
              {length === 'short'
                ? t('{n} / {max} Zeichen', { n: text.length, max: CONNECTION_NOTE_LIMIT })
                : t('{n} Zeichen', { n: text.length })}
            </span>
          </div>
          {copied === 'failed' && (
            <p className="mt-2 text-[12px] text-gold-300">
              {t('Kopieren nicht erlaubt — der Text ist markiert, Strg+C kopiert ihn.')}
            </p>
          )}

          <p className="mt-3 border-t border-cockpit-line pt-3 text-[12px] leading-relaxed text-cockpit-faint">
            {t('Entwurf aus dem Mandat. Eligo verschickt nichts — Sie senden die Nachricht persönlich, aus Ihrem eigenen Konto.')}
          </p>
        </>
      )}
    </Panel>
  )
}

export function LinkedInSearchPanel({ mandate }: { mandate: Mandate }) {
  return (
    <div id="section-linkedin" className="grid scroll-mt-24 gap-5 lg:grid-cols-2">
      <SearchHalf mandate={mandate} />
      <MessageHalf mandate={mandate} />
    </div>
  )
}
