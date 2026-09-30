/* Route table.
 *
 * Section 40: Streamlit's URLs were never meaningful, so nothing is being preserved
 * here. The structure below is the one the flows imply — plants are a collection
 * with a detail view, and adding one is a step inside that collection rather than a
 * top-level destination (section 11 removes the separate "add plant" tab).
 *
 * /auth sits outside the shell: signing in has no navigation.
 */

import { Routes, Route, Navigate } from 'react-router-dom'
import AppShell from './app/AppShell'
import Placeholder from './pages/Placeholder'
import More from './pages/More'

export default function App() {
  return (
    <Routes>
      <Route path="/auth" element={<Placeholder title="כניסה" note="יועבר בשלב 5." />} />

      <Route element={<AppShell />}>
        <Route index element={<Placeholder title="בית" />} />
        <Route path="plants">
          <Route index element={<Placeholder title="הצמחים שלי" />} />
          <Route path="new" element={<Placeholder title="הוספת צמח" />} />
          <Route path=":plantId" element={<Placeholder title="הצמח שלי" />} />
        </Route>
        <Route path="health" element={<Placeholder title="בריאות" />} />
        <Route path="more" element={<More />} />
        <Route path="settings" element={<Placeholder title="הגדרות" />} />
        <Route path="admin" element={<Placeholder title="ניהול" note="פאנל הניהול יועבר בשלב 6." />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
