/* Has a human read the professional information behind this? (FINAL section 10)
 *
 * A plant no longer waits for admin review before it gets knowledge and a care plan —
 * finished research is enough. That is a better first run, and it is only honest if
 * the screens say what the plan rests on.
 *
 * Three states, and the badge exists to keep them apart:
 *
 *   reviewed  a published version. Nothing is drawn. This is the ordinary case, and a
 *             badge on every plan would train people to stop reading badges.
 *   pending   finished research nobody has approved yet.
 *   rejected  an administrator judged that research wrong. The plan keeps running,
 *             because leaving the plant with no schedule at all is worse, and a
 *             corrected version is already being prepared.
 */

import StatusBadge from './StatusBadge'
import type { Tone } from '../lib/status'

const LABELS: Record<string, { label: string; tone: Tone }> = {
  pending: { label: 'ממתין לאישור מומחה', tone: 'warning' },
  rejected: { label: 'המידע המקצועי לא אושר', tone: 'danger' },
}

export default function ReviewBadge({ review }: { review: string | null | undefined }) {
  const found = LABELS[review ?? 'reviewed']
  if (!found) return null
  return <StatusBadge label={found.label} tone={found.tone} glyph="!" />
}
