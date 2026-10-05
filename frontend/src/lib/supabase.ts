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

/* Is this the installed app rather than a browser tab?
 *
 * `display-mode: standalone` is the standard answer and is what the manifest asks for
 * (vite.config.ts). `navigator.standalone` is Safari's own flag, which predates the
 * media query and is still the only one an iPhone home-screen app sets. Either is
 * enough; neither exists outside a browser, hence the optional calls. */
function isInstalled(): boolean {
  const standalone = window.matchMedia?.('(display-mode: standalone)').matches ?? false
  const ios = (window.navigator as Navigator & { standalone?: boolean }).standalone === true
  return standalone || ios
}

export const supabase = createClient(url, anonKey, {
  auth: {
    // The browser does natively what session_store.py was built to fake under
    // Streamlit: persist the session and refresh it before it expires.
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
    /* Where that persisted session lives, which decides how long being signed in
       lasts. `localStorage` survives closing the browser, so in a tab it meant the
       next person to open the page was whoever last used it - on a shared computer
       that is the wrong default. `sessionStorage` dies with the tab.

       The installed app keeps `localStorage`: it is a single-user surface on someone's
       own phone, and asking for a password on every launch is what makes an installed
       app feel worse than the site. On iOS the two are separate stores anyway, so the
       home-screen app signing in does not sign in Safari. */
    storage: isInstalled() ? window.localStorage : window.sessionStorage,
  },
})
