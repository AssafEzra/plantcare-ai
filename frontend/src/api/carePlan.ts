/* Care plans and their proposals (FINAL section 12).
 *
 * Mirrors app/api/routers/care.py. Only two of these routes change what a plant is
 * actually scheduled to do, and both require the user: `approve`, and
 * `operational-adjustment` — which itself only produces another proposal to approve.
 * Every other route either reads or queues something that sits there until somebody
 * looks at it.
 *
 * Proposing is a 202: the Care Agent took 105 seconds on its first live run, so the
 * caller polls `/v1/agent-requests/{id}` through `useAgentRequest` and stays with it.
 * The Streamlit build promised the proposal "will appear here in a moment" and then
 * never looked again, so a failed run left the user on the empty state that had
 * invited them to press the button.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { scoped } from '../lib/queryKeys'
import { useAuth } from '../auth/context'
import type { CarePlanVersion } from './plantDetail'

export type ProposalAccepted = {
  agent_request_id: string
  status: string
  replayed: boolean
}

export type ApprovalResult = {
  version_id: string
  version_number: number
  [key: string]: unknown
}

export type AdjustmentResult = {
  version_id: string
  [key: string]: unknown
}

/** The reasons a proposal can be raised. `HEALTH_DRIVEN` has its own endpoint. */
export type ProposalReason = 'INITIAL_PLAN' | 'ENVIRONMENT_CHANGE' | 'RE_IDENTIFICATION'

export function useProposals(plantId: string | undefined, enabled: boolean) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['plant', plantId, 'proposals']),
    queryFn: () => api.get<CarePlanVersion[]>(`/v1/plants/${plantId}/care-plan/proposals`),
    enabled: Boolean(plantId) && enabled,
  })
}

function useInvalidatePlan(plantId: string | undefined) {
  const queryClient = useQueryClient()
  const { userId } = useAuth()

  return () => {
    queryClient.invalidateQueries({ queryKey: scoped(userId, ['plant', plantId]) })
    queryClient.invalidateQueries({ queryKey: scoped(userId, ['plants']) })
    queryClient.invalidateQueries({ queryKey: scoped(userId, ['dashboard']) })
  }
}

export function useRequestProposal(plantId: string | undefined) {
  const invalidate = useInvalidatePlan(plantId)
  return useMutation({
    mutationFn: (reason: ProposalReason) =>
      api.post<ProposalAccepted>(`/v1/plants/${plantId}/care-plan/proposals`, {
        json: { reason },
      }),
    onSuccess: invalidate,
  })
}

/**
 * A health finding asking for the plan to be revisited (FINAL section 16).
 *
 * The Health Agent cannot touch the plan. This raises a HEALTH_DRIVEN proposal the
 * user then approves, which is the only route there is from a finding to a schedule.
 */
export function useRequestHealthAdjustment(plantId: string | undefined) {
  const invalidate = useInvalidatePlan(plantId)
  return useMutation({
    mutationFn: (assessmentId: string) =>
      api.post<ProposalAccepted>(`/v1/plants/${plantId}/care-plan/adjustment-proposals`, {
        json: {
          health_assessment_id: assessmentId,
          reason: 'ממצאי בדיקת הבריאות מצביעים על צורך בהתאמת התדירות.',
        },
      }),
    onSuccess: invalidate,
  })
}

export function useApproveProposal(plantId: string | undefined) {
  const invalidate = useInvalidatePlan(plantId)
  return useMutation({
    mutationFn: (versionId: string) =>
      api.post<ApprovalResult>(`/v1/care-plan-proposals/${versionId}/approve`),
    onSuccess: invalidate,
  })
}

export function useRejectProposal(plantId: string | undefined) {
  const invalidate = useInvalidatePlan(plantId)
  return useMutation({
    mutationFn: (versionId: string) =>
      api.post(`/v1/care-plan-proposals/${versionId}/reject`, { json: {} }),
    onSuccess: invalidate,
  })
}

/**
 * Change frequency, time or reminders. No model call, no advice rewritten.
 *
 * Produces a new PROPOSED version carrying the professional recommendations
 * byte-identical from the source, which the user still approves — skipping approval
 * here would make an operational tweak the one way to change the active plan without
 * saying yes to it.
 */
export function useAdjustPlan(plantId: string | undefined) {
  const invalidate = useInvalidatePlan(plantId)
  return useMutation({
    mutationFn: ({
      versionId,
      overrides,
      summary,
    }: {
      versionId: string
      overrides: Record<string, { interval_days: number }>
      summary: string
    }) =>
      api.post<AdjustmentResult>(`/v1/care-plan-versions/${versionId}/operational-adjustment`, {
        json: { operational_preferences: overrides, change_summary: summary },
      }),
    onSuccess: invalidate,
  })
}

/**
 * What is still missing before an adjustment can be saved.
 *
 * Returns the sentence to show, or null when the button should be live. A value
 * rather than a string buried in a render branch, and the two conditions are told
 * apart: a user who described a change but moved no number needs different words from
 * one who did the opposite. Reported from real use as "it wont let you save" — both
 * rules were real, and the screen enforced them in silence.
 */
export function whyNotSaveable(
  overrides: Record<string, unknown>,
  summary: string,
): string | null {
  const moved = Object.keys(overrides).length > 0
  const described = summary.trim().length > 0
  if (!moved && !described) return 'יש לשנות תדירות של טיפול אחד לפחות ולתאר את השינוי כדי לשמור.'
  if (!moved) return 'יש לשנות תדירות של טיפול אחד לפחות כדי לשמור.'
  if (!described) return 'יש לתאר את השינוי כדי לשמור.'
  return null
}
