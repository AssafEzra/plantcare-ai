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
import { PRIMARY_NAV, SECONDARY_NAV } from './nav'
import './AppShell.css'

const COLLAPSED_KEY = 'pc.sidebar.collapsed'

export default function AppShell() {
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(COLLAPSED_KEY) === '1',
  )

  useEffect(() => {
    localStorage.setItem(COLLAPSED_KEY, collapsed ? '1' : '0')
  }, [collapsed])

  return (
    <div className={`pc-shell${collapsed ? ' is-collapsed' : ''}`}>
      <Header onToggleSidebar={() => setCollapsed((c) => !c)} collapsed={collapsed} />

      <aside className="pc-sidebar" aria-label="ניווט ראשי">
        <nav>
          <ul className="pc-navlist">
            {[...PRIMARY_NAV.filter((i) => i.to !== '/more'), ...SECONDARY_NAV].map(
              (item) => (
                <li key={item.to}>
                  <NavLink to={item.to} end={item.to === '/'} className={({ isActive }) => `pc-navlink${isActive ? ' active' : ''}`}>
                    <span className="pc-navicon">{item.icon}</span>
                    <span className="pc-navlabel">{item.label}</span>
                  </NavLink>
                </li>
              ),
            )}
          </ul>
        </nav>
      </aside>

      <main className="pc-main">
        <div className="pc-content">
          <Outlet />
        </div>
      </main>

      <nav className="pc-bottomnav" aria-label="ניווט תחתון">
        <ul>
          {PRIMARY_NAV.map((item) => (
            <li key={item.to}>
              <NavLink to={item.to} end={item.to === '/'} className={({ isActive }) => `pc-tab${isActive ? ' active' : ''}`}>
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

function Header({
  onToggleSidebar,
  collapsed,
}: {
  onToggleSidebar: () => void
  collapsed: boolean
}) {
  return (
    <header className="pc-header">
      <button
        type="button"
        className="pc-iconbtn pc-sidebar-toggle"
        onClick={onToggleSidebar}
        aria-label={collapsed ? 'הרחבת התפריט' : 'כיווץ התפריט'}
        aria-expanded={!collapsed}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round">
          <path d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>

      <NavLink to="/" className="pc-brand">
        <img src="/favicon.svg" alt="" width="28" height="28" />
        <span>PlantCare</span>
      </NavLink>

      <div className="pc-header-actions">
        {/* Shows today's care tasks — the decision recorded in
            docs/MIGRATION_AUDIT.md section 5, because there is no notification feed
            endpoint and inventing one would be a schema change. Wired in phase 5. */}
        <button type="button" className="pc-iconbtn" aria-label="תזכורות להיום">
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 8.5a6 6 0 1 0-12 0c0 6-2 7.5-2 7.5h16s-2-1.5-2-7.5z" />
            <path d="M10.5 19.5a2 2 0 0 0 3 0" />
          </svg>
        </button>
        <button type="button" className="pc-iconbtn" aria-label="חשבון">
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="8.5" r="3.5" />
            <path d="M5 20c0-3.3 3.1-5.5 7-5.5s7 2.2 7 5.5" />
          </svg>
        </button>
      </div>
    </header>
  )
}
