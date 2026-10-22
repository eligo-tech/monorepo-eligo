import { t } from '@/i18n'

import { useEffect, useState, type ReactNode } from 'react'
import {
  SignedIn,
  SignedOut,
  SignIn,
  SignOutButton,
  OrganizationList,
  OrganizationSwitcher,
  useOrganization,
} from '@clerk/clerk-react'
import { ShieldAlert } from 'lucide-react'

import { ApiError, api } from '@/api/client'
import { supportEmail } from './config'

/** Full-screen centered shell for the sign-in / choose-org steps. */
function Screen({ title, subtitle, children }: { title: string; subtitle?: string; children?: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-page px-4">
      <div className="text-center">
        <div className="text-[22px] font-bold tracking-tight text-ink">
          eligo<span className="text-brand-600">-tech</span>
        </div>
        <h1 className="mt-4 text-[18px] font-semibold text-ink">{title}</h1>
        {subtitle && <p className="mx-auto mt-1 max-w-md text-[14px] text-ink-muted">{subtitle}</p>}
      </div>
      {children}
    </div>
  )
}

/** Gate the dashboard behind Clerk: must be signed in AND have an active
 *  organization (the tenant). Kandidatendaten are isolated per organization. */
export function AuthGate({ children }: { children: ReactNode }) {
  return (
    <>
      <SignedOut>
        <Screen title={t('Anmelden')} subtitle={t('Melde dich an, um auf deinen Arbeitsbereich zuzugreifen.')}>
          <SignIn routing="virtual" />
        </Screen>
      </SignedOut>
      <SignedIn>
        <OrgGate>
          <AdmissionGate>{children}</AdmissionGate>
        </OrgGate>
      </SignedIn>
    </>
  )
}

function OrgGate({ children }: { children: ReactNode }) {
  const { organization, isLoaded } = useOrganization()
  if (!isLoaded) return <Screen title={t('Lädt…')} />
  if (!organization) {
    return (
      <Screen
        title={t('Organisation wählen')}
        // The old wording invited the dead end below: "erstelle eine neue"
        // reads as a way in, and the backend refuses every organization it
        // was not told to admit. Say so here, where it costs one sentence,
        // rather than after somebody has named a workspace.
        subtitle={t('Kandidatendaten sind pro Organisation (Mandant) strikt isoliert. Wähle die Organisation, zu der du gehörst — eine neu erstellte muss eligo-tech erst freischalten.')}
      >
        <OrganizationList
          hidePersonal
          afterSelectOrganizationUrl="/#Kandidaten"
          afterCreateOrganizationUrl="/#Kandidaten"
        />
      </Screen>
    )
  }
  return <>{children}</>
}

// ── Admission ──────────────────────────────────────────────────────────────
//
// Signing in is not admission. `backend/app/core/auth.py:_admitted_tenant`
// only READS the org → tenant mapping; an organization nobody provisioned
// gets HTTP 403 from every endpoint. Until now the frontend had no screen for
// that: the cockpit rendered, each section called its endpoint, each endpoint
// returned 403, and the result was a dashboard of empty panels and error
// hints — which reads as "the product is broken", not as "your workspace has
// not been set up". ELI-12 is one person hitting exactly that.

/** Is this organization admitted, and do we know yet? */
export type Admission = 'checking' | 'admitted' | 'refused' | 'unreachable'

/** `GET /me` failed — does that mean "no workspace", or only "no answer"?
 *
 *  **Only a 403 may lock the app.** Everything else — a dropped connection, a
 *  cold backend, a 500, a token that has not refreshed yet — returns
 *  `unreachable`, and `unreachable` lets the app through. A gate that fails
 *  closed on a network blip would tell a recruiter their workspace does not
 *  exist because the wifi went away for a second, which is a worse lie than
 *  the empty panels this screen replaces: the cockpit already degrades one
 *  section at a time when an endpoint is unavailable, and that is the honest
 *  behaviour for "we could not ask".
 */
