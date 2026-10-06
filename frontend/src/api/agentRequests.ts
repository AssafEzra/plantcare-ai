/* One watcher for every agent run, instead of one per screen.
 *
 * `useAgentRequest` polls a single request and, when it succeeds, refreshes the
 * rest of the cache. That works only while the component holding the id stays
 * mounted — so work announced itself to the screen that started it and nowhere
 * else. Leave Add Plant before the identification lands and the species, the
 * status change and the archive-on-failure never reached My Plants.
 *
 * This asks a different question: "what of mine is still running?" It is mounted
 * once, in the shell, so the answer is available on every screen and survives
 * navigation and reload. `GET /v1/agent-requests` (app/api/routers/agent_requests.py)
 * answers it through the caller's own client, so RLS scopes it.
 *
 * It is not a background refresher. While nothing is running it makes no requests
 * at all; the only other time it asks is when the app regains visibility, and at
 * most once a minute. Nothing changed means nothing refetches and nothing
 * re-renders.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { scoped } from '../lib/queryKeys'
import { useAuth } from '../auth/context'
import { POLL_INTERVAL_MS, type AgentRequest } from './identification'

/** How stale the answer may be before returning to the app is worth one question. */
export const VISIBILITY_MIN_GAP_MS = 60_000

export type OpenRequest = AgentRequest

export function openRequestsKey(userId: string | null | undefined) {
  return scoped(userId, ['agent-requests', 'open'])
}

/**
 * Everything of mine that has not settled, and a refresh of the cache when one does.
 *
 * Returns the open list as the server last reported it. `AgentTray` renders from
 * this; nothing else needs to.
 */
export function useOpenAgentRequests() {
  const { userId } = useAuth()
  const queryClient = useQueryClient()

  const query = useQuery({
    queryKey: openRequestsKey(userId),
    queryFn: () => api.get<OpenRequest[]>('/v1/agent-requests'),
    enabled: Boolean(userId),
    staleTime: 0,
  })

  const open = query.data
  const running = (open?.length ?? 0) > 0

  /* An explicit timer rather than `refetchInterval`, for the reason already
     written at identification.ts: the declarative option fired once here and the
     list then froze while the run completed behind it. Through a ref so the
     effect depends only on whether anything is running - depending on the query
     object would tear the timer down and rebuild it every render. */
  const refetchRef = useRef(query.refetch)
  useEffect(() => {
    refetchRef.current = query.refetch
  })

  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => void refetchRef.current(), POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [running])

  /* The refresh. An id that was open and no longer is means an agent finished and
     wrote something this tab is showing a stale copy of. Invalidating everything
     except the agent-request keys themselves is the same predicate `useAgentRequest`
     used, moved here so there is one owner rather than three. Scoped to the acting
     identity, so a view-as switch does not refetch the administrator's own data. */
  const previous = useRef<string[]>([])
  useEffect(() => {
    if (!open) return
    const ids = open.map((entry) => entry.id)
    const settled = previous.current.filter((id) => !ids.includes(id))
    previous.current = ids
    if (settled.length === 0) return
    void queryClient.invalidateQueries({
      queryKey: scoped(userId, []),
      predicate: (entry) =>
        !entry.queryKey.includes('agent-request') && !entry.queryKey.includes('agent-requests'),
    })
  }, [open, queryClient, userId])

  return query
}

/**
 * Ask once when the app comes back, and not more than once a minute.
 *
 * This is the only thing that catches changes no browser made — the 07:30 tick
 * materialising tasks, the sweep marking them overdue. `refetchOnWindowFocus`
 * stays off globally (main.tsx): the point is one cheap question, not every query
 * refetching because a tab regained focus.
 */
