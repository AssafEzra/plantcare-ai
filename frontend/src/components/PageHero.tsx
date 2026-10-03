/* The green banner at the top of a page.
 *
 * One component rather than a block of markup repeated on seven screens: the heading
 * level, the landmark and the decoration are decided once, and a page that wants a
 * different action in the corner passes it as a child.
 *
 * The foliage behind the title is drawn, not photographed. A photograph would have to
 * be shipped, would cost a request on every page load, and would need a different crop
 * at every width; three SVG leaves cost nothing, scale cleanly and tint themselves from
 * the band they sit on. It is `aria-hidden` because it says nothing a reader needs.
 */

import type { ReactNode } from 'react'
import './PageHero.css'

export default function PageHero({
  eyebrow,
  title,
  subtitle,
  count,
  children,
}: {
  /** Small tracked label above the title. */
  eyebrow?: string
  title: string
  /** One line under the title. Facts, not marketing. */
  subtitle?: ReactNode
  /** Shown as a pill beside the title when the page counts something. */
  count?: number
  /** The page's primary action, rendered in the corner. */
  children?: ReactNode
}) {
  return (
    <header className="pc-hero">
      <span className="pc-hero-art" aria-hidden="true">
        <svg viewBox="0 0 240 180" fill="none" preserveAspectRatio="xMidYMid meet">
          <g className="pc-hero-leaf pc-hero-leaf-1">
            <path
              d="M120 170C120 120 150 80 205 70c-5 58-42 92-85 100z"
              fill="currentColor"
              opacity="0.5"
            />
            <path d="M120 170C135 130 160 100 200 78" stroke="currentColor" strokeWidth="2" opacity="0.4" />
          </g>
          <g className="pc-hero-leaf pc-hero-leaf-2">
            <path
              d="M120 175C120 130 92 96 40 88c5 54 40 84 80 87z"
              fill="currentColor"
              opacity="0.38"
            />
            <path d="M120 175C106 140 84 114 46 95" stroke="currentColor" strokeWidth="2" opacity="0.3" />
          </g>
          <g className="pc-hero-leaf pc-hero-leaf-3">
            <path
              d="M118 180C118 140 112 86 128 28c30 48 24 112 4 152z"
              fill="currentColor"
              opacity="0.3"
            />
          </g>
        </svg>
      </span>

      <div className="pc-hero-text">
        {eyebrow && <span className="pc-hero-eyebrow">{eyebrow}</span>}
        <h1>
          {title}
          {count !== undefined && <span className="pc-hero-count">{count}</span>}
        </h1>
        {subtitle && <p className="pc-hero-sub">{subtitle}</p>}
      </div>

      {children && <div className="pc-hero-actions">{children}</div>}
    </header>
  )
}
