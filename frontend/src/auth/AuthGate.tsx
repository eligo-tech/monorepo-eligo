import type { ReactNode } from 'react'
import {
  SignedIn,
  SignedOut,
  SignIn,
  OrganizationList,
  useOrganization,
} from '@clerk/clerk-react'

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
        <Screen title="Anmelden" subtitle="Melde dich an, um auf deinen Arbeitsbereich zuzugreifen.">
          <SignIn routing="virtual" />
        </Screen>
      </SignedOut>
      <SignedIn>
        <OrgGate>{children}</OrgGate>
      </SignedIn>
    </>
  )
}

function OrgGate({ children }: { children: ReactNode }) {
  const { organization, isLoaded } = useOrganization()
  if (!isLoaded) return <Screen title="Lädt…" />
  if (!organization) {
    return (
      <Screen
        title="Organisation wählen"
        subtitle="Kandidatendaten sind pro Organisation (Mandant) strikt isoliert. Wähle eine bestehende Organisation oder erstelle eine neue, um fortzufahren."
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
