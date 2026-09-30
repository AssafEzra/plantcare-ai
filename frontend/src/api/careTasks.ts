/* Care tasks and the Home dashboard payload.
 *
 * Types mirror TaskResponse / DashboardResponse in app/api/routers/care_tasks.py.
 * Only what phase 4 needs is bound here; phase 5 adds done/skip and the rest of the
 * dashboard.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { scoped } from '../lib/queryKeys'
import { useAuth } from '../auth/context'

export type CareTaskStatus = 'PENDING' | 'DONE' | 'SKIPPED' | 'OVERDUE' | 'CANCELLED'

export type CareTask = {
  id: string
  plant_id: string
  care_rule_id: string
  due_at_utc: string
  status: CareTaskStatus
  overdue_since: string | null
  completed_at: string | null
  plant_name: string | null
  action_type: string | null
}

export type OverdueSummary = {
  plant_id: string
  plant_name: string
  action_types: string[]
  count: number
  days_late: number
}

export type Dashboard = {
  today_care: CareTask[]
  upcoming_care: CareTask[]
  overdue_summary: OverdueSummary[]
  plants_needing_attention: Record<string, unknown>[]
  my_plants: Record<string, unknown>[]
  counts: {
    today_tasks: number
    attention: number
    active_plants: number
    overdue: number
  }
}

/* Ported from ACTION_LABELS in app/ui/components/care_plan.py. The Streamlit build
   pairs each with a Material icon name; those are Streamlit-specific and are not
   carried over. */
export const ACTION_LABELS: Record<string, string> = {
  WATERING: 'השקיה',
  FERTILIZING: 'דישון',
  REPOTTING: 'החלפת עציץ',
  PRUNING: 'גיזום',
  MISTING: 'ריסוס',
  ROTATING: 'סיבוב',
  INSPECTION: 'בדיקה',
}

export function actionLabel(actionType: string | null): string {
  if (!actionType) return 'טיפול'
  return ACTION_LABELS[actionType] ?? actionType
}

export function useDashboard() {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['dashboard']),
    queryFn: () => api.get<Dashboard>('/v1/dashboard'),
    enabled: Boolean(userId),
  })
}

/* --- actions -------------------------------------------------------------- */

/* Streamlit re-ran the whole script after every interaction, so a completed task
 * simply reappeared with its new status. React has to say so. Every mutation here
 * invalidates the reads that the write can change — the dashboard (counts, today's
 * list) and the plant list (each card shows its next task).
 *
 * The audit named this as a migration gap; forgetting it produces a screen that
 * looks broken in a specific way: the press works, the row does not move.
 *
 * The body is `{}` rather than omitted. ActionRequest carries an optional note, and
 * the Streamlit build hit a 422 on every press by sending nothing at all.
 */
function useTaskAction(action: 'done' | 'skip') {
  const queryClient = useQueryClient()
  const { userId } = useAuth()

  return useMutation({
    mutationFn: ({ taskId, note }: { taskId: string; note?: string }) =>
      api.post(`/v1/care-tasks/${taskId}/${action}`, { json: note ? { note } : {} }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: scoped(userId, ['dashboard']) })
      queryClient.invalidateQueries({ queryKey: scoped(userId, ['plants']) })
    },
  })
}

export const useCompleteTask = () => useTaskAction('done')
export const useSkipTask = () => useTaskAction('skip')
