/* Navigation model.
 *
 * One definition drives both shells, so the mobile bar and the desktop sidebar can
 * never drift apart. Section 11 fixes the mobile set at exactly four items —
 * בית, הצמחים שלי, בריאות, עוד — and states there is no separate "add plant" tab;
 * adding a plant is reached from Home and My Plants.
 *
 * Icons are inline SVG rather than an icon package: four glyphs do not justify a
 * dependency, and the CDN allowlist does not matter for a self-hosted bundle.
 * All use `currentColor` so the active/inactive colour is decided in CSS.
 */

import type { ReactNode } from 'react'

export type NavItem = {
  to: string
  label: string
  icon: ReactNode
  /** Mobile bottom bar shows only these four. */
  primary: boolean
  /** Reached through "עוד" on mobile; listed directly in the desktop sidebar. */
  adminOnly?: boolean
}

const stroke = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.75,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

const HomeIcon = (
  <svg viewBox="0 0 24 24" aria-hidden="true" {...stroke}>
    <path d="M3 10.5 12 3l9 7.5" />
    <path d="M5.5 9.5V20h13V9.5" />
  </svg>
)

const PlantsIcon = (
  <svg viewBox="0 0 24 24" aria-hidden="true" {...stroke}>
    <path d="M12 21v-8" />
    <path d="M12 13c0-3.5 2.4-6.4 5.8-7-.3 3.7-2.7 6.4-5.8 7z" />
    <path d="M12 15c0-3-2-5.6-5-6.2.3 3.2 2.3 5.6 5 6.2z" />
    <path d="M8 21h8" />
  </svg>
)

const HealthIcon = (
  <svg viewBox="0 0 24 24" aria-hidden="true" {...stroke}>
    <path d="M3 12h3.5l2-4.5 3 9 2.5-6 1.6 1.5H21" />
  </svg>
)

const MoreIcon = (
  <svg viewBox="0 0 24 24" aria-hidden="true" {...stroke}>
    <circle cx="5" cy="12" r="1.4" fill="currentColor" stroke="none" />
    <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
    <circle cx="19" cy="12" r="1.4" fill="currentColor" stroke="none" />
  </svg>
)

const SettingsIcon = (
  <svg viewBox="0 0 24 24" aria-hidden="true" {...stroke}>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 3v2.2M12 18.8V21M21 12h-2.2M5.2 12H3M18.4 5.6l-1.6 1.6M7.2 16.8l-1.6 1.6M18.4 18.4l-1.6-1.6M7.2 7.2 5.6 5.6" />
  </svg>
)

const AdminIcon = (
  <svg viewBox="0 0 24 24" aria-hidden="true" {...stroke}>
    <path d="M12 3l7 3v5.5c0 4-2.9 7.6-7 8.5-4.1-.9-7-4.5-7-8.5V6z" />
    <path d="M9.5 12l1.8 1.8 3.2-3.6" />
  </svg>
)

/** The four in the mobile bar, in order. */
export const PRIMARY_NAV: NavItem[] = [
  { to: '/', label: 'בית', icon: HomeIcon, primary: true },
  { to: '/plants', label: 'הצמחים שלי', icon: PlantsIcon, primary: true },
  { to: '/health', label: 'בריאות', icon: HealthIcon, primary: true },
  { to: '/more', label: 'עוד', icon: MoreIcon, primary: true },
]

/** Behind "עוד" on mobile; shown directly in the sidebar on desktop. */
export const SECONDARY_NAV: NavItem[] = [
  { to: '/settings', label: 'הגדרות', icon: SettingsIcon, primary: false },
  { to: '/admin', label: 'ניהול', icon: AdminIcon, primary: false, adminOnly: true },
]

export const ADMIN_NAV: NavItem[] = [
  { to: '/admin', label: 'ניהול', icon: AdminIcon, primary: true },
]

/**
 * What this identity is offered.
 *
 * An administrator gets the admin entry and nothing else: the account has no plants
 * of its own, so Home, My Plants and Health are four taps to four empty screens, and
 * an empty "you have no plants yet — add one" is an invitation to put a houseplant in
 * the wrong account.
 *
 * It keys on the *acting* role, and under "view as user" `GET /v1/me` reports the
 * viewed account — role USER — so the full navigation comes back for exactly as long
 * as the administrator is looking through somebody else's eyes. That is the one time
 * an admin needs Home and a plant page, and it is why this reads a role rather than
 * asking whether the signed-in person happens to be an administrator.
 */
export function navFor(role: string | undefined): { primary: NavItem[]; secondary: NavItem[] } {
  if (role === 'ADMIN') return { primary: ADMIN_NAV, secondary: [] }
  return { primary: PRIMARY_NAV, secondary: SECONDARY_NAV.filter((item) => !item.adminOnly) }
}
