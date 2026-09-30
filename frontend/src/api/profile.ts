/* Profile — the first typed endpoint binding.
 *
 * The pattern every later feature follows: a type mirroring the API's response
 * model, a thin fetch function, and a hook whose key goes through `scoped()` so the
 * acting identity (including any view-as target) is part of it.
 */

import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { scoped } from '../lib/queryKeys'
import { useAuth } from '../auth/context'

/** Mirrors ProfileResponse in app/api/schemas. */
export type Profile = {
  id: string
  email: string
  display_name: string | null
  role: 'USER' | 'ADMIN'
  timezone: string
  is_active: boolean
  created_at: string
}

export function useMe() {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['me']),
    queryFn: () => api.get<Profile>('/v1/me'),
    enabled: Boolean(userId),
  })
}
