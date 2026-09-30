/* Health checks and assessments (FINAL section 16).
 *
 * Mirrors app/api/routers/health.py.
 *
 * The Health Agent cannot change a care plan. A finding that asks for one comes back
 * as `requires_care_plan_adjustment` on a recommendation, and the client raises a
 * proposal through the care route — which the user then approves. That indirection is
 * the whole of section 16's "It cannot directly modify the Care Plan", so it is a
 * property of how these two modules are wired together, not an implementation detail.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { scoped } from '../lib/queryKeys'
import { useAuth } from '../auth/context'
import type { HealthStatus, HealthTrend } from '../lib/status'

export const MIN_HEALTH_IMAGES = 1
export const MAX_HEALTH_IMAGES = 4

export type Observation = { observation_text: string; [key: string]: unknown }
export type PossibleIssue = {
  issue_name: string
  severity: number | null
  evidence: string | null
  [key: string]: unknown
}
export type Recommendation = {
  recommendation_text: string
  requires_care_plan_adjustment: boolean
  [key: string]: unknown
}
export type AssessmentSource = { title: string | null; url: string | null; [key: string]: unknown }

export type Assessment = {
  id: string
  plant_id: string
  overall_status: HealthStatus
  confidence_level: string | null
  trend: HealthTrend
  requires_attention: boolean
  user_note: string | null
  insufficient_information_reason: string | null
  created_at: string
  observations: Observation[]
  possible_issues: PossibleIssue[]
  recommendations: Recommendation[]
  sources: AssessmentSource[]
}

export type HealthHistoryEntry = {
  id: string
  overall_status: HealthStatus
  confidence_level: string | null
  trend: HealthTrend
  requires_attention: boolean
  created_at: string
}

export type HealthCheckAccepted = {
  agent_request_id: string
  status: string
  replayed: boolean
}

export function useAssessment(assessmentId: string | null | undefined) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['assessment', assessmentId]),
    queryFn: () => api.get<Assessment>(`/v1/health-assessments/${assessmentId}`),
    enabled: Boolean(assessmentId),
  })
}

export function useHealthHistory(plantId: string | undefined, enabled: boolean) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['plant', plantId, 'health-history']),
    queryFn: () => api.get<HealthHistoryEntry[]>(`/v1/plants/${plantId}/health-history`),
    enabled: Boolean(plantId) && enabled,
  })
}

/**
 * Upload whatever is new, then start the check.
 *
 * The photographs are uploaded here rather than chosen beforehand because a health
 * check is prompted by something just noticed, and the picture of it does not exist
 * until now. They go in under `context_type=health`, which keeps them out of the
 * plant's gallery: evidence for one assessment is not a portrait.
 *
 * The ids are deduplicated before they are sent. The API refuses duplicates too, but
 * three real health checks died on a list holding one id three times — each after a
 * full minute of model time, because nothing objected until the insert.
 */
export function useStartHealthCheck(plantId: string | undefined) {
  const queryClient = useQueryClient()
  const { userId } = useAuth()

  return useMutation({
    mutationFn: async ({
      files,
      existingImageIds,
      note,
    }: {
      files: File[]
      existingImageIds: string[]
      note: string | null
    }) => {
      const imageIds = [...new Set(existingImageIds)]

      for (const file of files) {
        const form = new FormData()
        form.append('file', file)
        form.append('context_type', 'health')
        const image = await api.post<{ id: string }>(`/v1/plants/${plantId}/images`, {
          body: form,
        })
        imageIds.push(image.id)
      }

      return api.post<HealthCheckAccepted>(`/v1/plants/${plantId}/health-checks`, {
        json: { image_ids: imageIds, user_note: note },
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: scoped(userId, ['plant', plantId]) })
    },
  })
}
