import { useState, type CSSProperties, type ReactNode } from 'react'
import {
  Sparkles,
  CirclePlay,
  Search,
  Plus,
  ShieldCheck,
  Target,
  Layers,
  FileText,
  Check,
  Quote,
} from 'lucide-react'
import './landing.css'

// ── Design tokens (from the handoff) ───────────────────────────────────────
const C = {
  navy: '#0F1B2A',
  navyHover: '#1d3350',
  teal: '#0E9F86',
  tealDeep: '#0B7D6A',
  tealTint: '#E4F5F0',
  tealBorder: '#b9e3d8',
  blue: '#0B8FB0',
  blueTint: '#E4F1F9',
  amber: '#E8A13B',
  amberTint: '#FBEEDC',
  amberText: '#C2410C',
  t1: '#3C4A57',
  t2: '#5E6E7C',
  t3: '#8494A2',
  t4: '#9AA7B2',
  line: '#EEF2F5',
  line2: '#E4E9EE',
  surf: '#F0F3F6',
  surf2: '#F7F9FB',
  btnBorder: '#D3D9DF',
  panel: '#16232f',
  panelBorder: '#24384a',
  onNavy: '#8DA0B0',
  onNavy2: '#AEBAC6',
  onNavy3: '#CFE7E1',
}

const container: CSSProperties = { maxWidth: 1200, margin: '0 auto', padding: '0 28px' }

type Lang = 'de' | 'en'

export function LandingPage({ onEnterApp }: { onEnterApp: () => void }) {
  const [lang, setLang] = useState<Lang>('de')
  const [showBanner, setShowBanner] = useState(true)
  const L = (de: string, en: string) => (lang === 'de' ? de : en)

  return (
    <div className="lp">
      {showBanner && <Banner L={L} onClose={() => setShowBanner(false)} />}
      <Nav L={L} lang={lang} setLang={setLang} onEnterApp={onEnterApp} />
      <Hero L={L} onEnterApp={onEnterApp} />
      <Stats L={L} />
      <Agents L={L} />
      <ReceiptSplit L={L} />
      <MatchingSplit L={L} />
      <Compliance L={L} />
      <Testimonial L={L} />
      <FinalCta L={L} onEnterApp={onEnterApp} />
      <Footer L={L} />
    </div>
  )
}

// ── Shared bits ────────────────────────────────────────────────────────────
type Lfn = (de: string, en: string) => string

function Logo({ onNavy = false }: { onNavy?: boolean }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
      <span
        style={{
          width: 30, height: 30, borderRadius: 9, background: C.teal, color: '#fff',
          fontWeight: 800, fontSize: 16, display: 'grid', placeItems: 'center',
        }}
      >
        e
      </span>
      <span style={{ fontWeight: 700, fontSize: 16, letterSpacing: '-0.3px', color: onNavy ? '#fff' : C.navy }}>
        eligo
      </span>
      <span
        style={{
          fontSize: 9.5, fontWeight: 700, color: C.tealDeep, background: C.tealTint,
          border: `1px solid ${C.tealBorder}`, borderRadius: 20, padding: '2px 7px',
        }}
      >
        AI
      </span>
    </div>
  )
}

function Btn({
  variant, children, onClick, icon,
}: { variant: 'teal' | 'dark' | 'ghost' | 'ghostNavy'; children: ReactNode; onClick?: () => void; icon?: ReactNode }) {
  const base: CSSProperties = {
    display: 'inline-flex', alignItems: 'center', gap: 8, cursor: 'pointer',
    fontWeight: 700, borderRadius: 12, border: '1px solid transparent',
    fontFamily: 'inherit', transition: 'all .15s ease',
  }
  const styles: Record<string, CSSProperties> = {
    teal: { ...base, background: C.teal, color: '#fff', fontSize: 14.5, padding: '14px 26px', boxShadow: '0 8px 24px rgba(14,159,134,0.28)' },
    dark: { ...base, background: C.navy, color: '#fff', fontSize: 13, padding: '9px 17px', borderRadius: 10 },
    ghost: { ...base, background: '#fff', color: C.navy, fontSize: 14.5, padding: '14px 24px', border: `1px solid ${C.btnBorder}` },
    ghostNavy: { ...base, background: 'transparent', color: '#fff', fontSize: 14.5, padding: '14px 24px', border: '1px solid rgba(255,255,255,0.28)' },
  }
  const cls = variant === 'teal' ? 'lp-btn-teal' : variant === 'dark' ? 'lp-btn-dark' : 'lp-btn-ghost'
  return (
    <button className={cls} style={styles[variant]} onClick={onClick}>
      {icon}
      {children}
    </button>
  )
}

