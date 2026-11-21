import { api } from '@/api/client'
import type { CreatorDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'

/** ELI-69: the people who added leads, managers or companies in this
 *  workspace — the choices of "Angelegt von". Empty on failure: the filter
 *  then offers Alle and Ich only, which still work. `refresh` re-reads them
 *  (after "+ Lead", someone may be a creator for the first time). */
export function useCreators(kind: 'leads' | 'managers' | 'companies', refresh = 0): CreatorDTO[] {
  const creators = useAsync<CreatorDTO[]>(() => api.creators(kind), [kind, refresh], { keepPrevious: true })
  return creators.data ?? []
}
