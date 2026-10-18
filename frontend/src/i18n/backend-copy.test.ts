// Copy the BACKEND sends, which the frontend renders.
//
// Two places on the settings and import screens show strings the server
// authored: the import spec labels its entities and every mappable field
// (`backend/app/domain/imports/spec.py`), and each ATS connector labels and
// describes itself (`backend/app/domain/atsimport/connectors/`). All of it is
// written in German, and the frontend used to render it raw — so an English
// session read "Kandidaten", "Ansprechpartner" and "Die Personen aus Ihrem
// bisherigen System — Pflicht ist nur ein Name." on an otherwise English page.
//
// The call sites now pass it through `t()`. That alone is not enough: `t(x)`
// with a variable is invisible to `dictionary.test.ts`, which only reads
// literal call sites, so a label the dictionary has never heard of falls back
// to German silently — exactly the failure mode this whole change is about.

import { describe, expect, it } from 'vitest'

import { EN } from './en'
import { serverCopy } from './serverCopy.support'

describe('copy the backend sends', () => {
  const copy = serverCopy()

  it('found the strings at all — a silent zero would pass everything', () => {
    // If a regex stops matching because the Python was reformatted, the
    // assertion below passes vacuously. Pin the shape instead.
    const kinds = new Set(copy.map((c) => c.source))
    expect(kinds).toContain('spec.py entity label')
    expect(kinds).toContain('spec.py entity hint')
    expect(kinds).toContain('spec.py field label')
    expect(kinds).toContain('connector label')
    expect(kinds).toContain('connector hint')
    expect(copy.length).toBeGreaterThan(40)
  })

  it('can translate every string it renders', () => {
    const missing = copy
      .filter(({ value }) => !(value in EN))
      .map(({ source, value }) => `${source}: ${value}`)
    expect([...new Set(missing)]).toEqual([])
  })
})
