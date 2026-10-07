/* The administrator's endpoints (FINAL section 29).
 *
 * Mirrors app/api/routers/admin.py and the admin half of knowledge.py.
 *
 * Reaching these screens at all requires an ADMIN role, but that is a courtesy:
 * the navigation entry is hidden for other users while every admin route depends on
 * `AdminDep` and every admin table carries its own `is_admin()` RLS policy. Hiding
 * UI is never the control — the dependency produces a clean 403, and the policy is
 * what makes a forgotten dependency a non-event rather than a breach.
 *
 * Reads that report on work happening elsewhere are given `staleTime: 0`. The rest of
 * the panel changes when an administrator changes it, and a write invalidates it on
 * the way out; agent executions and requests do not work that way, and serving them
 * from a cache showed an administrator the state from before the research they had
 * just started — whose reasonable conclusion was that the request never went.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { scoped } from '../lib/queryKeys'
import { useAuth } from '../auth/context'

/* --- types ---------------------------------------------------------------- */

export type AgentStats = {
  agent_type: string
  total: number
  failed: number
  estimated_cost: number
  average_latency_ms: number
}

export type Overview = {
  window_days: number
  drafts_awaiting_review: number
  open_knowledge_reports: number
  failed_agent_requests: number
  failed_notifications: number
  agent_stats: AgentStats[]
  total_estimated_cost: number
  /* How many executions in the window carry no cost at all, so the total reads as
     the floor it is rather than as a complete figure. */
  executions_missing_cost: number
}

export type DraftStatus =
  | 'DRAFT'
  | 'RESEARCHING'
  | 'READY_FOR_REVIEW'
  | 'APPROVED'
  | 'REJECTED'
  | 'FAILED'

export type KnowledgeSection = { text?: string; confidence?: number }

export type KnowledgeDraft = {
  id: string
  species_id: string
  species_scientific_name: string | null
  species_common_name: string | null
  language: string
  status: DraftStatus
  research_request_id: string | null
  content: {
    sections?: Record<string, KnowledgeSection>
    sources?: Record<string, unknown>[]
    [key: string]: unknown
  } | null
  research_notes: string | null
  admin_note: string | null
  created_at: string
  updated_at: string
}

export type CatalogueEntry = {
  id: string
  species_id: string
  scientific_name: string
  common_name: string | null
  language: string
  version_number: number
  published_at: string
  plant_count: number
  /* The species' draft that is still in play, if it has one. The research route
     answers with a 409; this is what stops an administrator meeting one. */
  open_draft_status: DraftStatus | null
}

export type VersionDetail = {
  id: string
  species_id: string
  language: string
  version_number: number
  is_current: boolean
  published_by: string | null
  published_at: string
  content: Record<string, KnowledgeSection | string>
  source_summary: Record<string, unknown>
  sources: {
    id: string
    source_class: string
    title: string | null
    url: string | null
    publisher: string | null
    notes: string | null
  }[]
}

export type VersionSummary = {
  id: string
  species_id: string
  language: string
  version_number: number
  is_current: boolean
  published_at: string
}

export type ApprovedSource = {
  id: string
  name: string
  domain: string
  source_type: string | null
  reliability_level: number | null
  notes: string | null
  is_enabled: boolean
}

export type KnowledgeReport = {
  id: string
  user_id: string
  plant_id: string | null
  species_id: string | null
  knowledge_version_id: string | null
  report_text: string
  status: string
  admin_note: string | null
  created_at: string
}

export type AgentExecution = {
  id: string
  agent_request_id: string
  agent_type: string
  model: string
  prompt_version: string
  status: string
  attempt: number
  /* Null means unknown, not zero: a call that failed after the model generated, and
     a model with no price in its provider's table, both leave these genuinely
     unknown. Rendering either as 0 restates the understatement this distinction
     exists to remove. */
  input_tokens: number | null
  output_tokens: number | null
  estimated_cost: number | null
  latency_ms: number
  error_code: string | null
  error_message: string | null
  created_at: string
}

