/* "עוד" — a dedicated full-screen view.
 *
 * Section 11 is explicit that this is "a dedicated full-screen view, not a drawer
 * and not a bottom sheet", so it is a route with its own URL rather than an overlay.
 * On desktop these entries live in the sidebar directly and this page is redundant,
 * but it stays reachable so a deep link to /more never 404s.
 */

import { NavLink } from 'react-router-dom'
import { navFor } from '../app/nav'
import { useMe } from '../api/profile'
import './More.css'
import PageHero from '../components/PageHero'

export default function More() {
  const { data: me } = useMe()
  const { secondary: items } = navFor(me?.role)

  return (
    <section className="pc-more">
      <PageHero eyebrow="ניווט" title="עוד" />
      <ul className="pc-morelist">
        {items.map((item) => (
          <li key={item.to}>
            <NavLink to={item.to} className="pc-morelink">
              <span className="pc-moreicon">{item.icon}</span>
              <span>{item.label}</span>
              <span className="pc-morechevron" aria-hidden="true">
                {/* Points to the inline end, which RTL puts on the left. */}
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M15 5l-7 7 7 7" />
                </svg>
              </span>
            </NavLink>
          </li>
        ))}
      </ul>
    </section>
  )
}
