/* The green banner at the top of a page.
 *
 * One component rather than a block of markup repeated on seven screens: the heading
 * level, the landmark and the decoration are decided once, and a page that wants a
 * different action in the corner passes it as a child.
 *
 * The foliage behind the title is drawn, not photographed. A photograph would have to
 * be shipped, would cost a request on every page load, and would need a different crop
 * at every width; a handful of SVG fronds cost nothing, scale cleanly and tint
 * themselves from the band they sit on. It is `aria-hidden` because it says nothing a
 * reader needs.
 */

import type { CSSProperties, ReactNode } from 'react'
import './PageHero.css'

/* One leaf, drawn once, planted at the origin and pointing up. Every frond is this
   shape turned to its own angle — which is what makes a plant rather than six
   different drawings that happen to be near each other. */
const LEAF = 'M0 0C26-26 34-74 0-118-34-74-26-26 0 0Z'
const RIB = 'M0 0C6-30 6-70 0-108'

/* Seven of them, fanned out and each on its own clock.
 *
 * The periods are deliberately not multiples of one another: fronds on related clocks
 * fall back into step within a few seconds of being watched, and a plant that breathes
 * in unison reads as a loop rather than as a plant. The negative delays start each one
 * part-way through its own cycle, so nothing lines up on the first frame either.
 *
 * Opacity falls off towards the outer fronds, which is what gives the fan depth: the
 * ones leaning furthest out read as being behind the rest. */
const FRONDS = [
  { angle: -78, scale: 0.72, fill: 0.3, period: 10, delay: -5.6, sway: 7 },
  { angle: -52, scale: 0.92, fill: 0.42, period: 8.5, delay: -3, sway: 6 },
  { angle: -26, scale: 1.08, fill: 0.5, period: 6.5, delay: -0.8, sway: 5 },
  { angle: 0, scale: 1.16, fill: 0.56, period: 7.4, delay: -2.2, sway: 4 },
  { angle: 26, scale: 1.05, fill: 0.46, period: 9, delay: -4.4, sway: 5 },
  { angle: 52, scale: 0.88, fill: 0.36, period: 8, delay: -6.1, sway: 6 },
  { angle: 78, scale: 0.68, fill: 0.26, period: 11, delay: -1.7, sway: 7 },
]

/* Three specks drifting up through the fan. They cost three circles and they are the
   difference between foliage that sways and air that moves through it. */
const MOTES = [
  { cx: 96, cy: 150, r: 3.5, period: 9, delay: 0 },
  { cx: 168, cy: 118, r: 2.5, period: 12, delay: -4 },
  { cx: 232, cy: 156, r: 3, period: 10.5, delay: -7 },
]

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
        {/* Cropped to start just above the tallest frond's tip, and anchored to the top of
              its box (`YMin`) rather than centred: that is what puts the top leaf on the
              band's own top edge at any height the banner happens to be, instead of
              wherever a centred drawing's padding happens to leave it. */}
          <svg viewBox="0 72 320 158" fill="none" preserveAspectRatio="xMidYMin meet">
          {FRONDS.map((frond) => (
            <g
              key={frond.angle}
              className="pc-hero-leaf"
              style={
                {
                  '--pc-leaf-period': `${frond.period}s`,
                  '--pc-leaf-delay': `${frond.delay}s`,
                  '--pc-leaf-sway': `${frond.sway}deg`,
                } as CSSProperties
              }
            >
              <g transform={`translate(160 224) rotate(${frond.angle}) scale(${frond.scale})`}>
                <path d={LEAF} fill="currentColor" opacity={frond.fill} />
                <path
                  d={RIB}
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  opacity={frond.fill * 0.75}
                />
              </g>
            </g>
          ))}

          {MOTES.map((mote) => (
            <circle
              key={mote.cx}
              className="pc-hero-mote"
              cx={mote.cx}
              cy={mote.cy}
              r={mote.r}
              fill="currentColor"
              style={
                {
                  '--pc-mote-period': `${mote.period}s`,
                  '--pc-mote-delay': `${mote.delay}s`,
                } as CSSProperties
              }
            />
          ))}
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