export function admissionAfterFailure(error: unknown): Exclude<Admission, 'checking' | 'admitted'> {
  return error instanceof ApiError && error.status === 403 ? 'refused' : 'unreachable'
}

function AdmissionGate({ children }: { children: ReactNode }) {
  const { organization } = useOrganization()
  const orgId = organization?.id ?? null
  const [admission, setAdmission] = useState<Admission>('checking')

  useEffect(() => {
    // `/me` is the probe because it runs the same `get_current_actor`
    // dependency every other route runs and touches no data. Probing with a
    // real endpoint would conflate "this organization has no workspace" with
    // "this workspace has no rows yet" — and a new tenant legitimately has
    // none.
    let cancelled = false
    setAdmission('checking')
    api
      .me()
      .then(() => !cancelled && setAdmission('admitted'))
      .catch((e: unknown) => !cancelled && setAdmission(admissionAfterFailure(e)))
    return () => {
      cancelled = true
    }
    // Re-asks after an org switch: the session token carries the active
    // organization, so a different org is a different answer.
  }, [orgId])

  if (admission === 'checking') return <Screen title={t('Lädt…')} />
  if (admission === 'refused') {
    return <NotAdmitted name={organization?.name ?? null} id={orgId} />
  }
  return <>{children}</>
}

/** The dead end, made readable: what happened, which organization it happened
 *  to, and the two ways out that exist. */
function NotAdmitted({ name, id }: { name: string | null; id: string | null }) {
  return (
    <Screen
      title={t('Dieser Arbeitsbereich ist noch nicht freigeschaltet')}
      subtitle={t('Die Anmeldung hat geklappt — diese Organisation hat nur noch keinen Arbeitsbereich.')}
    >
      <div className="w-full max-w-md rounded-xl border border-line bg-white p-5 shadow-sm">
        <div className="flex gap-3">
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-accent-600" />
          <p className="text-[13px] leading-relaxed text-ink-soft">
            {t(
              'Kandidatendaten liegen pro Organisation getrennt. Eine Organisation bekommt ihren Arbeitsbereich, wenn eligo-tech sie einrichtet — anmelden allein reicht dafür nicht.',
            )}
          </p>
        </div>

        {/* The id, not just the name: it is the argument `provision_tenant`
            takes, so a screenshot of this box is a complete support request. */}
        <dl className="mt-4 space-y-1.5 border-t border-line pt-4 text-[13px]">
          <div className="flex gap-3">
            <dt className="w-24 shrink-0 text-ink-muted">{t('Organisation')}</dt>
            <dd className="text-ink">{name || t('Unbenannte Organisation')}</dd>
          </div>
          {id && (
            <div className="flex gap-3">
              <dt className="w-24 shrink-0 text-ink-muted">{t('Kennung')}</dt>
              <dd className="select-all break-all font-mono text-[12px] text-ink-soft">{id}</dd>
            </div>
          )}
        </dl>
        <p className="mt-3 text-[12px] text-ink-soft">
          {t('Schick uns diese Kennung, dann schalten wir die Organisation frei.')}
        </p>

        {supportEmail && (
          <a
            href={`mailto:${supportEmail}?subject=${encodeURIComponent('eligo-tech — Arbeitsbereich freischalten')}`}
            className="mt-4 inline-flex w-full items-center justify-center rounded-lg bg-brand-600 px-4 py-2 text-[13px] font-medium text-white hover:bg-brand-700"
          >
            {t('eligo-tech kontaktieren')}
          </a>
        )}
      </div>

      <div className="w-full max-w-md text-center">
        <p className="text-[13px] text-ink-muted">
          {t('Gehörst du zu einer anderen Organisation? Wechsle dorthin:')}
        </p>
        <div className="mt-2 flex justify-center">
          <OrganizationSwitcher hidePersonal />
        </div>
      </div>

      <SignOutButton>
        <button type="button" className="text-[13px] text-ink-muted underline hover:text-ink">
          {t('Abmelden')}
        </button>
      </SignOutButton>
    </Screen>
  )
}
