import { useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react'
import {
  ShieldCheck,
  Target,
  Layers,
  FileText,
  Check,
  Upload,
  Database,
  MessagesSquare,
  Terminal,
  Lock,
  ChevronDown,
  ArrowRight,
  Users,
} from 'lucide-react'
import './landing.css'
import { getLang, setLang, type Lang as I18nLang } from '@/i18n'

// ── Design tokens ──────────────────────────────────────────────────────────
// The cockpit palette (see tailwind.config.js) expressed for this page's inline
// styles, so the marketing surface and the product read as one system.
//
// Two semantics invert when the ground goes dark:
//   · `navy` was both a dark background and the primary text colour. Backgrounds
//     are now `surface`/`raised`; `navy` keeps only its text role.
//   · "deep" shades get *lighter*, not darker — contrast runs the other way.
const C = {
  // Grounds
  bg: '#0a0b09',
  surface: '#121310',
  raised: '#16170f',
  inset: '#0e0f0c',

  // Text ladder (t1 brightest → t4 faintest)
  navy: '#e8e8e3', // primary text
  t1: '#c9cac3',
  t2: '#9a9b93',
  t3: '#6b6d64',
  t4: '#5b5d55',

  // Mint — the brand accent
  teal: '#86c69a',
  tealDeep: '#a9d6b4', // lighter on dark: this is the "stronger" reading
  tealTint: '#1b2a20', // dark mint wash for chips/tiles
  tealBorder: '#3f6b50',
  onMint: '#0f1a12', // ink that sits on a mint fill

  // Gold — attention / review
  amber: '#e3a75c',
  amberTint: '#2e2312',
  amberText: '#f0c489',

  // Lavender — references / third category
  blue: '#b0a4d8',
  blueTint: '#241f33',

  // Hairlines and fills
  line: 'rgba(255,255,255,0.06)',
  line2: 'rgba(255,255,255,0.10)',
  surf: '#1c1d18',
  surf2: '#121310',
  btnBorder: 'rgba(255,255,255,0.14)',
  panel: '#16170f',
  panelBorder: 'rgba(255,255,255,0.08)',

  // Text on the darkest panels
  onNavy: '#9a9b93',
  onNavy2: '#c9cac3',
  onNavy3: '#a9d6b4',
}

/** Mono stack — matches the cockpit's `--font-mono`. Numbers, labels, chips. */
const MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace"

const container: CSSProperties = { maxWidth: 1200, margin: '0 auto', padding: '0 28px' }

// This page had a working DE/EN switch before the cockpit had one, and its
// own `L(de, en)` pairs are the English this product already shipped. The
// choice lives in `src/i18n` with the rest of the app, so picking English here
// and clicking through to the cockpit does not land you back in German.
type Lang = I18nLang

// Every claim on this page must be one the code backs up — claims.test.ts
// enforces the ones that were not. Product status labels below come from the
// code, not from the roadmap: a stub is "planned", a fixed script is "pilot".
export function LandingPage({ onEnterApp }: { onEnterApp: () => void }) {
  const lang = getLang()
  const [showBanner, setShowBanner] = useState(true)
  const L = (de: string, en: string) => (lang === 'de' ? de : en)

  return (
    <div className="lp">
      {showBanner && <Banner L={L} onClose={() => setShowBanner(false)} onEnterApp={onEnterApp} />}
      <Nav L={L} lang={lang} setLang={setLang} onEnterApp={onEnterApp} />
      <Hero L={L} onEnterApp={onEnterApp} />
      <Intro L={L} />
      <Platform L={L} />
      <HowItWorks L={L} />
      <Workflows L={L} />
      <Controls L={L} />
      <Faq L={L} />
      <FinalCta L={L} onEnterApp={onEnterApp} />
      <Footer L={L} />
    </div>
  )
}

// ── Shared bits ────────────────────────────────────────────────────────────
type Lfn = (de: string, en: string) => string

function scrollToId(id: string) {
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  document.getElementById(id)?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
}

function Logo() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
      <span
        style={{
          width: 30, height: 30, borderRadius: 9, background: C.teal, color: C.onMint,
          fontWeight: 800, fontSize: 16, display: 'grid', placeItems: 'center',
        }}
      >
        e
      </span>
      <span style={{ fontWeight: 700, fontSize: 16, letterSpacing: '-0.3px', color: C.navy }}>
        eligo<span style={{ color: C.tealDeep }}>labs</span>
      </span>
    </div>
  )
}

function Btn({
  variant, children, onClick, icon,
}: { variant: 'teal' | 'dark' | 'ghost'; children: ReactNode; onClick?: () => void; icon?: ReactNode }) {
  const base: CSSProperties = {
    display: 'inline-flex', alignItems: 'center', gap: 8, cursor: 'pointer',
    fontWeight: 700, borderRadius: 12, border: '1px solid transparent',
    fontFamily: 'inherit', transition: 'all .15s ease',
  }
  const styles: Record<string, CSSProperties> = {
    teal: { ...base, background: C.teal, color: C.onMint, fontSize: 14.5, padding: '14px 26px', boxShadow: '0 8px 24px rgba(134,198,154,0.22)' },
    dark: { ...base, background: C.teal, color: C.onMint, fontSize: 13, padding: '9px 17px', borderRadius: 10 },
    ghost: { ...base, background: 'transparent', color: C.navy, fontSize: 14.5, padding: '14px 24px', border: `1px solid ${C.btnBorder}` },
  }
  const cls = variant === 'teal' ? 'lp-btn-teal' : variant === 'dark' ? 'lp-btn-dark' : 'lp-btn-ghost'
  return (
    <button className={cls} style={styles[variant]} onClick={onClick}>
      {children}
      {icon}
    </button>
  )
}

function Eyebrow({ children }: { children: ReactNode }) {
  return (
    // Mono uppercase eyebrows are the cockpit's section-label signature.
    <div style={{ fontFamily: MONO, fontSize: 11.5, fontWeight: 500, color: C.tealDeep, textTransform: 'uppercase', letterSpacing: '1.4px' }}>
      {children}
    </div>
  )
}

function SectionHead({ eyebrow, title, sub, center = false }: { eyebrow: string; title: string; sub?: string; center?: boolean }) {
  return (
    <div style={{ maxWidth: 680, margin: center ? '0 auto' : undefined, textAlign: center ? 'center' : 'left' }}>
      <Eyebrow>{eyebrow}</Eyebrow>
      <h2 className="lp-h2" style={{ fontSize: 38, fontWeight: 800, letterSpacing: '-1px', margin: '12px 0 0' }}>{title}</h2>
      {sub && <p style={{ fontSize: 16, lineHeight: 1.6, color: C.t2, margin: '14px 0 0' }}>{sub}</p>}
    </div>
  )
}

function IconTile({ children, bg = C.tealTint, color = C.tealDeep, size = 42, radius = 12 }: { children: ReactNode; bg?: string; color?: string; size?: number; radius?: number }) {
  return (
    <span style={{ width: size, height: size, minWidth: size, borderRadius: radius, background: bg, color, display: 'grid', placeItems: 'center' }}>
      {children}
    </span>
  )
}

type StatusKind = 'live' | 'pilot' | 'planned'