export type AgentRequestSummary = {
  id: string
  user_id: string
  plant_id: string | null
  agent_type: string
  status: string
  stage: string | null
  error_code: string | null
  created_at: string
}

export type AdminDelivery = {
  id: string
  user_id: string
  status: string
  dedupe_key: string
  scheduled_at: string
  sent_at: string | null
  error_message: string | null
}

export type AuditEntry = {
  id: string
  admin_user_id: string | null
  action: string
  target_table: string | null
  target_id: string | null
  payload: Record<string, unknown> | null
  created_at: string
}

export type Account = {
  id: string
  email: string | null
  display_name: string | null
  role: string
  is_active: boolean
  anonymized_at: string | null
  created_at: string
}

/* --- reads ---------------------------------------------------------------- */

function useAdminQuery<T>(key: readonly unknown[], path: string, params?: Record<string, unknown>) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['admin', ...key]),
    queryFn: () => api.get<T>(path, { params: params as never }),
    enabled: Boolean(userId),
  })
}

export function useOverview() {
  return useAdminQuery<Overview>(['overview'], '/v1/admin/overview')
}

export function useDrafts(status: DraftStatus | 'ALL') {
  return useAdminQuery<KnowledgeDraft[]>(
    ['drafts', status],
    '/v1/admin/knowledge-drafts',
    status === 'ALL' ? undefined : { status },
  )
}

export function useCatalogue(q: string) {
  return useAdminQuery<CatalogueEntry[]>(
    ['catalogue', q],
    '/v1/admin/knowledge-versions',
    q ? { q } : undefined,
  )
}

export function useVersionDetail(versionId: string | null) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['admin', 'version', versionId]),
    queryFn: () => api.get<VersionDetail>(`/v1/admin/knowledge-versions/detail/${versionId}`),
    enabled: Boolean(versionId),
  })
}

export function useSpeciesVersions(speciesId: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['admin', 'species-versions', speciesId]),
    queryFn: () => api.get<VersionSummary[]>(`/v1/admin/knowledge-versions/${speciesId}`),
    enabled: Boolean(speciesId),
  })
}

export function useApprovedSources() {
  return useAdminQuery<ApprovedSource[]>(['approved-sources'], '/v1/admin/approved-sources')
}

export function useKnowledgeReports(status = 'OPEN') {
  return useAdminQuery<KnowledgeReport[]>(['reports', status], '/v1/admin/knowledge-reports', {
    status,
  })
}

/** Live, not cached — see the module comment. */
function useLiveQuery<T>(key: readonly unknown[], path: string, params: Record<string, unknown>) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['admin', ...key]),
    queryFn: () => api.get<T>(path, { params: params as never }),
    enabled: Boolean(userId),
    staleTime: 0,
  })
}

export function useAgentExecutions(failuresOnly: boolean) {
  return useLiveQuery<AgentExecution[]>(
    ['executions', failuresOnly],
    '/v1/admin/agent-executions',
    failuresOnly ? { limit: 50, status: 'FAILED' } : { limit: 50 },
  )
}

export function useAgentRequests(failuresOnly: boolean) {
  return useLiveQuery<AgentRequestSummary[]>(
    ['agent-requests', failuresOnly],
    '/v1/admin/agent-requests',
    failuresOnly ? { limit: 50, status: 'FAILED' } : { limit: 50 },
  )
}

export function useAdminDeliveries(failuresOnly: boolean) {
  return useAdminQuery<AdminDelivery[]>(
    ['deliveries', failuresOnly],
    '/v1/admin/notification-deliveries',
    failuresOnly ? { limit: 50, status: 'FAILED' } : { limit: 50 },
  )
}

export function useAuditLog() {
  return useAdminQuery<AuditEntry[]>(['audit-log'], '/v1/admin/audit-log', { limit: 50 })
}

export function useAccounts(q: string) {
  return useAdminQuery<Account[]>(['accounts', q], '/v1/admin/accounts', q ? { q } : undefined)
}

