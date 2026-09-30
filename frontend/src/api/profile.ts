/* Profile — the first typed endpoint binding.
 *
 * The pattern every later feature follows: a type mirroring the API's response
 * model, a thin fetch function, and a hook whose key goes through `scoped()` so the
 * acting identity (including any view-as target) is part of it.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
  locale: string
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

/**
 * Change the two things a user may change about themselves.
 *
 * `role`, `is_active` and `anonymized_at` are absent from the request model by
 * design — they are administrative, and a database trigger rejects them even if a
 * caller finds another route to them. There is nothing to leave out here because the
 * endpoint accepts nothing else.
 *
 * The timezone is what the scheduler converts every due time through, so changing it
 * moves when reminders arrive. Every list that shows a due date is invalidated with
 * the profile for that reason.
 */
export function useUpdateProfile() {
  const queryClient = useQueryClient()
  const { userId } = useAuth()

  return useMutation({
    mutationFn: (changes: { display_name?: string | null; timezone?: string }) =>
      api.patch<Profile>('/v1/me', { json: changes }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: scoped(userId, ['me']) })
      queryClient.invalidateQueries({ queryKey: scoped(userId, ['dashboard']) })
      queryClient.invalidateQueries({ queryKey: scoped(userId, ['plants']) })
    },
  })
}