/** A product's real state. Mint = shipped, gold = pilot, lavender = planned. */
function Status({ kind, L }: { kind: StatusKind; L: Lfn }) {
  const s = {
    live: { fg: C.tealDeep, bg: C.tealTint, label: 'Live' },
    pilot: { fg: C.amberText, bg: C.amberTint, label: 'Pilot' },
    planned: { fg: C.blue, bg: C.blueTint, label: L('Geplant', 'Planned') },
  }[kind]
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: MONO, fontSize: 10.5, fontWeight: 600, color: s.fg, background: s.bg, borderRadius: 20, padding: '3px 9px', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
      <span className={kind === 'live' ? 'lp-pulse' : undefined} style={{ width: 6, height: 6, borderRadius: '50%', background: s.fg }} />
      {s.label}
    </span>
  )
}

function CheckBullet({ lead, text }: { lead: string; text: string }) {
  return (
    <div style={{ display: 'flex', gap: 11, alignItems: 'flex-start' }}>
      <Check size={18} color={C.teal} style={{ marginTop: 2, flexShrink: 0 }} />
      <p style={{ margin: 0, fontSize: 14, lineHeight: 1.5, color: C.t1 }}>
        <b style={{ color: C.navy }}>{lead}</b> — {text}
      </p>
    </div>
  )
}

/** Mockups show invented sample data; say so, on a page that sells evidence. */
function ExampleTag({ L }: { L: Lfn }) {
  return (
    <span style={{ marginLeft: 'auto', fontFamily: MONO, fontSize: 10, color: C.t3, border: `1px dashed ${C.line2}`, borderRadius: 20, padding: '2px 8px', whiteSpace: 'nowrap' }}>
      {L('Beispieldaten', 'Example data')}
    </span>
  )
}

const card: CSSProperties = { background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 18 }

// ── 1. Banner ──────────────────────────────────────────────────────────────
function Banner({ L, onClose, onEnterApp }: { L: Lfn; onClose: () => void; onEnterApp: () => void }) {
  return (
    <div style={{ background: C.surface, color: C.onNavy3, fontSize: 12.5, fontWeight: 600, textAlign: 'center', padding: '9px 44px', position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, flexWrap: 'wrap' }}>
      <span className="lp-pulse" style={{ width: 7, height: 7, borderRadius: '50%', background: C.teal }} />
      {L('Wir suchen Design-Partner unter deutschen Personalagenturen.', 'We are looking for design partners among German recruiting agencies.')}
      <a href="#" onClick={(e) => { e.preventDefault(); onEnterApp() }} style={{ color: C.navy, fontWeight: 700, borderBottom: `1px solid ${C.teal}` }}>
        {L('Gespräch vereinbaren', 'Talk to us')} →
      </a>
      <button aria-label={L('Schließen', 'Close')} onClick={onClose} style={{ position: 'absolute', right: 14, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: C.t3, cursor: 'pointer', fontSize: 16 }}>×</button>
    </div>
  )
}

// ── 2. Nav ─────────────────────────────────────────────────────────────────
function Nav({ L, lang, setLang, onEnterApp }: { L: Lfn; lang: Lang; setLang: (l: Lang) => void; onEnterApp: () => void }) {
  const links: [string, string][] = [
    ['platform', L('Produkt', 'Product')],
    ['how-it-works', L('So funktioniert’s', 'How it works')],
    ['controls', L('Kontrolle', 'Controls')],
    ['faq', 'FAQ'],
  ]
  return (
    <header style={{ position: 'sticky', top: 0, zIndex: 40, background: 'rgba(10,11,9,0.85)', backdropFilter: 'blur(12px)', borderBottom: `1px solid ${C.line}` }}>
      <div style={{ ...container, display: 'flex', alignItems: 'center', height: 62 }}>
        <Logo />
        <nav className="lp-nav-links" style={{ display: 'flex', gap: 6, marginLeft: 28 }}>
          {links.map(([id, label]) => (
            <a key={id} href={`#${id}`} onClick={(e) => { e.preventDefault(); scrollToId(id) }} className="lp-navlink" style={{ fontSize: 13.5, fontWeight: 600, color: C.t1, padding: '7px 12px', borderRadius: 9 }}>
              {label}
            </a>
          ))}
        </nav>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 14 }}>
          <LangToggle lang={lang} setLang={setLang} />
          <a href="#" className="lp-nav-secondary" onClick={(e) => { e.preventDefault(); onEnterApp() }} style={{ fontSize: 13.5, fontWeight: 700, color: C.navy }}>
            {L('Anmelden', 'Log in')}
          </a>
          <Btn variant="dark" onClick={onEnterApp}>{L('Demo buchen', 'Book a demo')}</Btn>
        </div>
      </div>
    </header>
  )
}

function LangToggle({ lang, setLang }: { lang: Lang; setLang: (l: Lang) => void }) {
  return (
    <div style={{ display: 'flex', background: C.surf, border: `1px solid ${C.line2}`, borderRadius: 9, padding: 2 }}>
      {(['de', 'en'] as Lang[]).map((l) => (
        <button
          key={l}
          onClick={() => setLang(l)}
          style={{
            border: 'none', cursor: 'pointer', fontFamily: 'inherit', fontSize: 12.5, fontWeight: 700,
            padding: '5px 11px', borderRadius: 7,
            background: lang === l ? C.raised : 'transparent',
            color: lang === l ? C.navy : C.t3,
          }}
        >
          {l.toUpperCase()}
        </button>
      ))}
    </div>
  )
}

// ── 3. Hero ────────────────────────────────────────────────────────────────
function Hero({ L, onEnterApp }: { L: Lfn; onEnterApp: () => void }) {
  return (
    <section style={{ position: 'relative', background: 'linear-gradient(168deg, #101410 0%, #0d0e0b 55%, #12100c 100%)', overflow: 'hidden' }}>
      <div style={{ position: 'absolute', top: -120, right: -120, width: 520, height: 520, borderRadius: '50%', background: 'radial-gradient(circle, rgba(134,198,154,0.10), transparent 70%)', pointerEvents: 'none' }} />
      <div style={{ ...container, position: 'relative', padding: '74px 28px 96px' }}>
        <div className="lp-hero-grid" style={{ display: 'grid', gridTemplateColumns: '1.05fr 1fr', gap: 52, alignItems: 'center' }}>
          <div>
            {/* Where others put their investor, we put our independence. */}
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10, background: C.tealTint, border: `1px solid ${C.tealBorder}`, borderRadius: 20, padding: '6px 14px', fontFamily: MONO, fontSize: 11.5, fontWeight: 600, color: C.tealDeep, letterSpacing: '0.3px' }}>
              <span>Bootstrapped</span>
              <span style={{ color: C.tealBorder }}>·</span>
              <span>{L('Unabhängig', 'Independent')}</span>
              <span style={{ color: C.tealBorder }}>·</span>
              <span>{L('Gebaut in Deutschland', 'Built in Germany')}</span>
            </span>
            <h1 className="lp-h1" style={{ fontSize: 54, fontWeight: 800, lineHeight: 1.03, letterSpacing: '-1.7px', color: C.navy, margin: '22px 0 0' }}>
              {L('Recruiting, betrieben von Agenten.', 'Recruiting, run by agents.')}
              <br />
              <span style={{ color: C.tealDeep }}>{L('Freigegeben von Ihnen.', 'Approved by you.')}</span>
            </h1>
            <p style={{ fontSize: 17, lineHeight: 1.6, color: C.t1, maxWidth: 520, margin: '20px 0 0' }}>
              {L(
                'Eligo Labs liest Lebensläufe, matcht Kandidaten auf Rollen und prüft jede Agenten-Aussage gegen ihre Quelle, bevor sie in den Datensatz gelangt. Die Einstellungsentscheidung bleibt bei Ihnen.',
                'Eligo Labs reads CVs, matches candidates to roles and checks every agent claim against its source before it reaches the record. The hiring decision stays with you.',
              )}
            </p>
            <div style={{ display: 'flex', gap: 14, margin: '28px 0 0', flexWrap: 'wrap' }}>
              <Btn variant="teal" onClick={onEnterApp}>{L('Demo buchen', 'Book a demo')}</Btn>
              <Btn variant="ghost" icon={<ArrowRight size={16} color={C.tealDeep} />} onClick={() => scrollToId('how-it-works')}>
                {L('So funktioniert’s', 'See how it works')}
              </Btn>
            </div>
            <p style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, lineHeight: 1.5, color: C.t2, maxWidth: 480, margin: '36px 0 0', paddingTop: 20, borderTop: `1px solid ${C.line}` }}>
              <Lock size={16} color={C.tealDeep} style={{ marginTop: 2, flexShrink: 0 }} />
              <span>
                {L(
                  'Keine Investoren, die auf Monetarisierung drängen. Die Daten Ihrer Kandidaten sind unsere Verantwortung — nicht unser Geschäftsmodell.',
                  'No investors pushing us to monetise. Your candidates’ data is our responsibility — not our business model.',
                )}
              </span>
            </p>
          </div>
          <HeroMock L={L} />
        </div>
      </div>
    </section>
  )
}

