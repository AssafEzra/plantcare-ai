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
