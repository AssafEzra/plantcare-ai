/* משימות — the day's work (section 12's dashboard, renamed and narrowed).
 *
 * "The dashboard is action-oriented. The user should understand in seconds what needs
 * attention today." That sentence still decides the ordering: today's work first,
 * then what is late.
 *
 * This screen used to be Home and used to end with a grid of plants. My Plants is now
 * the landing page, so that grid was showing the same collection one tap away from
 * itself; it has been removed and this screen is only about tasks.
 *
 * There is NO health check action here — section 12 says so explicitly, and section
 * 21 puts the check on the plant dashboard. Overdue work is a summary rather than a
 * list, because section 24 forbids presenting a backlog.
 */

import { Link } from 'react-router-dom'
import { useDashboard, actionLabel } from '../api/careTasks'
import { useMe } from '../api/profile'
import CareTaskCard from '../components/CareTaskCard'
import Async from '../components/Async'
import PageHero from '../components/PageHero'
import { useIsReadOnly } from '../lib/viewAs'
import './Tasks.css'

export default function Tasks() {
  const { data: me } = useMe()
  const query = useDashboard()
  const data = query.data

  const readOnly = useIsReadOnly()

  return (
    <section>
      <PageHero
        eyebrow={me?.display_name ? `שלום ${me.display_name}` : 'היום בגינה'}
        title="משימות"
        count={data?.today_care.length}
        subtitle={greeting(data?.today_care.length ?? 0)}
      >
        {!readOnly && (
          <Link to="/plants/new" className="pc-btn">
            הוספת צמח
          </Link>
        )}
      </PageHero>

      <div className="pc-sectionhead">
        <div>
          <span className="pc-eyebrow">מה צריך לעשות</span>
          <h2>
            הטיפולים של היום{' '}
            {(data?.today_care.length ?? 0) > 0 && (
              <span className="pc-countpill">{data?.today_care.length}</span>
            )}
          </h2>
        </div>
      </div>

      <Async
        query={query}
        empty={(data?.today_care.length ?? 0) === 0}
        emptyState={
          <div className="pc-empty">
            <span className="pc-emptyart" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 12.5l5 5L20 6.5" />
              </svg>
            </span>
            <p>אין טיפולים להיום. הכול מעודכן.</p>
          </div>
        }
      >
        <ul className="pc-tasklist">
          {data?.today_care.map((task) => (
            <CareTaskCard key={task.id} task={task} />
          ))}
        </ul>
      </Async>

      {data && data.overdue_summary.length > 0 && (
        <div className="pc-overdue">
          <h3>באיחור</h3>
          <ul>
            {data.overdue_summary.map((row) => (
              <li key={row.plant_id}>
                <Link to={`/plants/${row.plant_id}`}>{row.plant_name}</Link>{' '}
                <span className="pc-overdue-detail">
                  {row.action_types.map(actionLabel).join(', ')} ·{' '}
                  <span className="pc-num">{row.days_late}</span> ימים
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

    </section>
  )
}

function greeting(due: number): string {
  if (due === 0) return 'אין טיפולים להיום'
  if (due === 1) return 'טיפול אחד מחכה לכם היום'
  return `${due} טיפולים מחכים לכם היום`
}
