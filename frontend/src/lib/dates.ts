/* Dates and times, in the user's local zone.
 *
 * Section 25: the database is UTC, the interface is local. The API sends ISO-8601
 * with an offset, so the browser converts using the device's zone. The profile also
 * carries a stored `timezone`, which is what NOTIFICATIONS are sent against — the
 * two can disagree if someone travels, and for on-screen text the device is the
 * right answer.
 *
 * Every formatted value is wrapped by callers in `.pc-num`/<time> so digits keep
 * their order inside Hebrew prose.
 */

const DATE = new Intl.DateTimeFormat('he-IL', { day: 'numeric', month: 'short' })
const DATE_FULL = new Intl.DateTimeFormat('he-IL', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
})
const TIME = new Intl.DateTimeFormat('he-IL', { hour: '2-digit', minute: '2-digit' })

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

/** Whole days from today: 0 today, -1 yesterday, 1 tomorrow. */
export function dayOffset(iso: string, now = new Date()): number {
  const then = new Date(iso)
  return Math.round((startOfDay(then) - startOfDay(now)) / 86_400_000)
}

/**
 * A due date said the way a person would.
 *
 * Relative wording for the days either side of today, because "היום" is what the
 * user is deciding about; an absolute date beyond that, because "in 9 days" makes
 * someone count.
 */
export function formatDueDate(iso: string, now = new Date()): string {
  const days = dayOffset(iso, now)
  if (days === 0) return 'היום'
  if (days === 1) return 'מחר'
  if (days === -1) return 'אתמול'
  if (days < -1) return `באיחור ${Math.abs(days)} ימים`
  if (days <= 7) return `בעוד ${days} ימים`
  return DATE.format(new Date(iso))
}

export function formatDate(iso: string): string {
  return DATE_FULL.format(new Date(iso))
}

export function formatTime(iso: string): string {
  return TIME.format(new Date(iso))
}

/* --- longer forms ---------------------------------------------------------- */

const STAMP = new Intl.DateTimeFormat('he-IL', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

const DAY_MONTH = new Intl.DateTimeFormat('he-IL', { day: '2-digit', month: '2-digit' })

/** A date and time, for choosing between photographs taken minutes apart. */
export function formatStamp(iso: string): string {
  return STAMP.format(new Date(iso))
}

/**
 * When a health check ran.
 *
 * Absolute rather than "3 days ago": a user comparing this check with the previous one
 * needs to place them, and a relative phrase makes that arithmetic their problem. A
 * health assessment is a statement about a moment — "the lower leaves are yellowing"
 * means something different from a week ago than from an hour ago — and a card with no
 * date makes a stale result indistinguishable from a fresh one.
 */
export function assessedAt(iso: string | null | undefined): string {
  if (!iso) return ''
  return `נבדק ב-${formatStamp(iso)}`
}

/**
 * A timeline entry's date, with relative wording for the recent past.
 *
 * "Today" and "yesterday" carry more than a date does when scanning a list, and beyond
 * that the date is what actually helps.
 */
export function timelineWhen(iso: string, now = new Date()): string {
  const moment = new Date(iso)
  const days = -dayOffset(iso, now)

  if (days === 0) return `היום ${formatTime(iso)}`
  if (days === 1) return `אתמול ${formatTime(iso)}`
  if (days > 1 && days < 7) return `לפני ${days} ימים`
  return DATE_FULL.format(moment)
}

/**
 * When a care task is due, in words a person uses.
 *
 * An overdue task says how late it is rather than the date it was due: "3 days late" is
 * actionable, "due on the 2nd" makes the reader do the arithmetic.
 */
export function formatTaskDue(iso: string, overdue: boolean, now = new Date()): string {
  const days = dayOffset(iso, now)

  if (overdue) {
    const late = Math.max(0, -days)
    if (late === 0) return 'באיחור'
    if (late === 1) return 'באיחור של יום'
    return `באיחור של ${late} ימים`
  }

  if (days === 0) return `היום בשעה ${formatTime(iso)}`
  if (days === 1) return `מחר בשעה ${formatTime(iso)}`
  return `${DAY_MONTH.format(new Date(iso))} בשעה ${formatTime(iso)}`
}

