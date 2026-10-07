import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { MutationCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'

import './styles/tokens.css'
import './styles/base.css'
import './styles/components.css'
import App from './App'
import { AuthProvider } from './auth/AuthProvider'

/* The query cache is created here, once.
 *
 * Its key discipline matters more than it looks: the Streamlit build keys its cache
 * on the acting identity *including the view-as target* (app/ui/state/api_client.py),
 * and an admin impersonating a user would otherwise be served their own cached data.
 * Phase 3 carries that rule over when the API client lands — see
 * docs/MIGRATION_AUDIT.md section 4.
 */
/* Starting an agent has to reach the watcher.
 *
 * `useOpenAgentRequests` polls while the open list is non-empty and stops when it
 * empties - which is what keeps an idle app silent. The consequence is that when
 * the list is empty nothing is asking, so a run begun from a screen would never
 * be noticed: the tray stayed shut for a health check that was genuinely running.
 *
 * One rule, here, rather than a line in each mutation: a response carrying an
 * `agent_request_id` means a run just began, so the open list is stale. Every
 * agent-starting endpoint returns one by contract (API_CONTRACTS, the 202-and-poll
 * pattern), so a fifth agent is covered the day it is added rather than the day
 * someone remembers.
 */
function startedAnAgent(data: unknown): boolean {
  return typeof data === 'object' && data !== null && 'agent_request_id' in data
}

let queryClient: QueryClient

const mutationCache = new MutationCache({
  onSuccess: (data) => {
    if (!startedAnAgent(data)) return
    void queryClient.invalidateQueries({
      predicate: (entry) => entry.queryKey.includes('agent-requests'),
    })
  },
})

queryClient = new QueryClient({
  mutationCache,
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