function Eyebrow({ children, onNavy = false }: { children: ReactNode; onNavy?: boolean }) {
  return (
    <div style={{ fontSize: 12.5, fontWeight: 800, color: onNavy ? C.teal : C.tealDeep, textTransform: 'uppercase', letterSpacing: '1px' }}>
      {children}
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

// ── 1. Banner ──────────────────────────────────────────────────────────────
function Banner({ L, onClose }: { L: Lfn; onClose: () => void }) {
  return (
    <div style={{ background: C.navy, color: C.onNavy3, fontSize: 12.5, fontWeight: 600, textAlign: 'center', padding: '9px 20px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10 }}>
      <span className="lp-pulse" style={{ width: 7, height: 7, borderRadius: '50%', background: C.teal }} />
      {L('eligo Agenten sind jetzt live — autonome KI, menschliche Kontrolle.', 'eligo agents are live — autonomous AI, human control.')}
      <a href="#" onClick={(e) => { e.preventDefault(); onClose() }} style={{ color: '#fff', fontWeight: 700, borderBottom: `1px solid ${C.teal}` }}>
        {L('Mehr erfahren', 'Learn more')} →
      </a>
    </div>
  )
}

// ── 2. Nav ─────────────────────────────────────────────────────────────────
function Nav({ L, lang, setLang, onEnterApp }: { L: Lfn; lang: Lang; setLang: (l: Lang) => void; onEnterApp: () => void }) {
  const links = [L('Produkt', 'Product'), L('Agenten', 'Agents'), 'Compliance', L('Preise', 'Pricing')]
  return (
    <header style={{ position: 'sticky', top: 0, zIndex: 40, background: 'rgba(255,255,255,0.86)', backdropFilter: 'blur(12px)', borderBottom: `1px solid ${C.line}` }}>
      <div style={{ ...container, display: 'flex', alignItems: 'center', height: 62 }}>
        <Logo />
        <nav className="lp-nav-links" style={{ display: 'flex', gap: 6, marginLeft: 28 }}>
          {links.map((l) => (
            <a key={l} href="#" className="lp-navlink" style={{ fontSize: 13.5, fontWeight: 600, color: C.t1, padding: '7px 12px', borderRadius: 9 }}>
              {l}
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
            background: lang === l ? '#fff' : 'transparent',
            color: lang === l ? C.navy : C.t3,
            boxShadow: lang === l ? '0 1px 2px rgba(15,27,42,.08)' : 'none',
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
    <section style={{ position: 'relative', background: 'linear-gradient(168deg, #EAF3F0 0%, #EEF1F4 46%, #EDE9E6 100%)', overflow: 'hidden' }}>
      <div style={{ position: 'absolute', top: -120, right: -120, width: 520, height: 520, borderRadius: '50%', background: 'radial-gradient(circle, rgba(14,159,134,0.16), transparent 70%)', pointerEvents: 'none' }} />
      <div style={{ ...container, position: 'relative', padding: '74px 28px 92px' }}>
        <div className="lp-hero-grid" style={{ display: 'grid', gridTemplateColumns: '1.05fr 1fr', gap: 52, alignItems: 'center' }}>
          <div>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, background: '#fff', border: '1px solid #DDE7E3', borderRadius: 20, padding: '6px 13px', fontSize: 12, fontWeight: 700, color: C.tealDeep, boxShadow: '0 2px 10px rgba(15,27,42,0.05)' }}>
              <Sparkles size={14} /> {L('KI-native Recruiting-Plattform', 'AI-native recruiting platform')}
            </span>
            <h1 className="lp-h1" style={{ fontSize: 52, fontWeight: 800, lineHeight: 1.04, letterSpacing: '-1.6px', color: C.navy, margin: '20px 0 0' }}>
              {L('Recruiting, betrieben von Agenten.', 'Recruiting, run by agents.')}
              <br />
              <span style={{ color: C.tealDeep }}>{L('Freigegeben von Ihnen.', 'Approved by you.')}</span>
            </h1>
            <p style={{ fontSize: 17, lineHeight: 1.6, color: C.t1, maxWidth: 500, margin: '20px 0 0' }}>
              {L(
                'eligo sourct, verifiziert und matcht Kandidaten autonom — jede Aussage mit Beleg. Sie treffen die Entscheidungen, die Agenten erledigen die Arbeit.',
                'eligo sources, verifies and matches candidates autonomously — every claim sourced. You make the decisions, the agents do the work.',
              )}
            </p>
            <div style={{ display: 'flex', gap: 14, margin: '28px 0 0', flexWrap: 'wrap' }}>
              <Btn variant="teal" onClick={onEnterApp}>{L('Kostenlos starten', 'Start for free')}</Btn>
              <Btn variant="ghost" icon={<CirclePlay size={18} color={C.tealDeep} />} onClick={onEnterApp}>
                {L('2-Min-Rundgang', 'Watch 2-min tour')}
              </Btn>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 22, margin: '40px 0 0', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 11.5, fontWeight: 700, color: C.t3, textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                {L('Im Einsatz bei', 'Trusted by')}
              </span>
              {['N26', 'Doctolib', 'Celonis', 'Bitpanda'].map((b) => (
                <span key={b} style={{ fontSize: 15, fontWeight: 800, color: C.t4 }}>{b}</span>
              ))}
            </div>
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
      <div style={{ background: '#fff', border: `1px solid ${C.line2}`, borderRadius: 18, boxShadow: '0 26px 64px rgba(15,27,42,0.16)', overflow: 'hidden' }}>
        {/* dark header */}
        <div style={{ background: C.navy, padding: '13px 16px', display: 'flex', alignItems: 'center', gap: 10 }}>
          <IconTile size={24} radius={7} bg={C.teal} color="#fff"><span style={{ fontSize: 12, fontWeight: 800 }}>e</span></IconTile>
          <span style={{ color: '#fff', fontSize: 12.5, fontWeight: 700 }}>Julia Schmidt</span>
          <span style={{ fontSize: 11, fontWeight: 700, color: C.onNavy3, border: '1px solid #1d5f54', borderRadius: 20, padding: '2px 8px' }}>94% Match</span>
          <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 7, color: C.onNavy, fontSize: 11.5, fontWeight: 600 }}>
            <span className="lp-pulse" style={{ width: 6, height: 6, borderRadius: '50%', background: C.teal }} />
            {L('2 Agenten aktiv', '2 agents live')}
          </span>
        </div>
        {/* body */}
        <div style={{ padding: 16 }}>
          <div style={{ border: `1px solid ${C.line}`, borderRadius: 12, padding: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
              <Layers size={17} color={C.tealDeep} />
              <span style={{ fontSize: 13.5, fontWeight: 800 }}>{L('Belegte Analyse', 'Sourced analysis')}</span>
              <span style={{ marginLeft: 'auto', fontSize: 10.5, fontWeight: 700, color: C.tealDeep, background: C.tealTint, borderRadius: 20, padding: '3px 9px' }}>
                {L('Jede Aussage belegt', 'Every claim sourced')}
              </span>
            </div>
            <p style={{ margin: '8px 0 0', fontSize: 12.5, lineHeight: 1.5, color: C.t2 }}>
              {L('Senior Backend-Engineer, 7 Jahre, zuletzt N26. Starke Go/Python-Basis, belegte Skalierungserfahrung.', 'Senior Backend Engineer, 7 years, last at N26. Strong Go/Python base, sourced scaling experience.')}
            </p>
          </div>
          <div style={{ display: 'grid', gap: 8, marginTop: 8 }}>
            <EvidenceRow icon={<Check size={14} />} tone="green" title={L('Skalierte Payments auf 4 Mio. Nutzer', 'Scaled payments to 4M users')} sub={L('Lebenslauf · Zeile 214', 'CV · line 214')} tag="CV" />
            <EvidenceRow icon={<span style={{ fontWeight: 800 }}>!</span>} tone="amber" title={L('Beschäftigungslücke ~8 Monate', 'Employment gap ~8 months')} sub={L('2019–2020 · im Gespräch klären', '2019–2020 · clarify in call')} tag={L('PRÜFEN', 'REVIEW')} />
            <EvidenceRow icon={<span style={{ fontWeight: 800 }}>★</span>} tone="blue" title={L('Führte Team von 5 Engineers', 'Led a team of 5 engineers')} sub={L('2 Referenzen · REF + CV', '2 references · REF + CV')} tag="REF" />
          </div>
        </div>
      </div>
      {/* floating receipt chip */}
      <div className="lp-floaty" style={{ position: 'absolute', left: -18, bottom: -22, background: '#fff', borderRadius: 14, boxShadow: '0 18px 44px rgba(15,27,42,0.18)', padding: '12px 15px', display: 'flex', alignItems: 'center', gap: 11 }}>
        <IconTile size={30} bg={C.navy} color="#fff"><FileText size={15} /></IconTile>
        <div>
          <div style={{ fontSize: 11, fontWeight: 800 }}>{L('Verifikations-Quittung', 'Verification receipt')}</div>
          <div style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, color: C.t2 }}>sha256:77c1…be9a</div>
        </div>
      </div>
    </div>
  )
}

function EvidenceRow({ icon, tone, title, sub, tag }: { icon: ReactNode; tone: 'green' | 'amber' | 'blue'; title: string; sub: string; tag: string }) {
  const tones = {
    green: { bg: C.tealTint, fg: C.tealDeep, tagBg: C.tealTint, tagFg: C.tealDeep },
    amber: { bg: C.amberTint, fg: C.amberText, tagBg: C.amberTint, tagFg: C.amberText },
    blue: { bg: C.blueTint, fg: C.blue, tagBg: C.blueTint, tagFg: C.blue },
  }[tone]
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 11, border: `1px solid ${C.line}`, borderRadius: 12, padding: '10px 12px' }}>
      <IconTile size={26} radius={8} bg={tones.bg} color={tones.fg}>{icon}</IconTile>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: C.navy }}>{title}</div>
        <div style={{ fontSize: 11.5, color: C.t3 }}>{sub}</div>
      </div>
      <span style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 800, color: tones.tagFg, background: tones.tagBg, borderRadius: 6, padding: '3px 7px' }}>{tag}</span>
    </div>
  )
}

