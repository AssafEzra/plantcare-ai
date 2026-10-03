/* משימות — the day's work (section 12's dashboard, renamed and narrowed).
 *
 * "The dashboard is action-oriented. The user should understand in seconds what needs
 * attention today." That sentence decides the ordering: what is late, then what is due,
 * then what is coming. Late work comes first because it is the only part of the list
 * that is getting worse while it is read.
 *
 * This screen used to be Home and used to end with a grid of plants. My Plants is now
 * the landing page, so that grid was showing the same collection one tap away from
 * itself; it has been removed and this screen is only about tasks.
 *
 * Three changes of substance over the first version:
 *
 *   - `today_care` is SPLIT. The payload mixes overdue tasks into it (anything due
 *     before the end of today), and drawn as one flat list, four days late looked
 *     exactly like due at six this evening.
 *   - The `overdue_summary` panel at the foot is GONE. The server derives it from the
 *     same OVERDUE tasks that are already in `today_care`, so it restated the list
 *     above it — with the days-late count rounded to "0 ימים" for anything late by
 *     less than a day. The overdue section says the same thing once, actionably.
 *   - `upcoming_care` is SHOWN. The server has always sent the next ten tasks beyond
 *     today and the screen threw them away, so "what does this week look like" was a
 *     question the app could answer and didn't. They are grouped by day and drawn
 *     read-only: section 12's own rule, enforced by `isDue`, is that a task is not
 *     actionable before the day it falls on — buttons on Thursday's watering invite
 *     completing it today, which re-anchors the whole recurrence.
 *
 * There is NO health check action here — section 12 says so explicitly, and section
 * 21 puts the check on the plant dashboard.
 */

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useDashboard, type CareTask } from '../api/careTasks'
import { useMe } from '../api/profile'
import { formatDayHeading } from '../lib/dates'
import CareTaskCard from '../components/CareTaskCard'
import Async from '../components/Async'
import PageHero from '../components/PageHero'
import './Tasks.css'

/** Which band of work is on screen. '' is all three. */
type View = '' | 'OVERDUE' | 'TODAY' | 'LATER'

