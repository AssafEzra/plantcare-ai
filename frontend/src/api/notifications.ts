/* Reminder preferences, and the log of what was actually sent.
 *
 * Mirrors app/api/routers/notifications.py.
 *
 * The delivery log is user-visible on purpose. FINAL section 14 logs every send to
 * prevent duplicates; showing the user that log is how "we did email you" stops being
 * something they have to take on trust. On a deployment with no mail provider
 * configured the honest answer is "we sent nothing", and a user comparing that against
 * an empty inbox deserves to see it.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { scoped } from '../lib/queryKeys'
import { useAuth } from '../auth/context'

export type NotificationPreferences = {
  user_id: string
  email_enabled: boolean
  /** `HH:MM:SS` from Postgres. A10: the time we may *write*, not when a task is due. */
  preferred_time_local: string
  daily_digest: boolean
}

export type DeliveryStatus = 'QUEUED' | 'SENT' | 'FAILED' | 'SKIPPED'

export type NotificationDelivery = {
  id: string
  care_task_id: string | null
  channel: string
  status: DeliveryStatus
  scheduled_at: string
  sent_at: string | null
  error_message: string | null
}

export function usePreferences() {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['notification-preferences']),
    queryFn: () => api.get<NotificationPreferences>('/v1/notification-preferences'),
    enabled: Boolean(userId),
  })
}

/**
 * Save changed preferences.
 *
 * The endpoint refuses an empty body — `PreferencesRequest` drops nulls and then
 * raises if nothing is left — so the caller sends only what actually moved and the
 * screen says "nothing to save" rather than provoking a 422.
 */
export function useUpdatePreferences() {
  const queryClient = useQueryClient()
  const { userId } = useAuth()

  return useMutation({
    mutationFn: (changes: Partial<Omit<NotificationPreferences, 'user_id'>>) =>
      api.put<NotificationPreferences>('/v1/notification-preferences', { json: changes }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: scoped(userId, ['notification-preferences']) })
    },
  })
}

/** Fetched only when asked for: it is a record to check, not something to read daily. */
export function useDeliveries(enabled: boolean, limit = 20) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['notification-deliveries', limit]),
    queryFn: () =>
      api.get<NotificationDelivery[]>('/v1/notification-deliveries', { params: { limit } }),
    enabled: Boolean(userId) && enabled,
  })
}

export const DELIVERY_LABELS: Record<string, string> = {
  QUEUED: 'ממתינה',
  SENT: 'נשלחה',
  FAILED: 'נכשלה',
  // A suppressed address is recorded as skipped rather than sent, so the log does not
  // claim something that never left.
  SKIPPED: 'לא נשלחה',
}