function HeroMock({ L }: { L: Lfn }) {
  return (
    <div style={{ position: 'relative' }}>
      <div style={{ ...card, boxShadow: '0 26px 64px rgba(0,0,0,0.55)', overflow: 'hidden' }}>
        <div style={{ background: C.inset, padding: '13px 16px', display: 'flex', alignItems: 'center', gap: 10 }}>
          <IconTile size={24} radius={7} bg={C.teal} color={C.onMint}><span style={{ fontSize: 12, fontWeight: 800 }}>e</span></IconTile>
          <span style={{ color: C.navy, fontSize: 12.5, fontWeight: 700 }}>Julia Schmidt</span>
          <span style={{ fontFamily: MONO, fontSize: 10.5, fontWeight: 600, color: C.onNavy3, border: `1px solid ${C.tealBorder}`, borderRadius: 20, padding: '2px 8px' }}>FIT 94</span>
          <span style={{ marginLeft: 'auto', fontFamily: MONO, fontSize: 10.5, color: C.t3 }}>Candidate-360</span>
        </div>
        <div style={{ padding: 16 }}>
          <div style={{ border: `1px solid ${C.line}`, borderRadius: 12, padding: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
              <Layers size={17} color={C.tealDeep} />
              <span style={{ fontSize: 13.5, fontWeight: 800 }}>{L('Belegte Analyse', 'Sourced analysis')}</span>
              <ExampleTag L={L} />
            </div>
            <p style={{ margin: '8px 0 0', fontSize: 12.5, lineHeight: 1.5, color: C.t2 }}>
              {L('Senior Backend-Engineer, 7 Jahre, zuletzt in einem Berliner Fintech. Starke Go/Python-Basis, belegte Skalierungserfahrung.', 'Senior Backend Engineer, 7 years, most recently at a Berlin fintech. Strong Go/Python base, sourced scaling experience.')}
            </p>
          </div>
          <div style={{ display: 'grid', gap: 8, marginTop: 8 }}>
            <EvidenceRow icon={<Check size={14} />} tone="green" title={L('Skalierte Payments auf 4 Mio. Nutzer', 'Scaled payments to 4M users')} sub={L('Lebenslauf · Zeile 214', 'CV · line 214')} tag="CV" />
            <EvidenceRow icon={<span style={{ fontWeight: 800 }}>!</span>} tone="amber" title={L('Beschäftigungslücke ~8 Monate', 'Employment gap ~8 months')} sub={L('2019–2020 · im Gespräch klären', '2019–2020 · clarify in call')} tag={L('PRÜFEN', 'REVIEW')} />
            <EvidenceRow icon={<span style={{ fontWeight: 800 }}>★</span>} tone="blue" title={L('Führte Team von 5 Engineers', 'Led a team of 5 engineers')} sub={L('2 Referenzen · REF + CV', '2 references · REF + CV')} tag="REF" />
          </div>
        </div>
      </div>
      <div className="lp-floaty" style={{ position: 'absolute', left: -18, bottom: -22, background: C.raised, border: `1px solid ${C.line2}`, borderRadius: 14, boxShadow: '0 18px 44px rgba(0,0,0,0.6)', padding: '12px 15px', display: 'flex', alignItems: 'center', gap: 11 }}>
        <IconTile size={30} bg={C.tealTint} color={C.tealDeep}><FileText size={15} /></IconTile>
        <div>
          <div style={{ fontSize: 11, fontWeight: 800 }}>{L('Verifikations-Quittung', 'Verification receipt')}</div>
          <div style={{ fontFamily: MONO, fontSize: 11, color: C.t2 }}>sha256:77c1…be9a</div>
        </div>
      </div>
    </div>
  )
}

function EvidenceRow({ icon, tone, title, sub, tag }: { icon: ReactNode; tone: 'green' | 'amber' | 'blue'; title: string; sub: string; tag: string }) {
  const tones = {
    green: { bg: C.tealTint, fg: C.tealDeep },
    amber: { bg: C.amberTint, fg: C.amberText },
    blue: { bg: C.blueTint, fg: C.blue },
  }[tone]
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 11, border: `1px solid ${C.line}`, borderRadius: 12, padding: '10px 12px' }}>
      <IconTile size={26} radius={8} bg={tones.bg} color={tones.fg}>{icon}</IconTile>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: C.navy }}>{title}</div>
        <div style={{ fontSize: 11.5, color: C.t3 }}>{sub}</div>
      </div>
      <span style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 800, color: tones.fg, background: tones.bg, borderRadius: 6, padding: '3px 7px' }}>{tag}</span>
    </div>
  )
}

// ── 4. Intro — two kinds of context, kept apart ─────────────────────────────
function Intro({ L }: { L: Lfn }) {
  const models = [
    {
      icon: <Database size={20} />, tone: C.blue, bg: C.blueTint,
      title: L('Der öffentliche Markt', 'The public market'),
      body: L(
        'Öffentliche Stellenanzeigen und Unternehmensdaten, täglich per Zeitplan eingelesen — mit Quell-URL, für alle Arbeitsbereiche gleich.',
        'Public job ads and company facts, ingested daily on a schedule — each with its source URL, the same for every workspace.',
      ),
    },
    {
      icon: <Lock size={20} />, tone: C.tealDeep, bg: C.tealTint,
      title: L('Ihr Arbeitsbereich', 'Your workspace'),
      body: L(
        'Ihre Lebensläufe, Mandate, Notizen und ATS-Importe. Strikt mandantengetrennt auf Datenbankebene — kein anderer Kunde sieht sie.',
        'Your CVs, mandates, notes and ATS imports. Strictly tenant-isolated at the database level — no other customer sees them.',
      ),
    },
  ]
  return (
    <section style={{ ...container, padding: '96px 28px 24px' }}>
      <div className="lp-split" style={{ display: 'grid', gridTemplateColumns: '0.9fr 1.1fr', gap: 56, alignItems: 'start' }}>
        <SectionHead
          eyebrow={L('Das Prinzip', 'The idea')}
          title={L('Zwei Arten von Kontext. Sauber getrennt.', 'Two kinds of context. Kept apart.')}
          sub={L(
            'Agenten arbeiten mit dem öffentlichen Markt und Ihren eigenen Daten — aber sie schreiben nichts direkt. Sie schlagen vor, die Verifikation prüft, und die Einstellungsentscheidung trifft Ihr Team.',
            'Agents work with the public market and your own data — but they write nothing directly. They propose, verification checks, and your team makes the hiring decision.',
          )}
        />
        <div style={{ display: 'grid', gap: 14 }}>
          {models.map((m) => (
            <div key={m.title} className="lp-hovercard" style={{ ...card, padding: 22, display: 'flex', gap: 16 }}>
              <IconTile bg={m.bg} color={m.tone}>{m.icon}</IconTile>
              <div>
                <h3 style={{ fontSize: 16, fontWeight: 800, margin: '2px 0 6px' }}>{m.title}</h3>
                <p style={{ fontSize: 13.5, lineHeight: 1.55, color: C.t2, margin: 0 }}>{m.body}</p>
              </div>
            </div>
          ))}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontFamily: MONO, fontSize: 11.5, color: C.t3, padding: '4px 4px 0' }}>
            <Users size={14} color={C.tealDeep} />
            {L('Die Einstellungsentscheidung trifft immer ein Mensch.', 'A person always makes the hiring decision.')}
          </div>
        </div>
      </div>
    </section>
  )
}