export function useRefreshOnReturn() {
  const { userId } = useAuth()
  const queryClient = useQueryClient()
  // Zero, not `Date.now()`: reading the clock during render is impure, and the
  // first return after the app opens is exactly the one worth answering anyway.
  const lastRef = useRef(0)

  const check = useCallback(async () => {
    if (document.visibilityState !== 'visible') return
    const now = Date.now()
    if (now - lastRef.current < VISIBILITY_MIN_GAP_MS) return
    lastRef.current = now

    const open = await queryClient.fetchQuery({
      queryKey: openRequestsKey(userId),
      queryFn: () => api.get<OpenRequest[]>('/v1/agent-requests'),
    })

    // Something is running: the poll above takes over and will refresh the cache
    // when it lands, so there is nothing to do here.
    if (open.length > 0) return

    // Nothing is running, so anything that changed was changed by the server on
    // its own schedule. Only the two lists it touches.
    void queryClient.invalidateQueries({ queryKey: scoped(userId, ['plants']) })
    void queryClient.invalidateQueries({ queryKey: scoped(userId, ['tasks']) })
  }, [queryClient, userId])

  useEffect(() => {
    if (!userId) return
    const onVisible = () => void check()
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [check, userId])
}

/** Is a run of this type already going for this plant? Disables the button that starts one. */
export function useIsAgentBusy(plantId: string | null, agentType: string): boolean {
  const { data } = useOpenAgentRequests()
  if (!plantId || !data) return false
  return data.some((entry) => entry.plant_id === plantId && entry.agent_type === agentType)
}

/** The sentence the API uses for the same refusal (services/agent_requests.py). */
export const AGENT_BUSY = 'הסוכן כבר פועל, נסו שוב בעוד רגע.'

/* Rows the tray shows: what is open now, plus what settled since it was last
   cleared. Kept here rather than in the component so the list survives navigation
   between screens - the tray unmounts and remounts, the record does not. */
export type TrayRow = {
  id: string
  agentType: string
  plantId: string | null
  status: OpenRequest['status']
}

export function useTrayRows(): { rows: TrayRow[]; clear: () => void; busy: boolean } {
  const { userId } = useAuth()
  const queryClient = useQueryClient()
  const { data } = useOpenAgentRequests()
  const [seen, setSeen] = useState<TrayRow[]>([])

  /* Add what is newly open, and keep the status of what is still open current. */
  useEffect(() => {
    if (!data) return
    setSeen((current) => {
      const open = new Map(data.map((entry) => [entry.id, entry]))
      let changed = false

      const next = current.map((row) => {
        const still = open.get(row.id)
        if (!still || still.status === row.status) return row
        changed = true
        return { ...row, status: still.status }
      })

      for (const entry of data) {
        if (next.some((row) => row.id === entry.id)) continue
        changed = true
        next.push({
          id: entry.id,
          agentType: entry.agent_type,
          plantId: entry.plant_id,
          status: entry.status,
        })
      }

      return changed ? next : current
    })
  }, [data])

  /* A row that has left the open list has settled, but the open list cannot say
     how - it only carries what is still running. Succeeded and failed are the
     difference between a green tick and a red cross, so the outcome is read rather
     than assumed: one request each, once, when it disappears. */
  const asked = useRef<Set<string>>(new Set())
  useEffect(() => {
    if (!data) return
    const openIds = new Set(data.map((entry) => entry.id))

    for (const row of seen) {
      if (openIds.has(row.id)) continue
      if (row.status !== 'QUEUED' && row.status !== 'PROCESSING') continue
      if (asked.current.has(row.id)) continue
      asked.current.add(row.id)

      void queryClient
        .fetchQuery({
          queryKey: scoped(userId, ['agent-request', row.id]),
          queryFn: () => api.get<AgentRequest>(`/v1/agent-requests/${row.id}`),
          // Never from cache. The screens that draw progress poll this same key,
          // so the cached value at this exact moment is the last poll before the
          // run settled - PROCESSING - and the global staleTime of 30s is long
          // enough for `fetchQuery` to hand it straight back. The row then never
          // reached a tick or a cross, which left the panel permanently unclosable.
          staleTime: 0,
        })
        .then((settled) => {
          setSeen((current) =>
            current.map((entry) =>
              entry.id === row.id ? { ...entry, status: settled.status } : entry,
            ),
          )
        })
        .catch(() => {
          // The request itself could not be read. Showing it as still running
          // forever would be worse than showing it as finished, and the screen it
          // belongs to carries the real outcome either way.
          setSeen((current) =>
            current.map((entry) =>
              entry.id === row.id ? { ...entry, status: 'SUCCEEDED' } : entry,
            ),
          )
        })
    }
  }, [data, seen, queryClient, userId])

  const busy = seen.some((row) => row.status === 'QUEUED' || row.status === 'PROCESSING')
  const clear = useCallback(() => {
    asked.current.clear()
    setSeen([])
  }, [])
  return { rows: seen, clear, busy }
}
