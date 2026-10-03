/* Route table.
 *
 * Section 40: Streamlit's URLs were never meaningful, so nothing is preserved here.
 * The structure is the one the flows imply — plants are a collection with a detail
 * view, and adding one is a step inside that collection.
 *
 * "/" is the plant collection, which is what the user opens the app to see. The day's
 * work moved to "/tasks". "/plants" still resolves, redirecting to "/", so a bookmark
 * or a link written before the change keeps working rather than hitting the catch-all.
 *
 * /auth sits outside both the guard and the shell: signing in has no navigation.
 *
 * /admin is guarded here as well as on the server. Every admin route depends on
 * `AdminDep` and every admin table carries its own `is_admin()` policy, so nothing
 * leaks either way — but without this a signed-in user who typed the URL was shown the
 * whole console, nine tabs and a page title, over a single 403 and a "נסו שוב" button
 * that could never succeed.
 */

import { Routes, Route, Navigate } from 'react-router-dom'
import AppShell from './app/AppShell'
import RequireAuth from './auth/RequireAuth'
import Auth from './pages/Auth'
import PlantDashboard from './pages/PlantDashboard'
import Settings from './pages/Settings'
import Admin from './pages/Admin'
import Tasks from './pages/Tasks'
import MyPlants from './pages/MyPlants'
import Health from './pages/Health'
import AddPlant from './pages/AddPlant'
import More from './pages/More'
import { useMe } from './api/profile'

export default function App() {
  return (
    <Routes>
      <Route path="/auth" element={<Auth />} />

      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route index element={<Landing />} />
          <Route path="tasks" element={<Tasks />} />
          <Route path="plants">
            <Route index element={<Navigate to="/" replace />} />
            <Route path="new" element={<AddPlant />} />
            <Route path=":plantId" element={<PlantDashboard />} />
          </Route>
          <Route path="health" element={<Health />} />
          <Route path="more" element={<More />} />
          <Route path="settings" element={<Settings />} />
          <Route path="admin" element={<AdminOnly />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  )
}

/**
 * Where "/" goes.
 *
 * An administrator has no plants of their own, so the collection would be an empty
 * list and an invitation to add one — into the wrong account. They land on the panel
 * instead.
 *
 * `useMe` reports the *acted-as* account under "view as user", so an administrator
 * looking through a user's eyes gets that user's plants, which is the whole point of
 * the mode. While the profile is still loading neither branch is taken: redirecting on
 * an unknown role would bounce a user to a 403 and an admin to an empty screen, and
 * the flash is worse than the wait.
 */
function Landing() {
  const { data: me, isPending } = useMe()
  if (isPending) return null
  return me?.role === 'ADMIN' ? <Navigate to="/admin" replace /> : <MyPlants />
}

/**
 * The admin panel, for administrators.
 *
 * `Landing` makes the opposite decision with the same machinery, and for the same
 * reason it waits on `isPending`: refusing on an unknown role would flash "this area is
 * for administrators" at an actual administrator while their profile loads.
 *
 * A refusal rather than a redirect. Someone who typed /admin asked a question, and
 * being returned silently to their plants does not answer it.
 */
function AdminOnly() {
  const { data: me, isPending } = useMe()
  if (isPending) return null
  if (me?.role !== 'ADMIN') {
    return (
      <p className="pc-formnotice" role="status">
        האזור הזה מיועד למנהלי מערכת בלבד.
      </p>
    )
  }
  return <Admin />
}