// ── 5. Platform — product cards with their real status ─────────────────────
function Platform({ L }: { L: Lfn }) {
  const products: { icon: ReactNode; t: string; b: string; s: StatusKind }[] = [
    { icon: <FileText size={20} />, t: L('Dokumenten-Lesen', 'Document reading'), s: 'live', b: L('Lebensläufe und Gesprächsnotizen werden zu strukturierten Feldern — jedes mit Quelle und Konfidenz.', 'CVs and call transcripts become structured fields — each with its source and confidence.') },
    { icon: <Target size={20} />, t: 'Matching', s: 'live', b: L('Muss-Kriterien in deterministischem Code, dann ein Ranking mit Begründung pro Treffer (heute heuristisch).', 'Must-haves checked in deterministic code, then a ranking with a reason for every hit (heuristic today).') },
    { icon: <ShieldCheck size={20} />, t: L('Verifikation & Quittungen', 'Verification & receipts'), s: 'live', b: L('Jede Agenten-Aussage wird gegen die Quelle geprüft und in einer verketteten Quittung festgehalten.', 'Every agent claim is re-checked against its source and recorded in a hash-chained receipt.') },
    { icon: <Upload size={20} />, t: L('ATS-Import', 'ATS import'), s: 'live', b: L('Bestehende Kandidaten per Datei oder CSV übernehmen. Eligo arbeitet neben Ihrem ATS, nicht statt ihm.', 'Bring existing candidates in by file or CSV. Eligo works alongside your ATS, not instead of it.') },
    { icon: <MessagesSquare size={20} />, t: L('Vorqualifizierung', 'Pre-screen'), s: 'pilot', b: L('Ein strukturiertes Vorgespräch mit Einwilligung des Kandidaten; die Antworten landen belegt im Profil.', 'A structured pre-screen with the candidate’s consent; answers land in the profile with their evidence.') },
    { icon: <Terminal size={20} />, t: L('Aus Claude fragen', 'Ask from Claude'), s: 'planned', b: L('Ihre eigenen Daten aus Claude oder ChatGPT abfragen — über einen MCP-Server, mit denselben Quittungen.', 'Query your own data from Claude or ChatGPT — through an MCP server, with the same receipts.') },
  ]
  return (
    <section id="platform" style={{ ...container, padding: '88px 28px 24px' }}>
      <SectionHead
        center
        eyebrow={L('Plattform', 'Platform')}
        title={L('Eine Plattform. Jeder Teil mit Beleg.', 'One platform. Every part with evidence.')}
        sub={L('Was live ist, steht als live da. Was noch kommt, auch.', 'What is live says live. What is still coming says so too.')}
      />
      <div className="lp-grid-3" style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 16, marginTop: 44 }}>
        {products.map((p) => (
          <div key={p.t} className="lp-hovercard" style={{ ...card, padding: 22, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <IconTile>{p.icon}</IconTile>
              <Status kind={p.s} L={L} />
            </div>
            <h3 style={{ fontSize: 16, fontWeight: 800, margin: '4px 0 0' }}>{p.t}</h3>
            <p style={{ fontSize: 13.5, lineHeight: 1.55, color: C.t2, margin: 0 }}>{p.b}</p>
          </div>
        ))}
      </div>
    </section>
  )
}