/* --- writes --------------------------------------------------------------- */

/**
 * Everything an administrative write can make stale.
 *
 * Coarse on purpose: the panel is one screen with nine tabs, an approval moves the
 * draft *and* the catalogue *and* the overview counters *and* the audit log, and an
 * admin acting on a stale list is how the same draft gets approved twice.
 */
function useInvalidateAdmin() {
  const queryClient = useQueryClient()
  const { userId } = useAuth()
  return () => queryClient.invalidateQueries({ queryKey: scoped(userId, ['admin']) })
}

export type ApprovalResult = { version_number: number; active_plants: number }

export function useApproveDraft() {
  const invalidate = useInvalidateAdmin()
  return useMutation({
    mutationFn: (draftId: string) =>
      api.post<ApprovalResult>(`/v1/admin/knowledge-drafts/${draftId}/approve`, { json: {} }),
    onSuccess: invalidate,
  })
}

export function useRejectDraft() {
  const invalidate = useInvalidateAdmin()
  return useMutation({
    mutationFn: ({ draftId, note }: { draftId: string; note: string }) =>
      api.post(`/v1/admin/knowledge-drafts/${draftId}/reject`, { json: { admin_note: note } }),
    onSuccess: invalidate,
  })
}

export function useRetryDraft() {
  const invalidate = useInvalidateAdmin()
  return useMutation({
    mutationFn: ({ draftId, reason }: { draftId: string; reason: string | null }) =>
      api.post(`/v1/admin/knowledge-drafts/${draftId}/retry`, { json: { reason } }),
    onSuccess: invalidate,
  })
}

export function useResearchSpecies() {
  const invalidate = useInvalidateAdmin()
  return useMutation({
    mutationFn: ({
      speciesId,
      reason,
      language,
    }: {
      speciesId: string
      reason: string
      language: string
    }) =>
      api.post(`/v1/admin/species/${speciesId}/knowledge/research`, {
        json: { reason, language },
      }),
    onSuccess: invalidate,
  })
}

export function useCreateSource() {
  const invalidate = useInvalidateAdmin()
  return useMutation({
    mutationFn: (body: { name: string; domain: string; reliability_level: number }) =>
      api.post<ApprovedSource>('/v1/admin/approved-sources', { json: body }),
    onSuccess: invalidate,
  })
}

/**
 * Disabling and re-enabling are not the same route.
 *
 * `POST /disable` exists because switching a source off is an event worth auditing,
 * while turning it back on is an ordinary field change. Disabling deliberately does
 * not touch existing provenance rows: they record what was true when a version
 * published.
 */
export function useSetSourceEnabled() {
  const invalidate = useInvalidateAdmin()
  return useMutation({
    mutationFn: ({ sourceId, enabled }: { sourceId: string; enabled: boolean }) =>
      enabled
        ? api.patch(`/v1/admin/approved-sources/${sourceId}`, { json: { is_enabled: true } })
        : api.post(`/v1/admin/approved-sources/${sourceId}/disable`),
    onSuccess: invalidate,
  })
}

export function useReviewReport() {
  const invalidate = useInvalidateAdmin()
  return useMutation({
    mutationFn: ({ reportId, status }: { reportId: string; status: string }) =>
      api.post(`/v1/admin/knowledge-reports/${reportId}/review`, { json: { status } }),
    onSuccess: invalidate,
  })
}

/** Records the audit entry. Entering the mode itself is `lib/viewAs`. */
export function useStartViewAs() {
  return useMutation({
    mutationFn: (userId: string) => api.post<Account>(`/v1/admin/accounts/${userId}/view-as`),
  })
}

export function useAnonymizeAccount() {
  const invalidate = useInvalidateAdmin()
  return useMutation({
    mutationFn: ({ accountId, reason }: { accountId: string; reason: string }) =>
      api.post<Account>(`/v1/admin/accounts/${accountId}/anonymize`, { json: { reason } }),
    onSuccess: invalidate,
  })
}
