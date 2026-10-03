/* A care action, as a glyph.
 *
 * Lived in PlantCard until the task rows on Home and the plant dashboard wanted the
 * same vocabulary. Seven actions, seven drawings: a column of identical dots beside
 * seven different words tells the eye nothing, and the eye is what a list is for.
 *
 * Inline SVG rather than an icon package, for the same reason `app/nav.tsx` gives: a
 * handful of glyphs does not justify a dependency, and these inherit `currentColor`.
 */

import type { ReactNode } from 'react'

const PATHS: Record<string, ReactNode> = {
  WATERING: <path d="M12 3s5 5.4 5 9a5 5 0 0 1-10 0c0-3.6 5-9 5-9z" />,
  FERTILIZING: (
    <>
      <path d="M12 20v-7" />
      <path d="M12 13c0-3.4 2.4-6.2 5.7-6.8-.3 3.6-2.7 6.2-5.7 6.8z" />
      <path d="M12 15c0-2.9-2-5.4-4.9-6 .3 3.1 2.3 5.4 4.9 6z" />
    </>
  ),
  REPOTTING: (
    <>
      <path d="M5 9h14l-1.6 10.2a2 2 0 0 1-2 1.8H8.6a2 2 0 0 1-2-1.8z" />
      <path d="M4 6h16v3H4z" />
    </>
  ),
  PRUNING: (
    <>
      <circle cx="7" cy="18" r="2.4" />
      <circle cx="17" cy="18" r="2.4" />
      <path d="M8.6 16.2L19 4M15.4 16.2L5 4" />
    </>
  ),
  MISTING: (
    <>
      <path d="M10 21V9a3 3 0 0 1 3-3h4" />
      <path d="M10 9h6" />
      <path d="M19 4.5h.01M21.5 7h.01M19 9.5h.01" />
    </>
  ),
  ROTATING: (
    <>
      <path d="M20 12a8 8 0 1 1-2.3-5.7" />
      <path d="M20 4v4h-4" />
    </>
  ),
  INSPECTION: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M20 20l-4.2-4.2" />
    </>
  ),
}

/** Decorative: the action is always named in words beside it. */
export default function ActionIcon({ type }: { type: string | null }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {(type && PATHS[type]) ?? <circle cx="12" cy="12" r="7" />}
    </svg>
  )
}
