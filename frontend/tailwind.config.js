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
      },
      borderRadius: {
        card: '1.25rem',
      },
      boxShadow: {
        card: '0 1px 2px rgba(16, 24, 40, 0.04), 0 8px 24px rgba(16, 24, 40, 0.06)',
        pill: '0 2px 10px rgba(16, 24, 40, 0.08)',
        kanban: '0 1px 2px rgba(16, 24, 40, 0.06), 0 4px 12px rgba(16, 24, 40, 0.05)',
      },
      fontFamily: {
        sans: [
          'Inter',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
      },
    },
  },
  plugins: [],
}