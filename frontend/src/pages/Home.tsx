/* Home (section 12).
 *
 * "The dashboard is action-oriented. The user should understand in seconds what needs
 * attention today." That sentence decides the ordering, and it is carried over from
 * the Streamlit home page: today's work first, because it is why someone opened the
 * app; the plants after it; the way to add one last.
 *
 * There is NO health check action here — section 12 says so explicitly, and section
 * 21 puts the check on the plant dashboard. Overdue work is a summary rather than a
 * list, because section 24 forbids presenting a backlog.
 */

import { Link } from 'react-router-dom'
import { useDashboard, actionLabel } from '../api/careTasks'
import { useMe } from '../api/profile'
import { usePlants } from '../api/plants'
import PlantCard from '../components/PlantCard'
import CareTaskCard from '../components/CareTaskCard'
import Async from '../components/Async'
import PageHero from '../components/PageHero'
import { useIsReadOnly } from '../lib/viewAs'
import '../components/PlantCard.css'
import './Home.css'

export default function Home() {
  const { data: me } = useMe()
  const query = useDashboard()
  const plantsQuery = usePlants()
  const data = query.data

  const plants = (plantsQuery.data ?? []).filter((p) => p.status !== 'ARCHIVED')
  const readOnly = useIsReadOnly()

  return (
    <section>
      <PageHero
        eyebrow="היום בגינה"
        title={me?.display_name ? `שלום ${me.display_name}` : 'בית'}
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

      <div className="pc-sectionhead">
        <div>
          <span className="pc-eyebrow">הגינה שלכם</span>
          <h2>
            הצמחים שלי{' '}
            {plants.length > 0 && <span className="pc-countpill">{plants.length}</span>}
          </h2>
        </div>
        <Link to="/plants">לכל הצמחים</Link>
      </div>

      <Async
        query={plantsQuery}
        empty={plants.length === 0}
        emptyState={
          <div className="pc-empty">
            <span className="pc-emptyart" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 21v-8" />
                <path d="M12 13c0-3.5 2.4-6.4 5.8-7-.3 3.7-2.7 6.4-5.8 7z" />
                <path d="M12 15c0-3-2-5.6-5-6.2.3 3.2 2.3 5.6 5 6.2z" />
              </svg>
            </span>
            <p>עוד לא הוספתם צמחים.</p>
            {!readOnly && (
              <Link to="/plants/new" className="pc-btn">
                הוספת הצמח הראשון
              </Link>
            )}
          </div>
        }
      >
        <div className="pc-plantgrid">
          {plants.slice(0, 6).map((plant, i) => (
            <PlantCard key={plant.id} plant={plant} index={i} />
          ))}
        </div>
      </Async>
    </section>
  )
}

function greeting(due: number): string {
  if (due === 0) return 'אין טיפולים להיום'
  if (due === 1) return 'טיפול אחד מחכה לכם היום'
  return `${due} טיפולים מחכים לכם היום`
}
