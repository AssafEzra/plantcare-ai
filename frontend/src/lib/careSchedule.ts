/* Care intensity — how tightly care is grouped onto weekdays.
 *
 * The scheduler does the grouping (app/domain/rules/recurrence.py); this file only
 * names it. Warnings are computed by the API and arrive ready to show, so the rule for
 * when a plant "would get too little care" lives in one place.
 */

import { actionLabel } from '../api/careTasks'
import { WEEKDAY_LABELS, intervalText } from './careVocab'

export type CareIntensity = 'HIGH' | 'MEDIUM' | 'LOW'
export type Weekday =
  | 'SUNDAY'
  | 'MONDAY'
  | 'TUESDAY'
  | 'WEDNESDAY'
  | 'THURSDAY'
  | 'FRIDAY'
  | 'SATURDAY'

/** A task the chosen schedule would leave at most half as often as its plan asks. */
export type CareWarning = {
  action_type: string
  interval_days: number
  max_gap_days: number
}

/** Mirrors `care_schedule` on the plant dashboard. */
export type CareScheduleSummary = {
  override: CareIntensity | null
  owner_intensity: CareIntensity
  effective: CareIntensity
  care_days: Weekday[]
  warnings: CareWarning[]
}

export const INTENSITY_LABELS: Record<CareIntensity, string> = {
  HIGH: 'גבוהה',
  MEDIUM: 'בינונית',
  LOW: 'נמוכה',
}

export const INTENSITY_HINTS: Record<CareIntensity, string> = {
  HIGH: 'כל משימה בזמן המיטבי שלה.',
  MEDIUM: 'כל המשימות מרוכזות לשני ימי טיפול בשבוע.',
  LOW: 'כל המשימות מרוכזות ליום טיפול אחד בשבוע.',
}

/* Sunday first: the week as it is lived in Israel, which is how the picker reads. */
export const WEEK: Weekday[] = [
  'SUNDAY',
  'MONDAY',
  'TUESDAY',
  'WEDNESDAY',
  'THURSDAY',
  'FRIDAY',
  'SATURDAY',
]

function inWeekOrder(days: Weekday[]): Weekday[] {
  return [...days].sort((a, b) => WEEK.indexOf(a) - WEEK.indexOf(b))
}

/** "מתוזמן לימי הטיפול שלך: שלישי / שישי" — the one line on the plan card. */
export function scheduleLine(days: Weekday[]): string {
  const names = inWeekOrder(days).map((day) => WEEKDAY_LABELS[day] ?? day)
  return `מתוזמן לימי הטיפול שלך: ${names.join(' / ')}`
}

/** "השקיה: התוכנית אומרת כל 3 ימים, וימי הטיפול שלך רחוקים עד 7 ימים זה מזה." */
export function warningText(warning: CareWarning): string {
  return `${actionLabel(warning.action_type)}: התוכנית אומרת ${intervalText(
    warning.interval_days,
  )}, וימי הטיפול שלך רחוקים עד ${warning.max_gap_days} ימים זה מזה. ייתכן שזה לא מספיק לצמח.`
}
