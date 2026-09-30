/* Route table.
 *
 * Section 40: Streamlit's URLs were never meaningful, so nothing is preserved here.
 * The structure is the one the flows imply — plants are a collection with a detail
 * view, and adding one is a step inside that collection rather than a top-level
 * destination (section 11 removes the separate "add plant" tab).
 *
 * /auth sits outside both the guard and the shell: signing in has no navigation.
 */

import { Routes, Route, Navigate } from 'react-router-dom'
import AppShell from './app/AppShell'
import RequireAuth from './auth/RequireAuth'
import Auth from './pages/Auth'
import Placeholder from './pages/Placeholder'
import Home from './pages/Home'
import More from './pages/More'

export default function App() {
  return (
    <Routes>
      <Route path="/auth" element={<Auth />} />

      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route index element={<Home />} />
          <Route path="plants">
            <Route index element={<Placeholder title="הצמחים שלי" />} />
            <Route path="new" element={<Placeholder title="הוספת צמח" />} />
            <Route path=":plantId" element={<Placeholder title="הצמח שלי" />} />
          </Route>
          <Route path="health" element={<Placeholder title="בריאות" />} />
          <Route path="more" element={<More />} />
          <Route path="settings" element={<Placeholder title="הגדרות" />} />
          <Route
            path="admin"
            element={<Placeholder title="ניהול" note="פאנל הניהול יועבר בשלב 6." />}
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  )
}