export default function Tasks() {
  const { data: me } = useMe()
  const query = useDashboard()
  const data = query.data
  const [view, setView] = useState<View>('')

  /* Split rather than filtered twice, so the two lists cannot drift apart. */
  const { overdue, today } = useMemo(() => {
    const all = data?.today_care ?? []
    return {
      overdue: all.filter((task) => task.status === 'OVERDUE'),
      today: all.filter((task) => task.status !== 'OVERDUE'),
    }
  }, [data])

  const later = useMemo(() => groupByDay(data?.upcoming_care ?? []), [data])
  const laterCount = data?.upcoming_care.length ?? 0
  const nothing = overdue.length + today.length + laterCount === 0

  const stats: { key: View; caption: string; value: number; tone: string }[] = [
    { key: 'OVERDUE', caption: 'באיחור', value: overdue.length, tone: 'danger' },
    { key: 'TODAY', caption: 'להיום', value: today.length, tone: 'primary' },
    { key: 'LATER', caption: 'בהמשך', value: laterCount, tone: 'neutral' },
  ]

  const shows = (band: View) => view === '' || view === band

  return (
    <section>
      <PageHero
        eyebrow={me?.display_name ? `שלום ${me.display_name}` : 'היום בגינה'}
        title="משימות"
        count={overdue.length + today.length}
        subtitle={greeting(overdue.length, today.length)}
      />

      {!nothing && (
        <div className="pc-statrow pc-statrow-3">
          {stats.map((stat) => (
            <button
              key={stat.key}
              type="button"
              className={`pc-stat pc-stat-${stat.tone}${view === stat.key ? ' is-on' : ''}`}
              aria-pressed={view === stat.key}
              onClick={() => setView(view === stat.key ? '' : stat.key)}
              disabled={stat.value === 0}
            >
              <span className="pc-statcaption">{stat.caption}</span>
              <span className="pc-statvalue">
                {stat.value}
                <span className="pc-statunit">משימות</span>
              </span>
            </button>
          ))}
        </div>
      )}

      <Async
        query={query}
        empty={nothing}
        emptyState={
          <div className="pc-empty">
            <span className="pc-emptyart" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 12.5l5 5L20 6.5" />
              </svg>
            </span>
            <p>אין טיפולים פתוחים. הכול מעודכן.</p>
            <Link to="/" className="pc-btn pc-btn-quiet">
              לצמחים שלי
            </Link>
          </div>
        }
      >
        <>
          {overdue.length > 0 && shows('OVERDUE') && (
            <section className="pc-taskband is-late">
              <div className="pc-sectionhead">
                <div>
                  <span className="pc-eyebrow">לא בוצעו במועד</span>
                  <h2>
                    באיחור <span className="pc-countpill">{overdue.length}</span>
                  </h2>
                </div>
              </div>
              <p className="pc-bandnote">כדאי להתחיל כאן. אלה הטיפולים שכבר עבר מועדם.</p>
              <ul className="pc-tasklist">
                {overdue.map((task) => (
                  <CareTaskCard key={task.id} task={task} />
                ))}
              </ul>
            </section>
          )}

          {today.length > 0 && shows('TODAY') && (
            <section className="pc-taskband">
              <div className="pc-sectionhead">
                <div>
                  <span className="pc-eyebrow">מה צריך לעשות</span>
                  <h2>
                    הטיפולים של היום <span className="pc-countpill">{today.length}</span>
                  </h2>
                </div>
              </div>
              <ul className="pc-tasklist">
                {today.map((task) => (
                  <CareTaskCard key={task.id} task={task} />
                ))}
              </ul>
            </section>
          )}

          {later.length > 0 && shows('LATER') && (
            <section className="pc-taskband">
              <div className="pc-sectionhead">
                <div>
                  <span className="pc-eyebrow">מה מחכה</span>
                  <h2>
                    בהמשך <span className="pc-countpill">{laterCount}</span>
                  </h2>
                </div>
              </div>
              {/* Read-only on purpose: see the note at the head of this file. */}
              <p className="pc-bandnote">לתכנון בלבד — אפשר לסמן כל טיפול ביום שבו הוא חל.</p>
              {later.map((day) => (
                <div key={day.key} className="pc-taskday">
                  <h3 className="pc-taskdayhead">
                    {day.label}
                    <span className="pc-taskdaycount">{day.tasks.length}</span>
                  </h3>
                  <ul className="pc-tasklist">
                    {day.tasks.map((task) => (
                      <CareTaskCard key={task.id} task={task} actionable={false} />
                    ))}
                  </ul>
                </div>
              ))}
            </section>
          )}
        </>
      </Async>
    </section>
  )
}

function greeting(late: number, due: number): string {
  if (late === 0 && due === 0) return 'אין טיפולים פתוחים'
  if (late > 0 && due > 0) return `${late} באיחור ועוד ${due} להיום`
  if (late > 0) return late === 1 ? 'טיפול אחד באיחור' : `${late} טיפולים באיחור`
  return due === 1 ? 'טיפול אחד מחכה לכם היום' : `${due} טיפולים מחכים לכם היום`
}

/**
 * Upcoming tasks, gathered into the day they fall on.
 *
 * Keyed by the LOCAL date rather than by the ISO string: two tasks at 08:00 and 19:00
 * on the same day are the same day to the reader, and section 25 puts the interface in
 * the device's zone. The server already sends these in due order, so appending to the
 * last group preserves it without a second sort.
 */
function groupByDay(tasks: CareTask[]): { key: string; label: string; tasks: CareTask[] }[] {
  const days = new Map<string, { key: string; label: string; tasks: CareTask[] }>()
  for (const task of tasks) {
    const key = new Date(task.due_at_utc).toDateString()
    const day = days.get(key)
    if (day) day.tasks.push(task)
    else days.set(key, { key, label: formatDayHeading(task.due_at_utc), tasks: [task] })
  }
  return [...days.values()]
}
