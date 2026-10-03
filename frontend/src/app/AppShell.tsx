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

import { NavLink, Outlet, useLocation } from 'react-router-dom'
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
  const path = useLocation().pathname

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
                  end
                  className={`pc-navlink${isCurrent(item.to, path) ? ' active' : ''}`}
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
                end
                className={`pc-tab${isCurrent(item.to, path) ? ' active' : ''}`}
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

/**
 * Which tab owns the current URL.
 *
 * `NavLink`'s own matching cannot express this. The collection lives at "/", so
 * without `end` it would match every page in the app; with `end` it stops matching
 * "/plants/<id>", and a plant's own page would light up no tab at all — the one place
 * a reader most wants to know where they are. A plant belongs to the collection, and
 * "/plants/new" belongs to the tab that points at it, not to the collection.
 */
function isCurrent(to: string, path: string): boolean {
  if (to === '/') return path === '/' || (path.startsWith('/plants/') && path !== '/plants/new')
  return path === to || path.startsWith(`${to}/`)
}