// ── 6. How it works — tabbed steps, one large card each ────────────────────
function HowItWorks({ L }: { L: Lfn }) {
  const steps: { n: string; tab: string; s: StatusKind; title: string; body: string; bullets: [string, string][]; mock: ReactNode }[] = [
    {
      n: '01', tab: L('Lesen', 'Read'), s: 'live',
      title: L('Jedes Feld kennt seine Quelle.', 'Every field knows its source.'),
      body: L('Der Extraktions-Agent liest Lebenslauf oder Gesprächsnotiz und schlägt strukturierte Felder vor. Jedes Feld zeigt auf die Stelle im Dokument, aus der es stammt.', 'The extraction agent reads a CV or call transcript and proposes structured fields. Each field points to the place in the document it came from.'),
      bullets: [[L('Quelle & Konfidenz', 'Source & confidence'), L('an jedem Feld.', 'on every field.')], [L('Vorschlag, kein Schreibzugriff', 'A proposal, not a write'), L('der Agent ändert den Datensatz nie direkt.', 'the agent never edits the record directly.')]],
      mock: <ExtractMock L={L} />,
    },
    {
      n: '02', tab: 'Match', s: 'live',
      title: L('Harte Kriterien im Code. Begründung pro Treffer.', 'Hard criteria in code. A reason for every hit.'),
      body: L('Arbeitserlaubnis, Standort, Gehaltsband und Zertifikate prüft deterministischer Code — nicht verhandelbar. Was durchkommt, wird gerankt und in einem Satz begründet.', 'Work permit, location, salary band and certifications are checked by deterministic code — non-negotiable. What passes is ranked and explained in one sentence.'),
      bullets: [[L('Kein Modell entscheidet', 'No model decides'), L('über ein rechtlich hartes Kriterium.', 'a legally hard criterion.')], [L('LLM-Ranking', 'LLM ranking'), L('ist in Arbeit; heute rankt eine transparente Heuristik.', 'is in progress; today a transparent heuristic ranks.')]],
      mock: <MatchMock L={L} />,
    },
    {
      n: '03', tab: L('Prüfen', 'Verify'), s: 'live',
      title: L('Geprüft, bevor es jemand sieht.', 'Checked before anyone sees it.'),
      body: L('Bevor ein Agenten-Vorschlag geschrieben wird, prüft eine Nachbedingung die Aussage erneut gegen die Quelle. Das Ergebnis wird als verkettete Quittung abgelegt; Unsicheres wird zur Prüfung markiert.', 'Before an agent’s proposal is written, a postcondition re-checks the claim against its source. The result is filed as a hash-chained receipt; anything uncertain is flagged for review.'),
      bullets: [[L('Nur anhängend', 'Append-only'), L('Quittungen werden nie überschrieben.', 'receipts are never overwritten.')], [L('Nachprüfbar', 'Checkable'), L('die Kette lässt sich jederzeit verifizieren.', 'the chain can be verified at any time.')]],
      mock: <ReceiptCard L={L} />,
    },
    {
      n: '04', tab: L('Vorqualifizieren', 'Pre-screen'), s: 'pilot',
      title: L('Ein Vorgespräch mit Einwilligung.', 'A pre-screen, with consent.'),
      body: L('Kandidaten beantworten ein strukturiertes Vorgespräch, nachdem sie eingewilligt haben. Die Antworten werden gelesen, belegt und Ihrem Team vorgelegt — nicht automatisch bewertet.', 'Candidates answer a structured pre-screen after giving consent. Answers are read, sourced and put in front of your team — not scored automatically.'),
      bullets: [[L('Einwilligung zuerst', 'Consent first'), L('kein Gespräch ohne Zustimmung.', 'no conversation without it.')], [L('Pilot', 'Pilot'), L('festes Skript, Erweiterung mit Design-Partnern.', 'fixed script, extended with design partners.')]],
      mock: <PrescreenMock L={L} />,
    },
    {
      n: '05', tab: L('Aus Claude fragen', 'Ask from Claude'), s: 'planned',
      title: L('Ihre Daten, aus Ihrem Assistenten.', 'Your data, from your assistant.'),
      body: L('Geplant: ein MCP-Server, über den Recruiter ihre eigenen Daten aus Claude oder ChatGPT abfragen — mit denselben Mandantengrenzen und Quittungen wie in der App.', 'Planned: an MCP server so recruiters can query their own data from Claude or ChatGPT — with the same tenant boundaries and receipts as the app.'),
      bullets: [[L('Gleiche Regeln', 'Same rules'), L('Mandantentrennung gilt auch hier.', 'tenant isolation applies here too.')], [L('Noch nicht verfügbar', 'Not available yet'), L('Entwurf der Oberfläche.', 'a preview of the design.')]],
      mock: <ClaudeMock L={L} />,
    },
  ]
  const [active, setActive] = useState(0)
  const step = steps[active]
  // WAI-ARIA tabs: one tab in the tab order, arrows/Home/End move between them.
  const onTabKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    const last = steps.length - 1
    const next = { ArrowRight: active === last ? 0 : active + 1, ArrowLeft: active === 0 ? last : active - 1, Home: 0, End: last }[e.key]
    if (next === undefined) return
    e.preventDefault()
    setActive(next)
    document.getElementById(`lp-tab-${steps[next].n}`)?.focus()
  }
  return (
    <section id="how-it-works" style={{ ...container, padding: '96px 28px 24px' }}>
      <SectionHead
        center
        eyebrow={L('So funktioniert’s', 'How it works')}
        title={L('Vom Dokument zur Entscheidung — jeder Schritt belegt.', 'From document to decision — every step sourced.')}
      />
      <div role="tablist" aria-label={L('Schritte', 'Steps')} className="lp-tabs" style={{ display: 'flex', gap: 6, justifyContent: 'center', margin: '36px auto 0', padding: 5, background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 14, width: 'fit-content', maxWidth: '100%' }}>
        {steps.map((s, i) => (
          <button
            key={s.n}
            role="tab"
            id={`lp-tab-${s.n}`}
            aria-selected={i === active}
            aria-controls="lp-step-panel"
            tabIndex={i === active ? 0 : -1}
            onKeyDown={onTabKey}
            onClick={() => setActive(i)}
            className="lp-tab"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 8, whiteSpace: 'nowrap',
              border: 'none', cursor: 'pointer', fontFamily: 'inherit', fontSize: 13.5, fontWeight: 700,
              padding: '9px 15px', borderRadius: 10,
              background: i === active ? C.tealTint : 'transparent',
              color: i === active ? C.navy : C.t2,
              boxShadow: i === active ? `inset 0 0 0 1px ${C.tealBorder}` : 'none',
            }}
          >
            <span style={{ fontFamily: MONO, fontSize: 11, color: i === active ? C.tealDeep : C.t3 }}>{s.n}</span>
            {s.tab}
          </button>
        ))}
      </div>
      <div key={step.n} role="tabpanel" id="lp-step-panel" aria-labelledby={`lp-tab-${step.n}`} tabIndex={0} className="lp-fadein lp-split" style={{ ...card, marginTop: 20, padding: 36, display: 'grid', gridTemplateColumns: '1fr 1.05fr', gap: 44, alignItems: 'center' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontFamily: MONO, fontSize: 40, fontWeight: 600, color: C.tealBorder, letterSpacing: '-1px', lineHeight: 1 }}>{step.n}</span>
            <Status kind={step.s} L={L} />
          </div>
          <h3 style={{ fontSize: 28, fontWeight: 800, letterSpacing: '-0.6px', lineHeight: 1.15, margin: '18px 0 0' }}>{step.title}</h3>
          <p style={{ fontSize: 15, lineHeight: 1.6, color: C.t2, margin: '14px 0 22px' }}>{step.body}</p>
          <div style={{ display: 'grid', gap: 12 }}>
            {step.bullets.map(([lead, text]) => <CheckBullet key={lead} lead={lead} text={text} />)}
          </div>
        </div>
        <div style={{ background: C.inset, border: `1px solid ${C.line}`, borderRadius: 16, padding: 18 }}>{step.mock}</div>
      </div>
    </section>
  )
}

function MockHead({ icon, title, right }: { icon: ReactNode; title: string; right?: ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 12 }}>
      {icon}
      <span style={{ fontSize: 14, fontWeight: 800 }}>{title}</span>
      {right && <span style={{ marginLeft: 'auto' }}>{right}</span>}
    </div>
  )
}

