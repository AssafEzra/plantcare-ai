/* A status badge: glyph and text together.
 *
 * Never colour alone — the rule carried over from app/ui/components/status.py. The
 * glyph is `aria-hidden` because it duplicates the label for sighted users; a screen
 * reader gets the words.
 */

import type { Tone } from '../lib/status'
import './StatusBadge.css'

export default function StatusBadge({
  label,
  tone,
  glyph,
}: {
  label: string
  tone: Tone
  glyph: string
}) {
  return (
    <span className={`pc-statusbadge pc-tone-${tone}`}>
      <span className="pc-statusglyph" aria-hidden="true">
        {glyph}
      </span>
      {label}
    </span>
  )
}
