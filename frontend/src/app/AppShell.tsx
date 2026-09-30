/* The application shell: header, desktop sidebar, mobile bottom bar.
 *
 * Section 11:
 *   - Mobile: fixed bottom navigation with exactly four items.
 *   - Desktop: full sidebar, collapsible to icon-only.
 *   - Header: fixed/sticky on both, carrying logo, notifications and user.
 *
 * The split is CSS, not JavaScript — one media query decides which nav renders, so
 * there is no resize listener, no layout flash on first paint, and both navs exist
 * in the DOM for assistive technology to find.
 */

import { NavLink, Outlet } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { navFor } from './nav'
import { useMe } from '../api/profile'
import Header from './Header'
import ViewAsBanner from './ViewAsBanner'
import './AppShell.css'

const COLLAPSED_KEY = 'pc.sidebar.collapsed'

export default function AppShell() {
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(COLLAPSED_KEY) === '1',
  )
  const { data: me } = useMe()

  useEffect(() => {
    localStorage.setItem(COLLAPSED_KEY, collapsed ? '1' : '0')
  }, [collapsed])

  /* Which entries exist is a courtesy, never the control: every admin route is gated
     server-side and every admin table has its own RLS policy. `navFor` explains why an
     administrator is offered the admin entry alone. */
  const { primary, secondary } = navFor(me?.role)
  const sidebarItems = [...primary.filter((item) => item.to !== '/more'), ...secondary]

  return (
    <div className={`pc-shell${collapsed ? ' is-collapsed' : ''}`}>
      <Header onToggleSidebar={() => setCollapsed((c) => !c)} collapsed={collapsed} />

      <aside className="pc-sidebar" aria-label="ניווט ראשי">
        <nav>
          <ul className="pc-navlist">
            {sidebarItems.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.to === '/'}
                  className={({ isActive }) => `pc-navlink${isActive ? ' active' : ''}`}
                >
                  <span className="pc-navicon">{item.icon}</span>
                  <span className="pc-navlabel">{item.label}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </aside>

      <main className="pc-main">
        <div className="pc-content">
          <ViewAsBanner />
          <Outlet />
        </div>
      </main>

      <nav className="pc-bottomnav" aria-label="ניווט תחתון">
        <ul>
          {primary.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) => `pc-tab${isActive ? ' active' : ''}`}
              >
                <span className="pc-tabicon">{item.icon}</span>
                <span className="pc-tablabel">{item.label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  )
}