// ── 4. Stats ───────────────────────────────────────────────────────────────
function Stats({ L }: { L: Lfn }) {
  const stats = [
    ['−48%', 'Time-to-Shortlist'],
    ['94%', L('Match-Genauigkeit', 'Match accuracy')],
    ['100%', L('belegbare Aussagen', 'claims sourced')],
    ['24/7', L('Agenten im Einsatz', 'agents at work')],
  ]
  return (
    <section style={{ background: C.navy }}>
      <div style={{ ...container, padding: '34px 28px' }}>
        <div className="lp-stats" style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 20 }}>
          {stats.map(([v, l]) => (
            <div key={l}>
              <div style={{ fontSize: 38, fontWeight: 800, color: '#fff', letterSpacing: '-1.2px' }}>{v}</div>
              <div style={{ fontSize: 12.5, fontWeight: 600, color: C.onNavy, marginTop: 2 }}>{l}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

// ── 5. Agents ──────────────────────────────────────────────────────────────
function Agents({ L }: { L: Lfn }) {
  const cards = [
    { icon: <Search size={20} />, t: 'Sourcing-Agent', b: L('Durchsucht Netzwerke und Jobbörsen, findet passende Profile und legt sie sauber im Datensatz an.', 'Searches networks and job boards, finds fitting profiles and files them cleanly into the record.') },
    { icon: <Plus size={20} />, t: L('Anreicherungs-Agent', 'Enrichment agent'), b: L('Füllt Lücken in Kontakt- und Profildaten aus öffentlichen Quellen — mit Provenienz und Konfidenz.', 'Fills gaps in contact and profile data from public sources — with provenance and confidence.') },
    { icon: <ShieldCheck size={20} />, t: L('Verifikations-Agent', 'Verification agent'), b: L('Prüft jede Aussage gegen die echte Quelle, bevor sie jemand zu sehen bekommt.', 'Checks every claim against the real source before anyone sees it.') },
    { icon: <Target size={20} />, t: 'Matching-Agent', b: L('Rankt Kandidaten und Rollen mit nachvollziehbarer Begründung — kein Blackbox-Score.', 'Ranks candidates and roles with an explainable reason — no black-box score.') },
  ]
  return (
    <section style={{ ...container, padding: '88px 28px 20px' }}>
      <div style={{ textAlign: 'center', maxWidth: 660, margin: '0 auto' }}>
        <Eyebrow>{L('Eine Belegschaft aus Agenten', 'A workforce of agents')}</Eyebrow>
        <h2 className="lp-h2" style={{ fontSize: 38, fontWeight: 800, letterSpacing: '-1px', margin: '12px 0 0' }}>
          {L('Vier Agenten, ein Prozessvertrag.', 'Four agents, one process contract.')}
        </h2>
        <p style={{ fontSize: 16, color: C.t2, maxWidth: 600, margin: '14px auto 0' }}>
          {L('Jeder Agent hat einen klaren Auftrag und schreibt nichts, ohne die Verifikation zu durchlaufen.', 'Each agent has a narrow job and writes nothing without passing verification.')}
        </p>
      </div>
      <div className="lp-grid-4" style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 18, marginTop: 44 }}>
        {cards.map((c) => (
          <div key={c.t} className="lp-agentcard" style={{ background: '#fff', border: `1px solid ${C.line2}`, borderRadius: 16, padding: 22 }}>
            <IconTile>{c.icon}</IconTile>
            <h3 style={{ fontSize: 15, fontWeight: 800, margin: '14px 0 6px' }}>{c.t}</h3>
            <p style={{ fontSize: 12.5, lineHeight: 1.55, color: C.t2, margin: 0 }}>{c.b}</p>
          </div>
        ))}
      </div>
    </section>
  )
}

// ── 6. Receipt split ───────────────────────────────────────────────────────
function CheckBullet({ lead, text }: { lead: string; text: string }) {
  return (
    <div style={{ display: 'flex', gap: 11, alignItems: 'flex-start' }}>
      <Check size={19} color={C.teal} style={{ marginTop: 2, flexShrink: 0 }} />
      <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.5, color: C.t1 }}>
        <b style={{ color: C.navy }}>{lead}</b> — {text}
      </p>
    </div>
  )
}

