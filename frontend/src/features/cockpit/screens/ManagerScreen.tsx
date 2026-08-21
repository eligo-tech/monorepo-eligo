// "Managers" — the client-side contact people. Not built yet.
//
// A Manager is the person at a client company a mandate actually belongs to:
// Firma → Manager → Job. It is deliberately NOT part of the shared market
// corpus — see ARCHITECTURE.md RULE 2. A manager is a natural person, so a
// shared table holding one would make a single erasure request reach across
// every workspace. Contacts stay tenant-scoped, carry provenance, and route
// through the GDPR Art. 14 flow when they come from a public source.

import { PlaceholderScreen } from './PlaceholderScreen'



export function ManagerScreen() {
  return (
    <PlaceholderScreen
      anchor="section-manager"
      title="Manager"
      lead="Die Ansprechpartner auf Kundenseite — die Person, zu der ein Mandat gehört."
    >
      <p>
        Firma → Manager → Job. Diese Ebene fehlt noch: ein Mandat kennt heute die Firma,
        aber nicht die Person, mit der Sie tatsächlich sprechen.
      </p>
      <p>
        Manager sind bewusst <strong>kein</strong> Teil des geteilten Markt-Korpus. Eine
        natürliche Person in einer geteilten Tabelle würde bedeuten, dass eine einzige
        Löschanfrage alle Workspaces trifft. Kontakte bleiben tenant-eigen, führen ihre
        Herkunft mit und lösen bei Erhebung aus öffentlichen Quellen die
        DSGVO-Art.-14-Benachrichtigung aus.
      </p>
    </PlaceholderScreen>
  )
}
