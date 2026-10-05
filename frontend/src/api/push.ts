/* Push devices. Mirrors app/api/routers/push.py.
 *
 * Registering happens on the device itself (`useRegisterThisDevice`); pausing,
 * resuming and removing work from any device, because the server holds the
 * registration.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { scoped } from '../lib/queryKeys'
import { useAuth } from '../auth/context'
import { currentSubscription, subscribe, subscriptionBody } from '../lib/push'

export type PushConfig = { configured: boolean; public_key: string | null }

export type PushDevice = {
  id: string
  device_label: string | null
  platform: 'ios' | 'android' | 'other'
  enabled: boolean
  created_at: string
  last_sent_at: string | null
  endpoint: string
}

export function usePushConfig() {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['push-config']),
    queryFn: () => api.get<PushConfig>('/v1/push/config'),
    enabled: Boolean(userId),
    staleTime: Infinity,
  })
}

export function usePushDevices() {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['push-devices']),
    queryFn: () => api.get<PushDevice[]>('/v1/push/subscriptions'),
    enabled: Boolean(userId),
  })
}

/** This device's endpoint, so the list can mark which row is "this device". */
export function useThisEndpoint() {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['push-this-endpoint']),
    queryFn: async () => (await currentSubscription())?.endpoint ?? null,
    enabled: Boolean(userId),
  })
}

function useInvalidateDevices() {
  const queryClient = useQueryClient()
  const { userId } = useAuth()
  return () => {
    queryClient.invalidateQueries({ queryKey: scoped(userId, ['push-devices']) })
    queryClient.invalidateQueries({ queryKey: scoped(userId, ['push-this-endpoint']) })
  }
}

export function useRegisterThisDevice() {
  const invalidate = useInvalidateDevices()
  return useMutation({
    mutationFn: async (publicKey: string) => {
      const subscription = await subscribe(publicKey)
      return api.post<PushDevice>('/v1/push/subscriptions', {
        json: subscriptionBody(subscription),
      })
    },
    onSuccess: invalidate,
  })
}

export function useToggleDevice() {
  const invalidate = useInvalidateDevices()
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.patch<PushDevice>(`/v1/push/subscriptions/${id}`, { json: { enabled } }),
    onSuccess: invalidate,
  })
}

export function useRemoveDevice() {
  const invalidate = useInvalidateDevices()
  return useMutation({
    mutationFn: async ({ id, endpoint }: { id: string; endpoint: string }) => {
      await api.delete(`/v1/push/subscriptions/${id}`)
      // Removing this very device: drop the browser's subscription too, so the
      // phone is not left holding an address nobody sends to.
      const mine = await currentSubscription()
      if (mine && mine.endpoint === endpoint) await mine.unsubscribe()
    },
    onSuccess: invalidate,
  })
}

/**
 * On app open: if this device is already subscribed and allowed, send the
 * subscription again. The server updates the row in place, which is how a
 * subscription the browser quietly renewed gets its new keys there.
 */
export async function resyncThisDevice(): Promise<void> {
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return
  const subscription = await currentSubscription()
  if (!subscription) return
  await api.post('/v1/push/subscriptions', {
    json: { ...subscriptionBody(subscription), resume: false },
  })
}

/** On sign-out: this phone stops receiving this account's reminders. */
export async function forgetThisDevice(): Promise<void> {
  const subscription = await currentSubscription()
  if (!subscription) return
  try {
    await api.post('/v1/push/subscriptions/unsubscribe', {
      json: { endpoint: subscription.endpoint },
    })
  } finally {
    await subscription.unsubscribe()
  }
}
