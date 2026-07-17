import type { Candidate, MatchReason } from './types'

// Mock candidate records — shaped like the backend canonical Candidate.
export const candidates: Candidate[] = [
  {
    id: 'c-priya',
    name: 'Priya Ranganathan',
    initials: 'PR',
    avatar: 'bg-brand-500',
    email: 'priya.ranganat@mail.com',
    phone: '+91 80555 56722',
    linkedin: true,
    currentTitle: 'Medical Science Liaison',
    currentCompany: 'Vaia',
    tenure: '2015–2024',
    extraRoles: 1,
    skills: [
      { label: 'M&A', tone: 'purple' },
      { label: 'Risk', tone: 'coral' },
    ],
    extraSkills: 8,
    location: 'Bengaluru, IN',
    verification: 98,
    aiSummary:
      'Medical Science Liaison mit 9 Jahren Erfahrung an der Schnittstelle von Wissenschaft und Vertrieb. Stark in Stakeholder-Management und klinischer Kommunikation.',
    stats: { avgTenure: '4 J · 2 M', current: '9 J · 1 M', total: '9 J · 2 M' },
    experience: [
      { company: 'Vaia', title: 'Medical Science Liaison', period: '2015 – heute', location: 'Bengaluru, IN' },
    ],
  },
  {
    id: 'c-melinda',
    name: 'Melinda Hart',
    initials: 'MH',
    avatar: 'bg-sky-600',
    email: 'melinda.hart@mail.com',
    phone: '+1 312 961 2199',
    linkedin: true,
    currentTitle: 'Co-CEO & President',
    currentCompany: 'Arial Investments',
    tenure: '2019–heute',
    extraRoles: 5,
    skills: [
      { label: 'M&A', tone: 'purple' },
      { label: 'Valuation', tone: 'mint' },
    ],
    extraSkills: 1,
    location: 'Chicago, US',
    verification: 96,
    aiSummary:
      'Co-CEO mit tiefem Track Record in Private Equity und Unternehmensführung. Führt Investmentteams und verantwortet Portfoliostrategie und M&A.',
    stats: { avgTenure: '5 J · 0 M', current: '6 J · 6 M', total: '22 J · 4 M' },
    experience: [
      { company: 'Arial Investments', title: 'Co-CEO & President', period: '2019 – heute', location: 'Chicago, US' },
    ],
  },
  {
    id: 'c-karian',
    name: 'Karian Wong',
    initials: 'KW',
    avatar: 'bg-pink-700',
    email: 'karian.wong@mail.com',
    phone: '+44 20 7946 0583',
    linkedin: true,
    currentTitle: 'Chief Financial Officer',
    currentCompany: 'iRobots',
    tenure: '2024–heute',
    extraRoles: 11,
    skills: [
      { label: 'Risk', tone: 'coral' },
      { label: 'Valuation', tone: 'mint' },
    ],
    extraSkills: 2,
    location: 'London, UK',
    verification: 92,
    aiSummary:
      'CFO mit breiter Erfahrung über Wachstums- und Scale-up-Phasen. Fokus auf Finanzstrategie, Fundraising und Investor Relations.',
    stats: { avgTenure: '2 J · 8 M', current: '1 J · 6 M', total: '18 J · 9 M' },
    experience: [
      { company: 'iRobots', title: 'Chief Financial Officer', period: '2024 – heute', location: 'London, UK' },
    ],
  },
  {
    id: 'c-mattias',
    name: 'Dr. Mattias Heiden',
    initials: 'DM',
    avatar: 'bg-violet-600',
    email: 'dr.mattias.hei@mail.com',
    phone: '+49 89 5551186',
    linkedin: true,
    currentTitle: 'Board Member',
    currentCompany: 'Helio Solutions',
    tenure: '2012–heute',
    extraRoles: 6,
    skills: [
      { label: 'M&A', tone: 'purple' },
      { label: 'Risk', tone: 'coral' },
    ],
    extraSkills: 8,
    location: 'München, DE',
    verification: 88,
    aiSummary:
      'Erfahrenes Aufsichtsratsmitglied mit Schwerpunkt Governance und Restrukturierung. Begleitet Technologieunternehmen bei Wachstum und M&A.',
    stats: { avgTenure: '6 J · 2 M', current: '13 J · 0 M', total: '27 J · 5 M' },
    experience: [
      { company: 'Helio Solutions', title: 'Board Member', period: '2012 – heute', location: 'München, DE' },
    ],
  },
  {
    id: 'c-marie',
    name: 'Marie Fontaine',
    initials: 'MF',
    avatar: 'bg-fuchsia-700',
    email: 'marie.fontaine@gmail.com',
    phone: '+33 6 72 45 98 11',
    linkedin: true,
    currentTitle: 'Investment Associate',
    currentCompany: 'Vanguard',
    tenure: 'Nov 2021 – heute',
    extraRoles: 3,
    skills: [
      { label: 'M&A', tone: 'purple' },
      { label: 'Valuation', tone: 'mint' },
      { label: 'Modelling', tone: 'sky' },
    ],
    extraSkills: 4,
    location: 'Paris, Frankreich',
    verification: 94,
    aiSummary:
      'Investment Associate bei Vanguard in San Francisco mit 9 Jahren Erfahrung in Financial Services. Spezialisiert auf Financial Engineering, Modelling, Bewertung und M&A-Analyse.',
    stats: { avgTenure: '6 J · 4 M', current: '3 J · 1 M', total: '9 J · 2 M' },
    experience: [
      { company: 'Vanguard', title: 'Investment Associate', period: 'Nov 2021 – heute', location: 'San Francisco, US' },
      { company: 'Rothschild & Co', title: 'Analyst, M&A', period: 'Aug 2018 – Okt 2021', location: 'Paris, FR' },
      { company: 'BNP Paribas', title: 'Summer Analyst', period: 'Jun 2017 – Aug 2017', location: 'Paris, FR' },
    ],
  },
]

// The "Warum wir gematcht haben" evidence panel for the Matching screen.
// Every reason carries a strength + a human-readable, evidence-backed detail.
export const marieMatchReasons: MatchReason[] = [
  {
    title: 'Relocation / Remote nötig',
    strength: 'weak',
    detail: 'Ansässig in Paris. Die Rolle ist in Frankfurt — Umzug oder Remote-Flexibilität wäre erforderlich.',
  },
  {
    title: 'Starker akademischer Hintergrund',
    strength: 'very-strong',
    detail: 'M.Sc. Financial Engineering (HEC Paris) — passt exakt zu den quantitativen Anforderungen der Rolle.',
  },
  {
    title: 'Direkte Finance-Leadership-Erfahrung',
    strength: 'strong',
    detail:
      'Über 6 Jahre bei Vanguard in Investment- und Analyse-Rollen — starke Übereinstimmung mit Finance-Director-Verantwortung.',
  },
  {
    title: 'Zusätzlicher Leadership-Beleg',
    strength: 'strong',
    detail: 'Führte ein 4-köpfiges Analystenteam bei Rothschild & Co — belegt durch zwei Referenzen.',
  },
]