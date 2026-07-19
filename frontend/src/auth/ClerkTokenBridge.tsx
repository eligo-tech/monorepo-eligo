import { useEffect } from 'react'
import { useAuth } from '@clerk/clerk-react'
import { setAuthTokenGetter } from '@/api/client'

/** Bridges Clerk's session token into the plain fetch client so every API call
 *  carries the JWT the backend maps to a tenant. Renders nothing. */
export function ClerkTokenBridge() {
  const { getToken } = useAuth()
  useEffect(() => {
    setAuthTokenGetter(() => getToken())
    return () => setAuthTokenGetter(null)
  }, [getToken])
  return null
}
