// The mark left of "COCKPIT" (ELI-55): the workspace's own icon when an admin
// uploaded one in Einstellungen (workspace_branding.header_icon), otherwise
// the Eligo mark. Never a hardcoded customer logo — the app is multi-tenant.

import { t } from '@/i18n'

export function WorkspaceMark({ iconUrl }: { iconUrl: string | null }) {
  if (iconUrl) {
    return (
      <span data-mark="workspace" className="flex h-8 w-8 shrink-0 items-center justify-center">
        <img src={iconUrl} alt={t('Logo')} className="max-h-full max-w-full object-contain" />
      </span>
    )
  }
  return (
    <span
      data-mark="eligo"
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-mint-600 text-mint-400"
    >
      <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" aria-hidden>
        <path
          d="M6 7.5h11M6 12h9M6 16.5h11"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
        />
      </svg>
    </span>
  )
}
