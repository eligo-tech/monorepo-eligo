import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// ELI-34: the browser tab is named "Cockpit".
describe('index.html', () => {
  it('names the browser tab "Cockpit"', () => {
    const html = readFileSync(resolve(__dirname, '../index.html'), 'utf8')
    expect(html).toMatch(/<title>Cockpit<\/title>/)
  })
})
