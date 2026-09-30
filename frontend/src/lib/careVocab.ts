/* The words the care plan is described in.
 *
 * Ported from app/ui/components/care_plan.py and environment_form.py. Kept apart from
 * `api/careTasks.ts` because the dashboard, the proposal dialog and the diff all
 * need them and none of those is about care *tasks*.
 */

export const SOURCE_LABELS: Record<string, string> = {
  INITIAL_PLAN: 'תוכנית ראשונה',
  OPERATIONAL_ADJUSTMENT: 'שינוי תפעולי',
  ENVIRONMENT_CHANGE: 'שינוי בסביבה',
  HEALTH_DRIVEN: 'בעקבות בדיקת בריאות',
  RE_IDENTIFICATION: 'זיהוי מחדש',
}

export const WEEKDAY_LABELS: Record<string, string> = {
  SUNDAY: 'ראשון',
  MONDAY: 'שני',
  TUESDAY: 'שלישי',
  WEDNESDAY: 'רביעי',
  THURSDAY: 'חמישי',
  FRIDAY: 'שישי',
  SATURDAY: 'שבת',
}

/**
 * Say the interval the way a person would.
 *
 * "כל 7 ימים" is correct and reads like a database row; "כל שבוע" is what the user
 * actually has to remember.
 */
export function intervalText(days: number): string {
  if (days === 1) return 'כל יום'
  if (days === 7) return 'כל שבוע'
  if (days === 14) return 'כל שבועיים'
  if (days === 30) return 'כל חודש'
  if (days % 7 === 0) return `כל ${days / 7} שבועות`
  return `כל ${days} ימים`
}

/** `HH:MM:SS` or `HH:MM` from the API, shown as `HH:MM`. */
export function clockTime(value: string | null | undefined): string {
  return (value ?? '').slice(0, 5)
}

/* --- the professional half ------------------------------------------------ */

/* FINAL section 12: these are shown as text and never as an input. The labels are
   the keys the Care Agent's contract fills in. */
export const RECOMMENDATION_LABELS: [string, string][] = [
  ['watering', 'השקיה'],
  ['light', 'אור'],
  ['feeding', 'דישון'],
  ['seasonal_notes', 'הערות עונתיות'],
]

/* --- growing conditions --------------------------------------------------- */

export const LOCATION_LABELS: Record<string, string> = {
  INDOOR: 'בתוך הבית',
  OUTDOOR: 'בחוץ',
  BALCONY: 'מרפסת',
  GREENHOUSE: 'חממה',
}

export const LIGHT_LABELS: Record<string, string> = {
  LOW: 'מעט אור',
  MEDIUM: 'אור בינוני',
  BRIGHT: 'אור בהיר',
  DIRECT_SUN: 'שמש ישירה',
}

export const DIRECTION_LABELS: Record<string, string> = {
  NORTH: 'צפון',
  SOUTH: 'דרום',
  EAST: 'מזרח',
  WEST: 'מערב',
  UNKNOWN: 'לא ידוע',
}

export const ENVIRONMENT_FIELDS: [string, string][] = [
  ['location_type', 'מיקום'],
  ['light_level', 'עוצמת אור'],
  ['light_direction', 'כיוון החלון'],
  ['temperature_c', 'טמפרטורה'],
  ['humidity_percent', 'לחות'],
  ['room', 'חדר'],
  ['notes', 'הערות'],
]

const VALUE_LABELS: Record<string, Record<string, string>> = {
  location_type: LOCATION_LABELS,
  light_level: LIGHT_LABELS,
  light_direction: DIRECTION_LABELS,
}

/** The stored value in Hebrew, for the read-only summary. */
export function describeEnvironment(field: string, value: unknown): string {
  const labels = VALUE_LABELS[field]
  if (labels) return labels[String(value)] ?? String(value)
  if (field === 'temperature_c') return `${value}°C`
  if (field === 'humidity_percent') return `${value}%`
  return String(value)
}

