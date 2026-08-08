/** @type {import('tailwindcss').Config} */
// eligo-tech design tokens — derived from the CRM mockups.
// Brand = muted emerald; sidebar = deep navy; accent = amber (active tab).
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Primary brand — muted emerald used for logo, primary buttons, links, active state.
        brand: {
          50: '#eaf5ef',
          100: '#d2ebdf',
          200: '#a9d8c1',
          300: '#78c0a0',
          400: '#4ea886',
          500: '#33986f',
          600: '#277c59',
          700: '#216248',
          800: '#1d4e3b',
          900: '#193f31',
        },
        // Deep navy sidebar surfaces.
        sidebar: {
          DEFAULT: '#0c1622',
          hover: '#16212f',
          active: '#1b2838',
          border: '#1e2a3a',
          muted: '#6b7a8d',
          text: '#c7d0da',
        },
        // Warm amber — active top-tab ring.
        accent: {
          400: '#eeb45a',
          500: '#e79f38',
          600: '#cf8a26',
        },
        // Neutral ink + surfaces.
        ink: {
          DEFAULT: '#1b2430',
          soft: '#3d4757',
          muted: '#8b95a2',
          faint: '#aab2bd',
        },
        page: '#edf0ef',
        line: '#eceff2',

        // ── Cockpit (dark surface) ────────────────────────────────────────
        // Near-black, faintly warm surfaces sampled from the cockpit mockups.
        cockpit: {
          bg: '#0a0b09',
          inset: '#0e0f0c',
          surface: '#121310',
          raised: '#16170f',
          line: 'rgba(255, 255, 255, 0.06)',
          edge: 'rgba(255, 255, 255, 0.10)',
          text: '#e8e8e3',
          dim: '#9a9b93',
          faint: '#6b6d64',
        },
        // Semantic trio. Named (not `emerald`/`amber`/`rose`) so they never
        // shadow a default Tailwind palette the light views still rely on.
        mint: {
          300: '#c6e4cd',
          400: '#a9d6b4',
          500: '#86c69a',
          600: '#5f9c74',
          700: '#3f6b50',
          800: '#2a4838',
        },
        gold: {
          300: '#f0c489',
          400: '#e3a75c',
          500: '#c9902f',
          600: '#9c6f22',
          800: '#4a3517',
        },
        coral: {
          300: '#eaa899',
          400: '#e0897a',
          500: '#c96a58',
          600: '#9d4e3f',
          800: '#4a2620',
        },
        lav: {
          400: '#b0a4d8',
          600: '#7a6ca8',
          800: '#3a3350',
        },
      },
      borderRadius: {
        card: '1.25rem',
        panel: '1.5rem',
      },
      boxShadow: {
        card: '0 1px 2px rgba(16, 24, 40, 0.04), 0 8px 24px rgba(16, 24, 40, 0.06)',
        pill: '0 2px 10px rgba(16, 24, 40, 0.08)',
        kanban: '0 1px 2px rgba(16, 24, 40, 0.06), 0 4px 12px rgba(16, 24, 40, 0.05)',
        // Cockpit: panels read as raised by an inner hairline, not a drop shadow.
        panel: 'inset 0 1px 0 rgba(255, 255, 255, 0.04), 0 12px 32px rgba(0, 0, 0, 0.45)',
        'glow-mint': '0 0 24px rgba(134, 198, 154, 0.28)',
        'glow-gold': '0 0 26px rgba(227, 167, 92, 0.30)',
        'glow-coral': '0 0 22px rgba(224, 137, 122, 0.28)',
      },
      backgroundImage: {
        // Faint graph-paper overlay behind every cockpit screen.
        grid: `linear-gradient(to right, rgba(255, 255, 255, 0.025) 1px, transparent 1px),
               linear-gradient(to bottom, rgba(255, 255, 255, 0.025) 1px, transparent 1px)`,
      },
      backgroundSize: {
        // Not `grid` — that key would collide with backgroundImage.grid, since
        // both utilities share the `bg-` prefix.
        'grid-cell': '44px 44px',
      },
      fontFamily: {
        // Both faces resolve through CSS vars so the command bar's
        // Jet · Mono · Heli control can swap them at runtime (see index.css).
        sans: ['var(--font-ui)'],
        mono: ['var(--font-mono)'],
      },
    },
  },
  plugins: [],
}