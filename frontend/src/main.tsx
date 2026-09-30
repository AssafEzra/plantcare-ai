import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import './styles/tokens.css'
import './styles/base.css'
import App from './App'

/* The query cache is created here, once.
 *
 * Its key discipline matters more than it looks: the Streamlit build keys its cache
 * on the acting identity *including the view-as target* (app/ui/state/api_client.py),
 * and an admin impersonating a user would otherwise be served their own cached data.
 * Phase 3 carries that rule over when the API client lands — see
 * docs/MIGRATION_AUDIT.md section 4.
 */
const queryClient = new QueryClient({
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
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
