import { execSync } from 'node:child_process'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

// The id of this build: the commit Vercel builds, else the local HEAD, else a
// timestamp. The same id is compiled into the bundle (`__BUILD_ID__`) and
// written to `/version.json`, so an open tab can tell that a newer build is
// live (src/lib/version.ts).
function buildId(): string {
  const fromVercel = process.env.VERCEL_GIT_COMMIT_SHA
  if (fromVercel) return fromVercel
  try {
    return execSync('git rev-parse HEAD', { stdio: ['ignore', 'pipe', 'ignore'] })
      .toString()
      .trim()
  } catch {
    return `build-${Date.now()}`
  }
}

const BUILD_ID = buildId()

/** Emit `dist/version.json` with the id the bundle carries. Build only. */
function versionJson(id: string): Plugin {
  return {
    name: 'eligo-version-json',
    apply: 'build',
    generateBundle() {
      this.emitFile({
        type: 'asset',
        fileName: 'version.json',
        source: JSON.stringify({ id }) + '\n',
      })
    },
  }
}

// Eligo Labs frontend — Vite dev server + build config.
export default defineConfig({
  plugins: [react(), versionJson(BUILD_ID)],
  define: {
    __BUILD_ID__: JSON.stringify(BUILD_ID),
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // Proxy API calls to the backend during local dev.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})