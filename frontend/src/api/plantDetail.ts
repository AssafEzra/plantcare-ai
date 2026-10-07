/* The plant dashboard view model, its images, its environment and its timeline.
 *
 * Mirrors app/api/routers/plant_detail.py, plant_images.py and the environment half
 * of plants.py.
 *
 * Everything above the timeline arrives in one `GET /v1/plants/{id}/dashboard`, for
 * the same reason Home has its own aggregate: this is a page opened often, and eight
 * sequential round trips would be felt on every visit. The timeline is separate and
 * deliberately not fetched until asked for — it sits below everything else on a long
 * page, and in the Streamlit build fetching it on every rerun cost about a second of
 * the 5.7 a single click spent on the API.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { scoped } from '../lib/queryKeys'
import { useAuth } from '../auth/context'
import type { CareTask } from './careTasks'
import type { PlantStatus } from './plants'
import type { HealthStatus, HealthTrend } from '../lib/status'
import type { CareIntensity, CareScheduleSummary } from '../lib/careSchedule'

/* --- types ---------------------------------------------------------------- */

export type GalleryImage = {
  id: string
  url: string | null
  thumbnail_url: string | null
  context_type: 'gallery' | 'identification' | 'health'
  is_main: boolean
  created_at: string
}

export type SpeciesSummary = {
  id: string
  scientific_name: string
  common_name: string | null
}

export type PendingCandidate = {
  id: string
  scientific_name: string
  common_name: string | null
  rank: number
  confidence_score: number | null
}

export type PendingIdentification = {
  id: string
  confidence_level: string | null
  image_quality: string | null
  created_at: string
  candidates: PendingCandidate[]
}

export type HealthSummary = {
  current_status: HealthStatus
  latest_assessment_id: string | null
  latest_assessed_at: string | null
  trend: HealthTrend | null
  requires_attention: boolean
  history: Record<string, unknown>[]
}

export type Environment = {
  plant_id?: string
  location_type: string | null
  light_level: string | null
  light_direction: string | null
  temperature_c: number | null
  humidity_percent: number | null
  room: string | null
  notes: string | null
  updated_at?: string | null
}

export type CareRule = {
  id: string
  action_type: string
  interval_days: number
  preferred_time_local: string
  preferred_weekday: string | null
  instructions: string | null
  is_active: boolean
}

export type CarePlanVersion = {
  id: string
  care_plan_id: string
  version_number: number
  knowledge_version_id: string | null
  knowledge_draft_id: string | null
  knowledge_review: 'reviewed' | 'pending' | 'rejected'
  status: string
  professional_recommendations: {
    summary?: string
    watering?: string
    light?: string
    feeding?: string
    seasonal_notes?: string
    warnings?: string[]
    [key: string]: unknown
  }
  operational_preferences: Record<string, unknown> | null
  change_summary: string | null
  source_type: string
  created_at: string
  rules: CareRule[]
  /* The rules in force, so the approval dialog can show what actually changes.
     Empty for a first plan, which is correct — there is nothing to diff. */
  current_rules: Omit<CareRule, 'id' | 'instructions'>[]
}

export type PlantDashboard = {
  id: string
  name: string | null
  status: PlantStatus
  notes: string | null
  created_at: string
  archived_at: string | null
  species: SpeciesSummary | null
  pending_identification: PendingIdentification | null
  main_image: GalleryImage | null
  gallery: GalleryImage[]
  environment: Environment | null
  health: HealthSummary
  upcoming_tasks: CareTask[]
  care_plan: CarePlanVersion | null
  open_proposals: number
  /** A care proposal already queued or running, raised by anything, including the tick. */
  care_request_id: string | null
  care_schedule: CareScheduleSummary | null
  /* Why the plant is still KNOWLEDGE_PENDING: 'RESEARCHING', 'FAILED', 'REJECTED',
     or null when there is nothing to say. The status alone renders identically for
     all three, so a plant whose research failed waits silently for ever. */
  knowledge_status: string | null
}

export type HistoryEntry = {
  kind: string
  occurred_at: string
  summary: string
  detail: Record<string, unknown>
  source: string
}

/* The images a user thinks of as the plant's gallery. `health` images are evidence
   for one check and are shown with that check, not in the portrait grid — the same
   line migration 0019 draws in the database. */
export const PORTRAIT_CONTEXTS = ['gallery', 'identification'] as const

export function isPortrait(image: GalleryImage): boolean {
  return (PORTRAIT_CONTEXTS as readonly string[]).includes(image.context_type)
}

/* --- reads ---------------------------------------------------------------- */

export function usePlantDashboard(plantId: string | undefined) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['plant', plantId]),
    queryFn: () => api.get<PlantDashboard>(`/v1/plants/${plantId}/dashboard`),
    enabled: Boolean(plantId),
  })
}

export function usePlantHistory(plantId: string | undefined, limit: number, enabled: boolean) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['plant', plantId, 'history', limit]),
    queryFn: () => api.get<HistoryEntry[]>(`/v1/plants/${plantId}/history`, { params: { limit } }),
    enabled: Boolean(plantId) && enabled,
  })
}

/* --- writes --------------------------------------------------------------- */

/**
 * Everything a write to this plant can invalidate.
 *
 * Streamlit re-ran the whole script after each interaction, so a change simply
 * reappeared. React has to say which reads are now stale, and getting it wrong here
 * produces a screen that looks broken in one specific way: the press works, nothing
 * moves. The plant list is included because every card shows a thumbnail, a name and
 * the plant's next task; the Home dashboard because it counts today's work.
 */
