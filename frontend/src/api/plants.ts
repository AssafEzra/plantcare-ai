/* Plants.
 *
 * Mirrors PlantResponse in app/api/schemas/plants.py. `thumbnail_url`,
 * `species_name`, `awaiting_confirmation` and `next_task` are filled in by the list
 * endpoint only — it batches those lookups across every plant at once — so a
 * single-plant read leaves them null by design.
 */

import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { scoped } from '../lib/queryKeys'
import { useAuth } from '../auth/context'
import type { HealthStatus } from '../lib/status'

export type PlantStatus =
  | 'PENDING_IDENTIFICATION'
  | 'IDENTIFIED'
  | 'KNOWLEDGE_PENDING'
  | 'ACTIVE'
  | 'ARCHIVED'

export type NextTask = {
  id: string
  action_type: string
  due_at_utc: string
  status: string
}

export type Plant = {
  id: string
  name: string | null
  species_id: string | null
  status: PlantStatus
  current_health_status: HealthStatus
  main_image_id: string | null
  notes: string | null
  archived_at: string | null
  created_at: string
  updated_at: string
  thumbnail_url: string | null
  species_name: string | null
  awaiting_confirmation: boolean
  next_task: NextTask | null
}

export type PlantFilters = {
  status?: PlantStatus
  health_status?: HealthStatus
  q?: string
}

export function usePlants(filters: PlantFilters = {}) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['plants', filters]),
    queryFn: () => api.get<Plant[]>('/v1/plants', { params: filters }),
    enabled: Boolean(userId),
  })
}

/** The name to show: the personal one, else the species, else a fallback. */
export function plantName(plant: Plant): string {
  return plant.name?.trim() || plant.species_name?.trim() || 'צמח ללא שם'
}
