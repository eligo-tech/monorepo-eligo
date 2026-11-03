// Adding someone back who asked to be erased (GDPR Art. 17).
//
// Every screen that creates or edits a person wraps its call in
// `withReaddConfirm`. The first attempt goes out without the override; if the
// server answers "this person asked to be erased on <date>", the recruiter is
// asked whether they came back of their own accord. Yes retries with the
// override (the server lifts only the e-mail block and logs who did it); no
// throws an error the screen shows like any other.
//
// One dialog for the whole app, mounted once by <ReaddHost/> — not one per
// form, which is how eight forms would end up saying eight different things.

import { t } from '@/i18n'

import { suppressedOn } from './erasureView'

type Ask = (requestedOn: string) => Promise<boolean>

let asker: Ask | null = null

/** Called by <ReaddHost/>. Returns the unregister function. */
export function registerReaddAsker(fn: Ask): () => void {
  asker = fn
  return () => {
    if (asker === fn) asker = null
  }
}

export class ReaddDeclined extends Error {
  constructor() {
    super(t('Nicht angelegt: Diese Person hat die Löschung ihrer Daten verlangt.'))
    this.name = new.target.name
  }
}

export async function withReaddConfirm<T>(run: (override: boolean) => Promise<T>): Promise<T> {
  try {
    return await run(false)
  } catch (e) {
    const on = suppressedOn(e)
    if (!on) throw e
    // No dialog mounted means nobody can answer — that is a "no", never a yes.
    const yes = asker ? await asker(on) : false
    if (!yes) throw new ReaddDeclined()
    return run(true)
  }
}
