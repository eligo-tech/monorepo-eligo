// Who the signed-in person is, asked once per app load.
//
// The role it returns drives what the UI *explains* — a closed panel says
// "Nur Administratoren" instead of rendering a form the server will refuse.
// It is never the authorization itself: every admin-only endpoint checks the
// same token, so a hidden button is a courtesy and a 403 is the control.

import { useEffect, useState } from 'react'

import { api } from '@/api/client'
import type { MeDTO } from '@/api/types'

export function useMe(): MeDTO | null {
  const [me, setMe] = useState<MeDTO | null>(null)
  useEffect(() => {
    let alive = true
    api
      .me()
      .then((data) => alive && setMe(data))
      .catch(() => alive && setMe(null))
    return () => {
      alive = false
    }
  }, [])
  return me
}

export const isAdmin = (me: MeDTO | null): boolean => me?.role === 'admin'
