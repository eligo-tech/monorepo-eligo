/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
}

/** The build's id (git sha), compiled in by vite.config.ts; matches /version.json. */
declare const __BUILD_ID__: string

interface ImportMeta {
  readonly env: ImportMetaEnv
}
