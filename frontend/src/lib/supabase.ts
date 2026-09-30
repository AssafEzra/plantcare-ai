/* The Supabase client — used for authentication only.
 *
 * The audit settled section 6's open question: there is no auth router on the API,
 * because the Streamlit build calls Supabase Auth directly from its own session
 * layer (app/ui/state/session.py) on the stated grounds that "obtaining a credential
 * is not a business operation". React does the same. No backend change.
 *
 * This client is NEVER used to read or write application data. PROJECT_STRUCTURE
 * section 7 forbids the UI from calling Supabase for business operations, and that
 * rule survives the migration unchanged: everything else goes through the API, which
 * is where authorization, RLS and the business rules live.
 */

import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

if (!url || !anonKey) {
  throw new Error(
    'VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY are required. Copy .env.example to .env.local.',
  )
}

export const supabase = createClient(url, anonKey, {
  auth: {
    // The browser does natively what session_store.py was built to fake under
    // Streamlit: persist the session and refresh it before it expires.
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
})
