import { api } from '@/api/client'
import type { CreatorDTO } from '@/api/types'
import { useAsync } from '@/hooks/useAsync'

/** ELI-69: the people who added leads, managers or companies in this
 *  workspace — the choices of "Angelegt von". Empty on failure: the filter
 *  then offers Alle and Ich only, which still work. */
export function useCreators(kind: 'leads' | 'managers' | 'companies'): CreatorDTO[] {
  const creators = useAsync<CreatorDTO[]>(() => api.creators(kind), [kind])
  return creators.data ?? []
}