function ExtractMock({ L }: { L: Lfn }) {
  const fields = [
    [L('Aktuelle Rolle', 'Current role'), 'Senior Backend Engineer', 'CV · p1', '0.97'],
    [L('Erfahrung', 'Experience'), L('7 Jahre', '7 years'), 'CV · p1–2', '0.93'],
    [L('Standort', 'Location'), 'Berlin', 'CV · p1', '0.99'],
    [L('Gehaltswunsch', 'Salary expectation'), '85–95k €', L('Notiz · 12.10.', 'Call note · 12 Oct'), '0.88'],
    [L('Arbeitserlaubnis', 'Work permit'), 'EU', 'CV · p1', '0.95'],
  ]
  return (
    <div style={{ ...card, background: C.raised, padding: 16 }}>
      <MockHead icon={<FileText size={16} color={C.tealDeep} />} title={L('Extrahierte Felder', 'Extracted fields')} right={<ExampleTag L={L} />} />
      <div style={{ display: 'grid', gap: 6 }}>
        {fields.map(([k, v, src, conf]) => (
          <div key={k} className="lp-field" style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr auto', gap: 10, alignItems: 'center', border: `1px solid ${C.line}`, borderRadius: 10, padding: '9px 12px', fontSize: 12.5 }}>
            <span style={{ color: C.t3 }}>{k}</span>
            <span style={{ color: C.navy, fontWeight: 700 }}>{v}</span>
            <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.tealDeep, background: C.tealTint, borderRadius: 6, padding: '2px 7px', whiteSpace: 'nowrap' }}>{src} · {conf}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function MatchMock({ L }: { L: Lfn }) {
  const filters = [L('Arbeitserlaubnis', 'Work permit'), L('Standort ≤ 50 km', 'Location ≤ 50 km'), L('Gehaltsband', 'Salary band')]
  const rows = [
    ['94', C.teal, L('Fintech · Berlin', 'Fintech · Berlin'), 'Senior Backend · Go/Python', L('Skalierung auf Mio.-Nutzer belegt.', 'Scaling to millions of users sourced.')],
    ['88', C.blue, L('Payments · München', 'Payments · Munich'), 'Platform Engineer', L('Passendes Domänenwissen.', 'Matching domain.')],
    ['81', C.amber, L('Logistik-SaaS · Hamburg', 'Logistics SaaS · Hamburg'), 'Backend Engineer', L('Starke Basis, weniger Seniorität.', 'Strong base, less seniority.')],
  ] as const
  return (
    <div style={{ ...card, background: C.raised, padding: 16 }}>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
        {filters.map((f) => (
          <span key={f} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontFamily: MONO, fontSize: 10.5, color: C.tealDeep, border: `1px solid ${C.tealBorder}`, borderRadius: 20, padding: '3px 9px' }}>
            <Check size={11} /> {f}
          </span>
        ))}
        <ExampleTag L={L} />
      </div>
      <div style={{ display: 'grid', gap: 8 }}>
        {rows.map(([score, color, company, role, why]) => (
          <div key={company} style={{ display: 'flex', gap: 14, alignItems: 'center', border: `1px solid ${C.line}`, borderRadius: 12, padding: '11px 13px' }}>
            <div style={{ width: 40, textAlign: 'center' }}>
              <div style={{ fontSize: 19, fontWeight: 800, color, fontFamily: MONO }}>{score}</div>
              <div style={{ fontSize: 8.5, fontWeight: 800, color: C.t3, letterSpacing: '0.5px', fontFamily: MONO }}>FIT</div>
            </div>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: C.navy }}>{company}</div>
              <div style={{ fontSize: 11.5, color: C.t3 }}>{role}</div>
            </div>
            <span className="lp-why" style={{ maxWidth: 160, fontSize: 9.5, fontWeight: 700, color: C.tealDeep, background: C.tealTint, borderRadius: 6, padding: '4px 8px', lineHeight: 1.35 }}>
              {L('WARUM', 'WHY')} · {why}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function ReceiptCard({ L }: { L: Lfn }) {
  const steps = [
    ['1', L('GELESEN', 'READ'), L('Lebenslauf.pdf, Abschnitt „Payments“.', 'CV.pdf, section “Payments”.'), false],
    ['2', L('BEHAUPTET', 'ASSERTED'), L('Skaliertes Zahlungssystem auf 4 Mio. Nutzer.', 'Scaled payment system to 4M users.'), false],
    ['3', L('VERIFIZIERT', 'VERIFIED'), L('Kennzahl im Quelltext belegt (Zeile 214).', 'Figure found in the source text (line 214).'), true],
    ['4', L('GESCHRIEBEN', 'WRITTEN'), L('Als Stärke markiert, Beleg verlinkt.', 'Marked as a strength, evidence linked.'), true],
  ] as const
  return (
    <div style={{ ...card, background: C.raised, padding: 16 }}>
      <MockHead
        icon={<IconTile size={30} bg={C.tealTint} color={C.tealDeep}><FileText size={15} /></IconTile>}
        title={L('Verifikations-Quittung', 'Verification receipt')}
        right={<span style={{ display: 'flex', gap: 6, alignItems: 'center' }}><ExampleTag L={L} /><span style={{ fontSize: 11, fontWeight: 700, color: C.tealDeep, background: C.tealTint, borderRadius: 20, padding: '4px 10px' }}>✓ {L('Verifiziert', 'Verified')}</span></span>}
      />
      <div style={{ display: 'grid', gap: 4, margin: '6px 0 14px' }}>
        {steps.map(([n, title, body, done]) => (
          <div key={n} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
            <span style={{ width: 22, height: 22, borderRadius: 7, background: done ? C.tealTint : C.surf, color: done ? C.tealDeep : C.t2, fontSize: 11, fontWeight: 800, display: 'grid', placeItems: 'center', flexShrink: 0 }}>{n}</span>
            <div style={{ paddingBottom: 6 }}>
              <div style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: '0.4px', color: done ? C.tealDeep : C.t2 }}>{title}</div>
              <div style={{ fontSize: 13, color: C.navy, marginTop: 1 }}>{body}</div>
            </div>
          </div>
        ))}
      </div>
      <div style={{ background: C.inset, borderRadius: 10, padding: '11px 13px', display: 'grid', gap: 7 }}>
        {[
          [L('Quelle', 'Source'), L('Lebenslauf.pdf', 'CV.pdf')],
          [L('Konfidenz', 'Confidence'), '0.91'],
          [L('Vorgänger', 'Previous'), 'sha256:3a90…c41d'],
          ['Hash', 'sha256:77c1…be9a'],
        ].map(([k, v]) => (
          <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5 }}>
            <span style={{ color: C.t2 }}>{k}</span>
            <span style={{ fontFamily: MONO, fontWeight: 600, color: C.navy }}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function PrescreenMock({ L }: { L: Lfn }) {
  const qa = [
    [L('Ab wann wären Sie verfügbar?', 'When could you start?'), L('Ab 1. Februar, drei Monate Kündigungsfrist.', 'From 1 February, three months’ notice.')],
    [L('Wie viel Remote-Anteil erwarten Sie?', 'How much remote work do you expect?'), L('Zwei Tage im Büro sind in Ordnung.', 'Two days in the office is fine.')],
  ]
  return (
    <div style={{ ...card, background: C.raised, padding: 16 }}>
      <MockHead icon={<MessagesSquare size={16} color={C.amberText} />} title={L('Vorgespräch', 'Pre-screen')} right={<span style={{ display: 'flex', gap: 8, alignItems: 'center' }}><span style={{ fontFamily: MONO, fontSize: 10.5, color: C.tealDeep }}>✓ {L('Einwilligung', 'Consent')}</span><ExampleTag L={L} /></span>} />
      <div style={{ display: 'grid', gap: 10 }}>
        {qa.map(([q, a]) => (
          <div key={q} style={{ display: 'grid', gap: 6 }}>
            <div style={{ fontSize: 12.5, color: C.t2, background: C.surf, borderRadius: '12px 12px 12px 4px', padding: '9px 12px', width: 'fit-content', maxWidth: '85%' }}>{q}</div>
            <div style={{ fontSize: 12.5, color: C.navy, background: C.tealTint, borderRadius: '12px 12px 4px 12px', padding: '9px 12px', width: 'fit-content', maxWidth: '85%', justifySelf: 'end' }}>{a}</div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8, fontSize: 11.5, color: C.amberText, background: C.amberTint, borderRadius: 10, padding: '8px 11px' }}>
        <span style={{ fontWeight: 800 }}>!</span>
        {L('Zur Prüfung durch Ihr Team — keine automatische Bewertung.', 'For your team to review — not scored automatically.')}
      </div>
    </div>
  )
}

function ClaudeMock({ L }: { L: Lfn }) {
  return (
    <div style={{ ...card, background: C.raised, padding: 0, overflow: 'hidden', fontFamily: MONO }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '10px 14px', background: C.inset, borderBottom: `1px solid ${C.line}` }}>
        {[C.t4, C.t4, C.t4].map((c, i) => <span key={i} style={{ width: 9, height: 9, borderRadius: '50%', background: c }} />)}
        <span style={{ marginLeft: 8, fontSize: 10.5, color: C.t3 }}>{L('Entwurf · noch nicht verfügbar', 'Design preview · not available yet')}</span>
      </div>
      <div style={{ padding: 16, fontSize: 12, lineHeight: 1.7 }}>
        <div style={{ color: C.t3 }}>&gt; {L('Welche Kandidaten im Mandat „Backend Berlin“ haben eine offene Prüfung?', 'Which candidates in the “Backend Berlin” mandate have an open review?')}</div>
        <div style={{ color: C.t1, marginTop: 10 }}>{L('2 Kandidaten:', '2 candidates:')}</div>
        <div style={{ color: C.navy }}>· Julia Schmidt — <span style={{ color: C.amberText }}>{L('Lücke 2019–2020', 'gap 2019–2020')}</span></div>
        <div style={{ color: C.navy }}>· Tomás Ruiz — <span style={{ color: C.amberText }}>{L('Gehalt aus Notiz, Konfidenz 0.62', 'salary from note, confidence 0.62')}</span></div>
        <div style={{ color: C.tealDeep, marginTop: 10 }}>✓ {L('Quittung', 'receipt')} RCPT-9031 · {L('nur Ihr Arbeitsbereich', 'your workspace only')}</div>
      </div>
    </div>
  )
}

// ── 7. Illustrative workflows ──────────────────────────────────────────────
function Workflows({ L }: { L: Lfn }) {
  const flows = [
    {
      tag: L('Mandat', 'Mandate'),
      title: L('Vom Briefing zur Shortlist', 'From intake call to shortlist'),
      steps: [
        L('Sie legen die Muss-Kriterien im Mandat fest: Arbeitserlaubnis, Standort, Gehaltsband.', 'You set the must-haves on the mandate: work permit, location, salary band.'),
        L('Deterministischer Code filtert jeden Kandidaten heraus, der eines verfehlt.', 'Deterministic code filters out every candidate who misses one.'),
        L('Der Rest wird gerankt, jeder mit einer Begründung in einem Satz.', 'The rest are ranked, each with a one-line reason.'),
      ],
    },
    {
      tag: L('Verifikation', 'Verification'),
      title: L('Eine Aussage, die nicht stimmte', 'A claim that didn’t check out'),
      steps: [
        L('Ein Agent schlägt „10 Jahre Führungserfahrung" vor.', 'An agent proposes “10 years of leadership”.'),
        L('Die Nachbedingung findet im Lebenslauf nur 4 Jahre.', 'The postcondition finds only 4 years in the CV.'),
        L('Nichts wird geschrieben; die Aussage wird zur Prüfung markiert.', 'Nothing is written; the claim is flagged for review.'),
      ],
    },
    {
      tag: L('Markt', 'Market'),
      title: L('Neue öffentliche Stellen über Nacht', 'New public roles, overnight'),
      steps: [
        L('Der nächtliche Lauf liest öffentliche Stellenanzeigen ein.', 'The nightly run ingests public job ads.'),
        L('Jede Anzeige behält ihre Quell-URL.', 'Every ad keeps its source URL.'),
        L('Morgens sind die neuen Rollen mit Quelle im Hub durchsuchbar.', 'In the morning the new roles are searchable in the hub, with their source.'),
      ],
    },
  ]
  return (
    <section id="workflows" style={{ ...container, padding: '96px 28px 24px' }}>
      <SectionHead
        eyebrow={L('Abläufe', 'Workflows')}
        title={L('So sieht ein Tag mit Eligo aus.', 'What a day with Eligo looks like.')}
        sub={L('Veranschaulichende Beispiele — kein Kundenergebnis.', 'Illustrative examples — not a customer result.')}
      />
      <div className="lp-grid-3" style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 16, marginTop: 36 }}>
        {flows.map((f) => (
          <div key={f.title} className="lp-hovercard" style={{ ...card, padding: 24 }}>
            <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.t3, textTransform: 'uppercase', letterSpacing: '1px' }}>{f.tag} · {L('Beispiel', 'Example')}</span>
            <h3 style={{ fontSize: 17, fontWeight: 800, margin: '10px 0 16px' }}>{f.title}</h3>
            <ol style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: 12 }}>
              {f.steps.map((s, i) => (
                <li key={s} style={{ display: 'flex', gap: 12, fontSize: 13.5, lineHeight: 1.5, color: C.t1 }}>
                  <span style={{ fontFamily: MONO, fontSize: 11, color: C.tealDeep, background: C.tealTint, borderRadius: 6, width: 22, height: 22, display: 'grid', placeItems: 'center', flexShrink: 0 }}>{i + 1}</span>
                  {s}
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
    </section>
  )
}

// ── 8. Systems & controls ──────────────────────────────────────────────────
function Controls({ L }: { L: Lfn }) {
  const controls: [string, string][] = [
    [L('Herkunft & Quittungen', 'Provenance & receipts'), L('Quelle und Konfidenz an jedem extrahierten Feld.', 'Source and confidence on every extracted field.')],
    [L('KI-VO · menschliche Aufsicht', 'AI Act · human oversight'), L('Agenten schlagen vor; Unsicheres wird zur Prüfung markiert.', 'Agents propose; uncertain claims are flagged for review.')],
    [L('Mandantentrennung', 'Tenant isolation'), L('Row-Level-Security in der Datenbank, standardmäßig geschlossen.', 'Row-level security in the database, closed by default.')],
    [L('Nur anhängendes Protokoll', 'Append-only log'), L('Jede Agenten-Aktion als verkettete Quittung.', 'Every agent action as a hash-chained receipt.')],
    [L('Harte Kriterien im Code', 'Hard criteria in code'), L('Kein Modell entscheidet über Arbeitserlaubnis oder Gehalt.', 'No model decides work permit or salary.')],
    [L('Neben Ihrem ATS', 'Alongside your ATS'), L('Import statt Ablösung — Ihr System bleibt führend.', 'Import, not replace — your system stays in charge.')],
  ]
  return (
    <section id="controls" style={{ ...container, padding: '96px 28px 24px' }}>
      <div className="lp-controls-card" style={{ position: 'relative', ...card, borderRadius: 22, padding: '44px 46px', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', top: -100, right: -80, width: 380, height: 380, borderRadius: '50%', background: 'radial-gradient(circle, rgba(134,198,154,0.12), transparent 70%)', pointerEvents: 'none' }} />
        <div className="lp-compliance-grid" style={{ position: 'relative', display: 'grid', gridTemplateColumns: '0.85fr 1.15fr', gap: 40, alignItems: 'center' }}>
          <SectionHead
            eyebrow={L('Systeme & Kontrolle', 'Systems & controls')}
            title={L('Für die europäische Realität gebaut.', 'Built for the European reality.')}
            sub={L('Die Verifikations- und Quittungs-Schicht bildet fast 1:1 ab, was ein Hochrisiko-KI-System im Recruiting ohnehin haben muss.', 'The verification and receipt layer maps almost one-to-one onto what a high-risk hiring AI system must have anyway.')}
          />
          <div className="lp-chip-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            {controls.map(([t, b]) => (
              <div key={t} style={{ background: C.panel, border: `1px solid ${C.panelBorder}`, borderRadius: 12, padding: '14px 15px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ width: 7, height: 7, borderRadius: '50%', background: C.teal, flexShrink: 0 }} />
                  <span style={{ fontSize: 13, fontWeight: 800, color: C.navy }}>{t}</span>
                </div>
                <p style={{ fontSize: 12, lineHeight: 1.5, color: C.t2, margin: '6px 0 0 15px' }}>{b}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

// ── 9. FAQ ─────────────────────────────────────────────────────────────────
function Faq({ L }: { L: Lfn }) {
  const qa: [string, string][] = [
    [L('Ersetzt Eligo mein ATS?', 'Does Eligo replace my ATS?'), L('Nein. Sie importieren Ihre Kandidaten per Datei oder CSV; Eligo liest, matcht und prüft daneben.', 'No. You import candidates by file or CSV; Eligo reads, matches and checks alongside it.')],
    [L('Wer trifft die Einstellungsentscheidung?', 'Who makes the hiring decision?'), L('Immer ein Mensch. Agenten schlagen nur vor, und rechtlich harte Kriterien prüft deterministischer Code, kein Modell.', 'Always a person. Agents only propose, and legally hard criteria are checked by deterministic code, not a model.')],
    [L('Was heißt „jede Aussage belegt“?', 'What does “every claim sourced” mean?'), L('Bevor eine Agenten-Aussage im Datensatz landet, wird sie gegen die Quelle geprüft und als Quittung abgelegt. Unsicheres wird zur Prüfung markiert statt geschrieben.', 'Before an agent claim reaches the record, it is checked against its source and filed as a receipt. Anything uncertain is flagged for review instead of written.')],
    [L('Wie steht Eligo zur DSGVO?', 'Where does Eligo stand on GDPR?'), L('Wir nennen Eligo noch nicht konform. Gebaut sind Herkunft an jedem Feld, nur anhängende Quittungen und Mandantentrennung in der Datenbank; die offenen Punkte gehen wir mit Ihnen im Gespräch durch.', 'We don’t call Eligo compliant yet. What is built: provenance on every field, append-only receipts and tenant isolation in the database. We will walk you through the open items on a call.')],
    [L('Warum bootstrapped?', 'Why bootstrapped?'), L('Weil Ihre Kandidatendaten nicht unser Produkt sind. Ohne Investorendruck bauen wir in dem Tempo, das Verifikation braucht — und verdienen an der Software, nie an Daten.', 'Because your candidates’ data is not our product. Without investor pressure we build at the pace verification needs — and we make money from the software, never from data.')],
  ]
  return (
    <section id="faq" style={{ ...container, maxWidth: 880, padding: '96px 28px 40px' }}>
      <SectionHead center eyebrow="FAQ" title={L('Fragen, die Kunden zuerst stellen.', 'Questions buyers ask first.')} />
      <div style={{ marginTop: 36, display: 'grid', gap: 10 }}>
        {qa.map(([q, a]) => (
          <details key={q} className="lp-faq" style={{ ...card, borderRadius: 14, padding: '0 20px' }}>
            <summary style={{ display: 'flex', alignItems: 'center', gap: 12, cursor: 'pointer', padding: '18px 0', fontSize: 15, fontWeight: 700, color: C.navy, listStyle: 'none' }}>
              {q}
              <ChevronDown size={18} color={C.t3} className="lp-faq-chev" style={{ marginLeft: 'auto', flexShrink: 0 }} />
            </summary>
            <p style={{ margin: 0, padding: '0 0 18px', fontSize: 14, lineHeight: 1.6, color: C.t2 }}>{a}</p>
          </details>
        ))}
      </div>
    </section>
  )
}

// ── 10. Final CTA ──────────────────────────────────────────────────────────
function FinalCta({ L, onEnterApp }: { L: Lfn; onEnterApp: () => void }) {
  return (
    <section style={{ background: 'linear-gradient(168deg,#101410,#12100c)', marginTop: 56 }}>
      <div style={{ ...container, padding: '80px 28px', textAlign: 'center' }}>
        <h2 className="lp-h2" style={{ fontSize: 42, fontWeight: 800, letterSpacing: '-1.2px', maxWidth: 640, margin: '0 auto' }}>
          {L('Geben Sie den Agenten die Arbeit. Behalten Sie die Entscheidung.', 'Give the agents the work. Keep the decision.')}
        </h2>
        <p style={{ fontSize: 16.5, color: C.t1, maxWidth: 520, margin: '16px auto 28px' }}>
          {L('Sprechen Sie direkt mit den Leuten, die Eligo bauen.', 'Talk directly to the people who build Eligo.')}
        </p>
        <div style={{ display: 'flex', gap: 14, justifyContent: 'center', flexWrap: 'wrap' }}>
          <Btn variant="teal" onClick={onEnterApp}>{L('Demo buchen', 'Book a demo')}</Btn>
          <Btn variant="ghost" onClick={onEnterApp}>{L('Anmelden', 'Log in')}</Btn>
        </div>
        <p style={{ fontFamily: MONO, fontSize: 11.5, color: C.t3, marginTop: 24, letterSpacing: '0.3px' }}>
          Bootstrapped · {L('Unabhängig', 'Independent')} · {L('Gebaut in Deutschland', 'Built in Germany')}
        </p>
      </div>
    </section>
  )
}

// ── 11. Footer ─────────────────────────────────────────────────────────────
function Footer({ L }: { L: Lfn }) {
  // A link with a destination and one without are different promises. In
  // Germany "Impressum" and "Datenschutz" must resolve, and Google will not let
  // an OAuth app leave testing without a privacy policy it can fetch. Product
  // links scroll to their section. No About/Blog/Careers until those pages exist.
  const cols: [string, { label: string; href?: string; id?: string }[]][] = [
    [
      L('Produkt', 'Product'),
      [
        { label: L('Plattform', 'Platform'), id: 'platform' },
        { label: L('So funktioniert’s', 'How it works'), id: 'how-it-works' },
        { label: L('Kontrolle', 'Controls'), id: 'controls' },
        { label: 'FAQ', id: 'faq' },
      ],
    ],
    [
      L('Rechtliches', 'Legal'),
      [
        { label: L('Impressum', 'Imprint'), href: '/impressum/' },
        { label: L('Datenschutz', 'Privacy'), href: '/datenschutz/' },
      ],
    ],
  ]
  return (
    <footer style={{ background: C.surface, color: C.onNavy }}>
      <div style={{ ...container, padding: '52px 28px 34px' }}>
        <div className="lp-footer-grid" style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr 1fr', gap: 36 }}>
          <div>
            <Logo />
            <p style={{ fontSize: 12.5, lineHeight: 1.6, color: C.onNavy, maxWidth: 260, marginTop: 14 }}>
              {L('KI-native Recruiting-Plattform. Schmale Agenten, belegte Aussagen, Einstellungsentscheidungen beim Menschen.', 'AI-native recruiting platform. Narrow agents, sourced claims, hiring decisions kept human.')}
            </p>
          </div>
          {cols.map(([h, items]) => (
            <div key={h}>
              <div style={{ fontSize: 11, fontWeight: 800, color: C.navy, textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: 14 }}>{h}</div>
              <div style={{ display: 'grid', gap: 9 }}>
                {items.map(({ label, href, id }) => (
                  <a
                    key={label}
                    href={id ? `#${id}` : href}
                    onClick={id ? (e) => { e.preventDefault(); scrollToId(id) } : undefined}
                    className="lp-footlink"
                    style={{ fontSize: 12.5, color: C.onNavy }}
                  >
                    {label}
                  </a>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div style={{ borderTop: `1px solid ${C.line2}` }}>
        <div style={{ ...container, padding: '18px 28px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11.5, flexWrap: 'wrap', gap: 10 }}>
          <span>© 2026 Eligo Labs. {L('Alle Rechte vorbehalten.', 'All rights reserved.')}</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: C.teal }} />
            Bootstrapped · {L('Gebaut in Deutschland', 'Built in Germany')}
          </span>
        </div>
      </div>
    </footer>
  )
}
