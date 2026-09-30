/* Identification: create a plant, attach photographs, run the agent, confirm.
 *
 * Mirrors app/api/routers/identification.py and the flow in
 * app/ui/app_pages/add_plant.py.
 */

import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { scoped } from '../lib/queryKeys'
import { useAuth } from '../auth/context'
import type { Plant } from './plants'

export const MAX_IMAGES = 4
export const MAX_BYTES = 10 * 1024 * 1024
export const ACCEPTED_MIME = ['image/jpeg', 'image/png', 'image/webp']

/* The five stages of FINAL section 24. COMPLETE is absent: it is the end of the run
   rather than a step the user waits through. */
export const STAGES = [
  ['IMAGES_RECEIVED', 'התמונות התקבלו'],
  ['CONTEXT_LOADED', 'ההקשר נטען'],
  ['ANALYZING', 'מנתחים'],
  ['PREPARING_RESULT', 'מכינים את התוצאה'],
] as const

export const POLL_INTERVAL_MS = 1500

export type AgentRequest = {
  id: string
  agent_type: string
  status: 'QUEUED' | 'PROCESSING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED'
  stage: string | null
  plant_id: string | null
  error_code: string | null
  output_summary: Record<string, unknown> | null
}

export type Candidate = {
  id: string
  scientific_name: string
  common_name: string | null
  rank: number
  confidence_score: number | null
  species_id: string | null
}

export type Identification = {
  id: string
  plant_id: string
  status: 'SUCCESS' | 'NEEDS_MORE_INFORMATION' | 'FAILED'
  method: string
  confidence_score: number | null
  confidence_level: 'HIGH' | 'MEDIUM' | 'LOW' | null
  image_quality: string | null
  request_more_photos: boolean
  insufficient_reason: string | null
  wikipedia_url: string | null
  created_at: string
  candidates: Candidate[]
}

export type ConfirmResult = {
  knowledge_pending?: boolean
  [key: string]: unknown
}

/* --- the run ------------------------------------------------------------- */

export type StartRunInput = { files: File[]; note: string | null }
export type StartRunResult = { plantId: string; requestId: string }

/**
 * Create the plant, upload its photographs, start the agent.
 *
 * The plant is created BEFORE it is named: FINAL section 3 puts naming after
 * confirmation, so there is nothing to ask for yet. A run that fails archives this
 * plant, which is why the failure path offers a fresh start rather than a retry —
 * there is no row left to run a second attempt against.
 */
export function useStartIdentification() {
  const queryClient = useQueryClient()
  const { userId } = useAuth()

  return useMutation<StartRunResult, unknown, StartRunInput>({
    mutationFn: async ({ files, note }) => {
      const plant = await api.post<Plant>('/v1/plants', { json: { notes: note } })

      /* Sequentially, not Promise.all. The API counts uncommitted images per
         context to enforce its own ceiling, and parallel uploads race that check. */
      const imageIds: string[] = []
      for (const file of files) {
        const form = new FormData()
        form.append('file', file)
        form.append('context_type', 'identification')
        const image = await api.post<{ id: string }>(`/v1/plants/${plant.id}/images`, {
          body: form,
        })
        imageIds.push(image.id)
      }

      const run = await api.post<{ agent_request_id: string }>(
        `/v1/plants/${plant.id}/identification-runs`,
        { json: { image_ids: imageIds, user_description: note } },
      )

      return { plantId: plant.id, requestId: run.agent_request_id }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: scoped(userId, ['plants']) })
    },
  })
}

/**
 * Poll one agent request until it settles.
 *
 * An explicit interval rather than `refetchInterval`. The declarative option fired
 * exactly once here and the progress list froze on its first stage while the run
 * completed behind it — observed twice, against a request that reached SUCCEEDED in
 * eight seconds. Rather than keep guessing at why, this owns the timer: it is a
 * handful of lines, it is obvious when read, and its behaviour can be confirmed by
 * counting requests in the network panel.
 *
 * `refetch` is called through a ref so the effect depends only on the id and the
 * settled flag — depending on the query object would tear the timer down and rebuild
 * it on every render.
 */
export function useAgentRequest(requestId: string | null) {
  const { userId } = useAuth()
  const query = useQuery({
    queryKey: scoped(userId, ['agent-request', requestId]),
    queryFn: () => api.get<AgentRequest>(`/v1/agent-requests/${requestId}`),
    enabled: Boolean(requestId),
    staleTime: 0,
  })

  const status = query.data?.status
  const settled = status === 'SUCCEEDED' || status === 'FAILED' || status === 'CANCELLED'

  const refetchRef = useRef(query.refetch)
  useEffect(() => {
    refetchRef.current = query.refetch
  })

  useEffect(() => {
    if (!requestId || settled) return
    const timer = setInterval(() => void refetchRef.current(), POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [requestId, settled])

  return query
}

export function useIdentification(identificationId: string | null) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['identification', identificationId]),
    queryFn: () => api.get<Identification>(`/v1/identifications/${identificationId}`),
    enabled: Boolean(identificationId),
  })
}

export function useConfirmIdentification(identificationId: string | null) {
  const queryClient = useQueryClient()
  const { userId } = useAuth()

  return useMutation<ConfirmResult, unknown, { candidateId: string; name: string | null }>({
    mutationFn: ({ candidateId, name }) =>
      api.post<ConfirmResult>(`/v1/identifications/${identificationId}/confirm`, {
        json: { candidate_id: candidateId, name },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: scoped(userId, ['plants']) })
      queryClient.invalidateQueries({ queryKey: scoped(userId, ['dashboard']) })
    },
  })
}