function ReceiptSplit({ L }: { L: Lfn }) {
  return (
    <section style={{ ...container, padding: '74px 28px' }}>
      <div className="lp-split" style={{ display: 'grid', gridTemplateColumns: '1fr 1.05fr', gap: 56, alignItems: 'center' }}>
        <div>
          <Eyebrow>{L('Belegbar per Design', 'Sourced by design')}</Eyebrow>
          <h2 className="lp-h2" style={{ fontSize: 34, fontWeight: 800, letterSpacing: '-0.8px', margin: '12px 0 0' }}>
            {L('Jede Aussage kommt mit einer Quittung.', 'Every claim comes with a receipt.')}
          </h2>
          <p style={{ fontSize: 15.5, color: C.t2, margin: '16px 0 26px', lineHeight: 1.6 }}>
            {L('Keine Blackbox. Öffnen Sie jede Behauptung und sehen Sie genau, was gelesen, behauptet, verifiziert und geschrieben wurde — mit Quelle, Konfidenz und Signatur.', 'No black box. Open any claim and see exactly what was read, asserted, verified and written — with source, confidence and signature.')}
          </p>
          <div style={{ display: 'grid', gap: 18 }}>
            <CheckBullet lead={L('Gelesen → Verifiziert', 'Read → Verified')} text={L('jeder Schritt des Agenten ist einsehbar.', 'every step the agent took is visible.')} />
            <CheckBullet lead={L('Quelle & Konfidenz', 'Source & confidence')} text={L('inklusive Zeitstempel und kryptografischer Signatur.', 'including timestamp and cryptographic signature.')} />
            <CheckBullet lead="Human-in-the-loop" text={L('nichts geht raus, bevor Sie es freigeben.', 'nothing ships before you approve it.')} />
          </div>
        </div>
        <div style={{ background: C.surf2, border: `1px solid ${C.line}`, borderRadius: 18, padding: 22 }}>
          <ReceiptCard L={L} />
        </div>
      </div>
    </section>
  )
}

