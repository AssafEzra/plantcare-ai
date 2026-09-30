/* Route guard.
 *
 * Hiding a route is a convenience, never the control — every endpoint behind these
 * screens is independently gated server-side, and admin tables have their own RLS
 * policies on top. The same principle the Streamlit admin page states in its own
 * docstring applies here.
 *
 * The `loading` check matters: redirecting before the first session lookup resolves
 * would bounce a signed-in user to the sign-in screen on every page load.
 */

import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from './context'

export default function RequireAuth() {
  const { session, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div className="pc-authgate" role="status" aria-live="polite">
        <span className="pc-sr-only">טוען…</span>
      </div>
    )
  }

  if (!session) {
    // Remember where they were headed, so sign-in can return them there.
    return <Navigate to="/auth" replace state={{ from: location.pathname }} />
  }

  return <Outlet />
}
