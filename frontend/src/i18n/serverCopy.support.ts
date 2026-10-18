// Test support, never bundled: it reads the backend's Python off disk with
// `node:fs`, so nothing in the app may import it. Named `.support.ts` rather
// than `.test.ts` so vitest does not try to run it as a suite.
//
// Two tests need the same list and must not keep separate copies of it:
//   * `backend-copy.test.ts` — every string here has an English entry;
//   * `dictionary.test.ts` — these entries are NOT orphans just because the
//     only call sites are `t(f.label)` with a variable.
// Two independent extractions would drift, and the second one drifting makes
// the first one's entries look unused, which invites deleting them.

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** Vitest runs with the frontend package as cwd; the backend is its sibling. */
const backend = (...parts: string[]) => resolve(process.cwd(), '..', 'backend', ...parts)

function read(path: string): string {
  try {
    return readFileSync(path, 'utf8')
  } catch {
    throw new Error(
      `Cannot read ${path}. If the backend moved these files, update this ` +
        `helper — do not delete it: it is the only thing checking that ` +
        `server-authored copy is translatable.`,
    )
  }
}

const all = (src: string, rx: RegExp): string[] => [...src.matchAll(rx)].map((m) => m[1])

export interface ServerString {
  /** Where it came from, so a failure names the file to edit. */
  source: string
  value: string
}

/** Every German string the backend sends for the frontend to display. */
export function serverCopy(): ServerString[] {
  const spec = read(backend('app', 'domain', 'imports', 'spec.py'))
  const connectors = ['file_upload.py', 'aifind.py'].map((f) =>
    read(backend('app', 'domain', 'atsimport', 'connectors', f)),
  )

  const out: ServerString[] = []
  const push = (source: string, values: string[]) => {
    for (const value of values) out.push({ source, value })
  }

  push('spec.py entity label', all(spec, /^\s*label="([^"]+)"/gm))
  push('spec.py entity hint', all(spec, /^\s*hint="([^"]+)"/gm))
  push('spec.py field label', all(spec, /_f\("[a-z_0-9]+",\s*"([^"]+)"/g))
  for (const src of connectors) {
    push('connector label', all(src, /^\s{4}label = "([^"]+)"/gm))
    push('connector hint', all(src, /^\s{4}hint = "([^"]+)"/gm))
  }
  return out
}

/** Just the strings, deduplicated. */
export const serverCopyValues = (): Set<string> =>
  new Set(serverCopy().map((c) => c.value))