function useInvalidatePlant(plantId: string | undefined) {
  const queryClient = useQueryClient()
  const { userId } = useAuth()

  return () => {
    queryClient.invalidateQueries({ queryKey: scoped(userId, ['plant', plantId]) })
    queryClient.invalidateQueries({ queryKey: scoped(userId, ['plants']) })
    queryClient.invalidateQueries({ queryKey: scoped(userId, ['dashboard']) })
  }
}

export function useRenamePlant(plantId: string | undefined) {
  const invalidate = useInvalidatePlant(plantId)
  return useMutation({
    mutationFn: (body: { name: string | null; notes: string | null }) =>
      api.patch(`/v1/plants/${plantId}`, { json: body }),
    onSuccess: invalidate,
  })
}

/**
 * Pin a plant to its own care intensity, or `null` to follow Settings again.
 *
 * Unlike a frequency change this is not a proposal: it applies at once, and the plant's
 * pending tasks move before the response returns. Takes the plant id per call so the
 * Settings warning list can pin any plant it shows.
 */
export function useSetPlantIntensity() {
  const queryClient = useQueryClient()
  const { userId } = useAuth()
  return useMutation({
    mutationFn: ({ plantId, intensity }: { plantId: string; intensity: CareIntensity | null }) =>
      api.patch(`/v1/plants/${plantId}`, { json: { care_intensity: intensity } }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: scoped(userId, ['plant']) })
      queryClient.invalidateQueries({ queryKey: scoped(userId, ['plants']) })
      queryClient.invalidateQueries({ queryKey: scoped(userId, ['dashboard']) })
      queryClient.invalidateQueries({ queryKey: scoped(userId, ['care-impact']) })
    },
  })
}

export function useArchivePlant(plantId: string | undefined) {
  const invalidate = useInvalidatePlant(plantId)
  return useMutation({
    mutationFn: () => api.post(`/v1/plants/${plantId}/archive`),
    onSuccess: invalidate,
  })
}

export function useRestorePlant(plantId: string | undefined) {
  const invalidate = useInvalidatePlant(plantId)
  return useMutation({
    mutationFn: () => api.post(`/v1/plants/${plantId}/restore`),
    onSuccess: invalidate,
  })
}

export function useSaveEnvironment(plantId: string | undefined) {
  const invalidate = useInvalidatePlant(plantId)
  return useMutation({
    mutationFn: (values: Partial<Environment>) =>
      api.put<Environment>(`/v1/plants/${plantId}/environment`, { json: values }),
    onSuccess: invalidate,
  })
}

export function useLogHistoryEvent(plantId: string | undefined) {
  const queryClient = useQueryClient()
  const { userId } = useAuth()

  return useMutation({
    mutationFn: (body: { event_type: string; note: string | null }) =>
      api.post(`/v1/plants/${plantId}/history`, { json: body }),
    onSuccess: () => {
      // The timeline is keyed per page size, so every page of it is now stale.
      queryClient.invalidateQueries({ queryKey: scoped(userId, ['plant', plantId, 'history']) })
    },
  })
}

/* --- images --------------------------------------------------------------- */

export type DeleteOutcome = { outcome: 'deleted' | 'hidden' }

/**
 * Remove an image — or hide it, which is what happens to one the AI has used.
 *
 * FINAL section 20 decides what "delete" means and the endpoint implements it: an
 * image an agent has consumed stays, because an assessment that cited it must remain
 * legible. The caller is told which of the two happened so the user can be told too.
 */
export function useDeleteImage(plantId: string | undefined) {
  const invalidate = useInvalidatePlant(plantId)
  return useMutation({
    mutationFn: (imageId: string) =>
      api.delete<DeleteOutcome>(`/v1/plants/${plantId}/images/${imageId}`),
    onSuccess: invalidate,
  })
}

export function useSetMainImage(plantId: string | undefined) {
  const invalidate = useInvalidatePlant(plantId)
  return useMutation({
    mutationFn: (imageId: string) => api.post(`/v1/plants/${plantId}/images/${imageId}/main`),
    onSuccess: invalidate,
  })
}

/**
 * Set the gallery order.
 *
 * The whole set, in order, every time. The endpoint refuses a partial list — naming
 * only some images would leave the rest at whatever number they had, which is how two
 * sets silently interleave — so the caller sends what the grid currently shows.
 */
export function useReorderImages(plantId: string | undefined) {
  const invalidate = useInvalidatePlant(plantId)
  return useMutation({
    mutationFn: (imageIds: string[]) =>
      api.put(`/v1/plants/${plantId}/images/order`, { json: { image_ids: imageIds } }),
    onSuccess: invalidate,
  })
}

/**
 * Add photographs to the gallery.
 *
 * Sequentially, not in parallel: the API counts uncommitted images per context to
 * enforce its own ceiling, and concurrent uploads race that check.
 */
export function useUploadImages(plantId: string | undefined) {
  const invalidate = useInvalidatePlant(plantId)
  return useMutation({
    mutationFn: async (files: File[]) => {
      for (const file of files) {
        const form = new FormData()
        form.append('file', file)
        form.append('context_type', 'gallery')
        await api.post(`/v1/plants/${plantId}/images`, { body: form })
      }
    },
    onSuccess: invalidate,
  })
}