/* --- health --------------------------------------------------------------- */

export const SEVERITY_LABELS: Record<number, string> = {
  1: 'קלה',
  2: 'קלה-בינונית',
  3: 'בינונית',
  4: 'משמעותית',
  5: 'חמורה',
}

export const CONFIDENCE_LABELS: Record<string, string> = {
  HIGH: 'גבוהה',
  MEDIUM: 'בינונית',
  LOW: 'נמוכה',
}

/* --- knowledge ------------------------------------------------------------ */

/* The thirteen sections FINAL section 10 defines, in the order the article is read
   in. Anything the agent returns that is not here is not rendered: the set is the
   contract, and an unknown key is a schema drift worth noticing rather than
   displaying raw. */
export const KNOWLEDGE_SECTIONS: [string, string][] = [
  ['identification', 'זיהוי'],
  ['description', 'תיאור'],
  ['light', 'אור'],
  ['watering', 'השקיה'],
  ['soil', 'מצע'],
  ['temperature', 'טמפרטורה'],
  ['humidity', 'לחות'],
  ['fertilization', 'דישון'],
  ['repotting', 'החלפת עציץ'],
  ['pruning', 'גיזום'],
  ['propagation', 'ריבוי'],
  ['common_problems', 'בעיות נפוצות'],
  ['toxicity_safety', 'רעילות ובטיחות'],
]

/* Worst first, deliberately. A reader needs to see what is *not* backed by a fetched
   page before the text resting on it. */
export const SOURCE_CLASS_LABELS: Record<string, { label: string; tone: string }> = {
  APPROVED: { label: 'מקור מאושר', tone: 'success' },
  EXTERNAL_UNAPPROVED: { label: 'מקור חיצוני לא מאושר', tone: 'warning' },
  AI_GENERATED_REQUIRES_VERIFICATION: { label: 'נוצר ב-AI — דורש אימות', tone: 'danger' },
}

export const SOURCE_CLASS_ORDER: Record<string, number> = {
  AI_GENERATED_REQUIRES_VERIFICATION: 0,
  EXTERNAL_UNAPPROVED: 1,
  APPROVED: 2,
}

/* --- history -------------------------------------------------------------- */

/* The four kinds FINAL section 19 lets a user log by hand. A user cannot forge a
   PLANT_CREATED or an ENVIRONMENT_CHANGED: those are written by the actions that
   cause them, and the endpoint refuses anything else. */
export const LOGGABLE_EVENTS: [string, string][] = [
  ['REPOTTED', 'החלפתי עציץ'],
  ['MOVED', 'העברתי למקום אחר'],
  ['PRUNED', 'גיזמתי'],
  ['CUSTOM_NOTE', 'הערה חופשית'],
]

/* --- administration ------------------------------------------------------- */

export const DRAFT_STATUS_LABELS: Record<string, { label: string; tone: string }> = {
  DRAFT: { label: 'טיוטה', tone: 'neutral' },
  RESEARCHING: { label: 'במחקר', tone: 'neutral' },
  READY_FOR_REVIEW: { label: 'ממתין לבדיקה', tone: 'warning' },
  APPROVED: { label: 'אושר', tone: 'success' },
  REJECTED: { label: 'נדחה', tone: 'danger' },
  FAILED: { label: 'נכשל', tone: 'danger' },
}

/* Below this a section is surfaced to the reviewer rather than left to be found.
   Matches `KnowledgeContent.weakest_sections` server-side. A reviewer with limited
   time who reads top to bottom will approve the fourteenth section least carefully,
   so the screen says where to start. */
export const WEAK_SECTION = 0.5

export const REPORT_DECISIONS: [string, string][] = [
  ['ACTIONED', 'טופל'],
  ['REVIEWING', 'בבדיקה'],
  ['DISMISSED', 'נדחה'],
]

