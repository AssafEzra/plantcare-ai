/* Health status and trend vocabulary.
 *
 * Ported from app/ui/components/status.py, including its rule: a badge shows an icon
 * and text together, "never colour alone". Colour-blind users and anyone on a poor
 * screen get the same information as everyone else, so the icon is not decoration.
 */

export type HealthStatus = 'HEALTHY' | 'NEEDS_ATTENTION' | 'CRITICAL' | 'UNKNOWN'
export type HealthTrend = 'IMPROVING' | 'WORSENING' | 'STABLE' | 'UNABLE_TO_DETERMINE'

/** Maps onto the --pc-{tone} / --pc-{tone}-bg token pairs. */
export type Tone = 'success' | 'warning' | 'danger' | 'neutral'

export type StatusStyle = { label: string; tone: Tone; glyph: string }

const STATUS: Record<HealthStatus, StatusStyle> = {
  HEALTHY: { label: 'בריא', tone: 'success', glyph: '✓' },
  NEEDS_ATTENTION: { label: 'דורש תשומת לב', tone: 'warning', glyph: '!' },
  CRITICAL: { label: 'מצב קריטי', tone: 'danger', glyph: '!!' },
  UNKNOWN: { label: 'לא ידוע', tone: 'neutral', glyph: '?' },
}

const TREND: Record<HealthTrend, StatusStyle> = {
  IMPROVING: { label: 'משתפר', tone: 'success', glyph: '↑' },
  WORSENING: { label: 'מחמיר', tone: 'danger', glyph: '↓' },
  STABLE: { label: 'יציב', tone: 'neutral', glyph: '→' },
  UNABLE_TO_DETERMINE: { label: 'אין מספיק נתונים', tone: 'neutral', glyph: '?' },
}

export function statusStyle(status: string | null | undefined): StatusStyle {
  return STATUS[(status ?? 'UNKNOWN') as HealthStatus] ?? STATUS.UNKNOWN
}

export function trendStyle(trend: string | null | undefined): StatusStyle {
  return TREND[(trend ?? 'UNABLE_TO_DETERMINE') as HealthTrend] ?? TREND.UNABLE_TO_DETERMINE
}

/** Ordering for "worst first" — the Health screen leads with what needs doing. */
export const STATUS_SEVERITY: Record<HealthStatus, number> = {
  CRITICAL: 0,
  NEEDS_ATTENTION: 1,
  UNKNOWN: 2,
  HEALTHY: 3,
}

/* Plant lifecycle, for the states a card must explain rather than hide. */
export const PLANT_STATUS_LABELS: Record<string, string> = {
  PENDING_IDENTIFICATION: 'בזיהוי',
  IDENTIFIED: 'ממתין לאישור',
  KNOWLEDGE_PENDING: 'אוסף מידע',
  ACTIVE: 'פעיל',
  ARCHIVED: 'בארכיון',
}
