/* Professional information about a species, and reporting an error in it.
 *
 * Mirrors the two user-facing routes in app/api/routers/knowledge.py. The rest of
 * that file is the admin review queue, which belongs to phase 6.
 *
 * FINAL section 10: users read and report; they never edit. There is no write path
 * here beyond the report, and that is the whole shape of the feature.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { scoped } from '../lib/queryKeys'
import { useAuth } from '../auth/context'
import { ApiError } from '../lib/errors'

export type KnowledgeSource = {
  id: string
  source_class: string
  title: string | null
  url: string | null
  publisher: string | null
  retrieved_at: string | null
  notes: string | null
}

export type Knowledge = {
  id: string
  species_id: string
  language: string
  version_number: number
  /* "published" or "pending". A pending article is finished research no
     administrator has approved, and it carries no sources — source verification is
     part of the review it has not had. */
  review: 'published' | 'pending'
  content: Record<string, { text?: string } | string | null>
  source_summary: Record<string, unknown>
  published_at: string
  sources: KnowledgeSource[]
}

/**
 * The current article for a species.
 *
 * A 404 is an ordinary outcome — the research may still be running — so it is not
 * retried and the screen says "being prepared" rather than showing an error. Any
 * other failure is a real one and reaches `Async` as normal.
 */
export function useKnowledge(speciesId: string | null | undefined) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: scoped(userId, ['knowledge', speciesId]),
    queryFn: () => api.get<Knowledge>(`/v1/species/${speciesId}/knowledge`),
    enabled: Boolean(speciesId),
    retry: (count, error) => {
      if (error instanceof ApiError && error.status === 404) return false
      return count < 2
    },
  })
}

export function isNotPrepared(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}

/** FINAL section 10: users report errors; they never edit. */
export function useReportKnowledgeError(speciesId: string | null | undefined) {
  return useMutation({
    mutationFn: ({ plantId, text }: { plantId: string; text: string }) =>
      api.post(`/v1/species/${speciesId}/knowledge-reports`, {
        json: { plant_id: plantId, report_text: text },
      }),
  })
}

/** The article's prose, in the order section 10 defines, skipping empty sections. */
export function readSection(
  content: Knowledge['content'],
  name: string,
): string | null {
  const section = content?.[name]
  if (!section) return null
  const text = typeof section === 'string' ? section : section.text
  return text?.trim() || null
}

/**
 * Research this plant's species again, after a run that failed.
 *
 * The only research call a non-administrator can make, and it is narrow by design:
 * the API refuses anything but a plant of yours, waiting, whose newest draft is
 * FAILED. It exists because a failed run otherwise strands the plant in
 * KNOWLEDGE_PENDING with nothing on screen admitting it - and with the care plan
 * button beside it offering work that cannot succeed, since the Care Agent plans
 * from knowledge that was never published.
 */
export function useRetryResearch(plantId: string | undefined) {
  const queryClient = useQueryClient()
  const { userId } = useAuth()

  return useMutation({
    mutationFn: () =>
      api.post<{ draft_id: string; agent_request_id: string; already_running: boolean }>(
        `/v1/plants/${plantId}/knowledge/research`,
      ),
    onSuccess: () => {
      // The plant leaves KNOWLEDGE_PENDING on its own when the run lands; the tray
      // watches the request. These two just stop the page showing the old failure.
      queryClient.invalidateQueries({ queryKey: scoped(userId, ['plant', plantId]) })
      queryClient.invalidateQueries({ queryKey: scoped(userId, ['plants']) })
    },
  })
}
