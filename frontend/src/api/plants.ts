/* Plants.
 *
 * Mirrors PlantResponse in app/api/schemas/plants.py. `thumbnail_url`,
 * `species_name`, `awaiting_confirmation` and `next_task` are filled in by the list
 * endpoint only — it batches those lookups across every plant at once — so a
 * single-plant read leaves them null by design.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
  /* Position in the owner's list. Not unique per user, so never used as a key —
     the list arrives sorted, and this exists so a drag can send the order back. */
  display_order: number
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

/**
 * Save the order the user dragged the list into.
 *
 * The whole list every time, which is what the endpoint requires: a drag shifts
 * everything after the thing moved, and a partial list would leave the rest at
 * whatever number they had.
 *
 * Written into the cache before the request goes, and the server's answer replaces
 * it afterwards. Without that the plant snaps back to where it was for as long as
 * the round trip takes, which reads as the drag having failed — and the user drags
 * again.
 */
export function useReorderPlants() {
  const { userId } = useAuth()
  const client = useQueryClient()

  return useMutation({
    mutationFn: (plantIds: string[]) =>
      api.put<Plant[]>('/v1/plants/order', { json: { plant_ids: plantIds } }),
    onMutate: async (plantIds: string[]) => {
      const key = scoped(userId, ['plants'])
      await client.cancelQueries({ queryKey: key })

      const previous = client.getQueriesData<Plant[]>({ queryKey: key })
      for (const [queryKey, plants] of previous) {
        if (!plants) continue
        const byId = new Map(plants.map((plant) => [plant.id, plant]))
        const reordered = plantIds
          .map((id, index) => {
            const plant = byId.get(id)
            /* `display_order` is rewritten, not just the array order. The screen
               sorts by this field, so an array in the new order carrying the old
               numbers is re-sorted straight back to where it started - which looks
               exactly like the drag having been rejected. */
            return plant ? { ...plant, display_order: index + 1 } : undefined
          })
          .filter((plant): plant is Plant => plant !== undefined)
        /* Only when the drag covers exactly this cached list. A filtered or
           searched view holds a subset, and reordering it from a full list would
           drop every plant the filter had hidden. */
        if (reordered.length === plants.length) client.setQueryData(queryKey, reordered)
      }

      return { previous }
    },
    onError: (_error, _plantIds, context) => {
      for (const [queryKey, plants] of context?.previous ?? []) {
        client.setQueryData(queryKey, plants)
      }
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: scoped(userId, ['plants']) })
    },
  })
}