function ReceiptCard({ L }: { L: Lfn }) {
  const steps = [
    ['1', L('GELESEN', 'READ'), L('Lebenslauf.pdf, Abschnitt „N26 · Payments".', 'CV.pdf, section “N26 · Payments”.'), false],
    ['2', L('BEHAUPTET', 'ASSERTED'), L('Skaliertes Zahlungssystem auf 4 Mio. Nutzer.', 'Scaled payment system to 4M users.'), false],
    ['3', L('VERIFIZIERT', 'VERIFIED'), L('Kennzahl im Quelltext belegt (Zeile 214).', 'Figure sourced in the text (line 214).'), true],
    ['4', L('GESCHRIEBEN', 'WRITTEN'), L('Als Stärke markiert, Beleg verlinkt.', 'Marked as a strength, evidence linked.'), true],
  ] as const
  return (
    <div style={{ background: '#fff', border: `1px solid ${C.line2}`, borderRadius: 14, padding: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
        <IconTile size={34} bg={C.navy} color="#fff"><FileText size={16} /></IconTile>
        <div>
          <div style={{ fontSize: 14.5, fontWeight: 800 }}>{L('Verifikations-Quittung', 'Verification receipt')}</div>
          <div style={{ fontSize: 12, color: C.t3 }}>{L('RCPT-9014 · Extraktions-Agent', 'RCPT-9014 · Extraction agent')}</div>
        </div>
        <span style={{ marginLeft: 'auto', fontSize: 11.5, fontWeight: 700, color: C.tealDeep, background: C.tealTint, borderRadius: 20, padding: '4px 10px' }}>
          ✓ {L('Verifiziert', 'Verified')}
        </span>
      </div>
      <div style={{ display: 'grid', gap: 4, margin: '18px 0' }}>
        {steps.map(([n, title, body, done]) => (
          <div key={n} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
            <span style={{ width: 22, height: 22, borderRadius: 7, background: done ? C.tealTint : C.surf, color: done ? C.tealDeep : C.t2, fontSize: 11, fontWeight: 800, display: 'grid', placeItems: 'center', flexShrink: 0 }}>{n}</span>
            <div style={{ paddingBottom: 6 }}>
              <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: '0.4px', color: done ? C.tealDeep : C.t2 }}>{title}</div>
              <div style={{ fontSize: 13.5, color: C.navy, marginTop: 1 }}>{body}</div>
            </div>
          </div>
        ))}
      </div>
      <div style={{ background: C.surf2, borderRadius: 12, padding: '12px 14px', display: 'grid', gap: 8 }}>
        {[
          [L('Quelle', 'Source'), 'Lebenslauf.pdf'],
          [L('Konfidenz', 'Confidence'), '0.91'],
          [L('Signatur', 'Signature'), 'sha256:77c1…be9a'],
        ].map(([k, v]) => (
          <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
            <span style={{ color: C.t2 }}>{k}</span>
            <span style={{ fontFamily: 'ui-monospace, monospace', fontWeight: 700, color: C.navy }}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── 7. Matching split ──────────────────────────────────────────────────────
function MatchingSplit({ L }: { L: Lfn }) {
  const rows = [
    ['94', C.teal, 'N26', L('Senior Backend · Go/Python', 'Senior Backend · Go/Python'), L('Skalierung auf Mio.-Nutzer belegt.', 'Scaling to millions of users sourced.')],
    ['88', C.blue, 'Trade Republic', L('Platform Engineer · EU-Fintech', 'Platform Engineer · EU fintech'), L('Passendes Domänenwissen, Umzug offen.', 'Matching domain, relocation open.')],
    ['81', C.amber, 'Mollie', L('Backend · Payments', 'Backend · Payments'), L('Starke Basis, weniger Seniorität.', 'Strong base, less seniority.')],
  ] as const
  return (
    <section style={{ background: 'linear-gradient(180deg, #F1FAF6, #fff)' }}>
      <div style={{ ...container, padding: '74px 28px' }}>
        <div className="lp-split" style={{ display: 'grid', gridTemplateColumns: '1.05fr 1fr', gap: 56, alignItems: 'center' }}>
          <div className="lp-split-mock" style={{ background: '#fff', border: `1px solid ${C.line2}`, borderRadius: 18, boxShadow: '0 20px 50px rgba(15,27,42,0.10)', padding: 18 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 12 }}>
              <Layers size={17} color={C.tealDeep} />
              <span style={{ fontSize: 14, fontWeight: 800 }}>{L('Passende Rollen', 'Matching roles')}</span>
              <span style={{ marginLeft: 'auto', fontSize: 11.5, color: C.t3, fontWeight: 600 }}>{L('Erklärt & belegt', 'Explained & sourced')}</span>
            </div>
            <div style={{ display: 'grid', gap: 10 }}>
              {rows.map(([score, color, company, role, why]) => (
                <div key={company} style={{ display: 'flex', gap: 14, alignItems: 'center', border: `1px solid ${C.line}`, borderRadius: 12, padding: '12px 14px' }}>
                  <div style={{ width: 44, textAlign: 'center' }}>
                    <div style={{ fontSize: 20, fontWeight: 800, color }}>{score}</div>
                    <div style={{ fontSize: 8.5, fontWeight: 800, color: C.t3, letterSpacing: '0.5px' }}>FIT</div>
                    <div style={{ height: 4, borderRadius: 3, background: C.surf, marginTop: 4, overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${score}%`, background: color, borderRadius: 3 }} />
                    </div>
                  </div>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontSize: 13.5, fontWeight: 700, color: C.navy }}>{company}</div>
                    <div style={{ fontSize: 12, color: C.t3 }}>{role}</div>
                  </div>
                  <span style={{ maxWidth: 150, fontSize: 8.5, fontWeight: 800, color: C.tealDeep, background: C.tealTint, borderRadius: 6, padding: '4px 8px', lineHeight: 1.35 }}>
                    {L('WARUM', 'WHY')} · {why}
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div>
            <Eyebrow>{L('Matching mit Erklärung', 'Explainable matching')}</Eyebrow>
            <h2 className="lp-h2" style={{ fontSize: 34, fontWeight: 800, letterSpacing: '-0.8px', margin: '12px 0 0' }}>
              {L('Kandidaten und Rollen, die wirklich passen.', 'Candidates and roles that truly fit.')}
            </h2>
            <p style={{ fontSize: 15.5, color: C.t2, margin: '16px 0 26px', lineHeight: 1.6 }}>
              {L('Deterministische Muss-Kriterien filtern zuerst; das Modell rankt nur den Rest — und erklärt jeden Treffer in einem Satz.', 'Deterministic must-haves filter first; the model only ranks the rest — and explains every hit in one sentence.')}
            </p>
            <div style={{ display: 'grid', gap: 18 }}>
              <CheckBullet lead={L('Harte Filter zuerst', 'Hard filters first')} text={L('Arbeitserlaubnis, Standort, Gehalt — nicht verhandelbar.', 'Work permit, location, salary — non-negotiable.')} />
              <CheckBullet lead={L('Erklärung statt Score', 'Explanation, not a score')} text={L('jeder Match kommt mit einem „Warum" und einem „Achtung".', 'every match comes with a “why” and a “watch out”.')} />
              <CheckBullet lead={L('Belegt', 'Sourced')} text={L('die Begründung verweist auf Profil und Rolle.', 'the reasoning points to the profile and the role.')} />
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

// ── 8. Compliance ──────────────────────────────────────────────────────────
function Compliance({ L }: { L: Lfn }) {
  const chips = [
    'DSGVO / GDPR', L('KI-VO · Aufsicht', 'AI Act · oversight'), L('Art. 14 automatisiert', 'Art. 14 automated'),
    'ISO 27001', L('EU-gehostet', 'EU-hosted'), L('Vollständiges Audit-Log', 'Full audit log'),
  ]
  return (
    <section style={{ ...container, padding: '74px 28px' }}>
      <div style={{ position: 'relative', background: C.navy, borderRadius: 22, padding: '44px 46px', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', top: -100, right: -80, width: 380, height: 380, borderRadius: '50%', background: 'radial-gradient(circle, rgba(14,159,134,0.18), transparent 70%)' }} />
        <div className="lp-compliance-grid" style={{ position: 'relative', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 40, alignItems: 'center' }}>
          <div>
            <Eyebrow onNavy>{L('Compliance-nativ', 'Compliance-native')}</Eyebrow>
            <h2 className="lp-h2" style={{ fontSize: 32, fontWeight: 800, color: '#fff', letterSpacing: '-0.6px', margin: '12px 0 0' }}>
              {L('Für die europäische Realität gebaut.', 'Built for the European reality.')}
            </h2>
            <p style={{ fontSize: 15, color: C.onNavy2, margin: '14px 0 0', lineHeight: 1.6, maxWidth: 420 }}>
              {L('Die Verifikations- und Quittungs-Schicht bildet fast 1:1 ab, was ein Hochrisiko-KI-System ohnehin haben muss.', 'The verification and receipt layer maps almost one-to-one onto what a high-risk AI system must have anyway.')}
            </p>
          </div>
          <div className="lp-chip-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            {chips.map((c) => (
              <div key={c} style={{ display: 'flex', alignItems: 'center', gap: 8, background: C.panel, border: `1px solid ${C.panelBorder}`, borderRadius: 12, padding: '14px 15px' }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: C.teal, flexShrink: 0 }} />
                <span style={{ fontSize: 12.5, fontWeight: 700, color: '#E7EDF2' }}>{c}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

// ── 9. Testimonial ─────────────────────────────────────────────────────────
function Testimonial({ L }: { L: Lfn }) {
  return (
    <section style={{ ...container, maxWidth: 920, padding: '40px 28px 80px', textAlign: 'center' }}>
      <Quote size={40} color={C.teal} style={{ transform: 'scaleX(-1)' }} />
      <p className="lp-serif" style={{ fontSize: 28, lineHeight: 1.4, color: C.navy, letterSpacing: '-0.3px', maxWidth: 760, margin: '12px auto 0' }}>
        {L(
          '„Zum ersten Mal vertraue ich einer KI-Bewertung — weil ich jede Aussage bis zur Quelle zurückverfolgen kann. Meine Recruiter sichten Belege, keine Blackbox."',
          '“For the first time I trust an AI assessment — because I can trace every claim back to its source. My recruiters review evidence, not a black box.”',
        )}
      </p>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 14, marginTop: 28 }}>
        <span style={{ width: 44, height: 44, borderRadius: '50%', background: 'linear-gradient(135deg,#0E9F86,#0B7D6A)', color: '#fff', fontWeight: 800, display: 'grid', placeItems: 'center' }}>MK</span>
        <div style={{ textAlign: 'left' }}>
          <div style={{ fontSize: 13.5, fontWeight: 800 }}>Maren Kaltenbach</div>
          <div style={{ fontSize: 12, color: C.t3 }}>{L('Head of Talent · Peer Ventures', 'Head of Talent · Peer Ventures')}</div>
        </div>
      </div>
    </section>
  )
}

// ── 10. Final CTA ──────────────────────────────────────────────────────────
function FinalCta({ L, onEnterApp }: { L: Lfn; onEnterApp: () => void }) {
  return (
    <section style={{ background: 'linear-gradient(168deg,#EAF3F0,#EDE9E6)' }}>
      <div style={{ ...container, padding: '78px 28px', textAlign: 'center' }}>
        <h2 style={{ fontSize: 42, fontWeight: 800, letterSpacing: '-1.2px', maxWidth: 640, margin: '0 auto' }}>
          {L('Geben Sie den Agenten die Arbeit. Behalten Sie die Entscheidung.', 'Give the agents the work. Keep the decision.')}
        </h2>
        <p style={{ fontSize: 16.5, color: C.t1, maxWidth: 520, margin: '16px auto 28px' }}>
          {L('In 15 Minuten startklar. Ihre Daten bleiben in der EU.', 'Ready in 15 minutes. Your data stays in the EU.')}
        </p>
        <div style={{ display: 'flex', gap: 14, justifyContent: 'center', flexWrap: 'wrap' }}>
          <Btn variant="dark" onClick={onEnterApp}>{L('Demo buchen', 'Book a demo')}</Btn>
          <Btn variant="ghost" onClick={onEnterApp}>{L('Kostenlos starten', 'Start for free')}</Btn>
        </div>
        <p style={{ fontSize: 12.5, color: C.t3, marginTop: 22 }}>
          {L('DSGVO-konform · EU-gehostet · in 15 Minuten startklar', 'GDPR-compliant · EU-hosted · ready in 15 minutes')}
        </p>
      </div>
    </section>
  )
}

// ── 11. Footer ─────────────────────────────────────────────────────────────
function Footer({ L }: { L: Lfn }) {
  const cols = [
    [L('Produkt', 'Product'), ['Sourcing', 'Verifikation', 'Matching', 'Reporting']],
    [L('Unternehmen', 'Company'), [L('Über uns', 'About'), 'Blog', L('Karriere', 'Careers'), 'Kontakt']],
    [L('Rechtliches', 'Legal'), ['DSGVO / GDPR', 'AI Act', L('Impressum', 'Imprint'), L('Datenschutz', 'Privacy')]],
  ]
  return (
    <footer style={{ background: C.navy, color: C.onNavy }}>
      <div style={{ ...container, padding: '52px 28px 34px' }}>
        <div className="lp-footer-grid" style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr 1fr 1fr', gap: 36 }}>
          <div>
            <Logo onNavy />
            <p style={{ fontSize: 12.5, lineHeight: 1.6, color: C.onNavy, maxWidth: 250, marginTop: 14 }}>
              {L('KI-native Recruiting-Plattform. Autonome Agenten, belegte Aussagen, menschliche Freigabe.', 'AI-native recruiting platform. Autonomous agents, sourced claims, human approval.')}
            </p>
          </div>
          {cols.map(([h, items]) => (
            <div key={h as string}>
              <div style={{ fontSize: 11, fontWeight: 800, color: '#fff', textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: 14 }}>{h}</div>
              <div style={{ display: 'grid', gap: 9 }}>
                {(items as string[]).map((it) => (
                  <a key={it} href="#" className="lp-footlink" style={{ fontSize: 12.5, color: C.onNavy }}>{it}</a>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div style={{ borderTop: `1px solid #1d2b3a` }}>
        <div style={{ ...container, padding: '18px 28px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11.5, flexWrap: 'wrap', gap: 10 }}>
          <span>© 2026 eligo. {L('Alle Rechte vorbehalten.', 'All rights reserved.')}</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: C.teal }} />
            {L('EU-gehostet · DSGVO-konform', 'EU-hosted · GDPR-compliant')}
          </span>
        </div>
      </div>
    </footer>
  )
}
