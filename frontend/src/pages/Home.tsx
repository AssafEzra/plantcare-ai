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
import { useDashboard, useCompleteTask, useSkipTask, actionLabel } from '../api/careTasks'
import type { CareTask } from '../api/careTasks'
import { useMe } from '../api/profile'
import { usePlants } from '../api/plants'
import PlantCard from '../components/PlantCard'
import Async from '../components/Async'
import { formatDueDate } from '../lib/dates'
import '../components/PlantCard.css'
import './Home.css'

export default function Home() {
  const { data: me } = useMe()
  const query = useDashboard()
  const plantsQuery = usePlants()
  const data = query.data

  const plants = (plantsQuery.data ?? []).filter((p) => p.status !== 'ARCHIVED')

  return (
    <section>
      <header className="pc-pagehead">
        <h1>{me?.display_name ? `שלום ${me.display_name}` : 'בית'}</h1>
        <Link to="/plants/new" className="pc-btn">
          הוספת צמח
        </Link>
      </header>

      <div className="pc-sectionhead">
        <h2>הטיפולים של היום</h2>
      </div>

      <Async
        query={query}
        empty={(data?.today_care.length ?? 0) === 0}
        emptyState={<p>אין טיפולים להיום. הכול מעודכן.</p>}
      >
        <ul className="pc-tasklist">
          {data?.today_care.map((task) => (
            <TaskRow key={task.id} task={task} />
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
        <h2>הצמחים שלי</h2>
        <Link to="/plants">לכל הצמחים</Link>
      </div>

      <Async
        query={plantsQuery}
        empty={plants.length === 0}
        emptyState={
          <div className="pc-empty">
            <p>עוד לא הוספתם צמחים.</p>
            <Link to="/plants/new" className="pc-btn">
              הוספת הצמח הראשון
            </Link>
          </div>
        }
      >
        <div className="pc-plantgrid">
          {plants.slice(0, 6).map((plant) => (
            <PlantCard key={plant.id} plant={plant} />
          ))}
        </div>
      </Async>
    </section>
  )
}

function TaskRow({ task }: { task: CareTask }) {
  const complete = useCompleteTask()
  const skip = useSkipTask()
  const busy = complete.isPending || skip.isPending
  const failed = complete.error || skip.error

  return (
    <li className="pc-taskrow">
      <div className="pc-taskinfo">
        <span className="pc-taskaction">{actionLabel(task.action_type)}</span>
        <Link to={`/plants/${task.plant_id}`} className="pc-taskplant">
          {task.plant_name ?? 'צמח'}
        </Link>
        <span className="pc-taskdue">{formatDueDate(task.due_at_utc)}</span>
        {failed && (
          <span className="pc-taskerror" role="alert">
            הפעולה לא נרשמה. אפשר לנסות שוב.
          </span>
        )}
      </div>

      <div className="pc-taskactions">
        <button
          type="button"
          className="pc-btn pc-btn-sm"
          disabled={busy}
          onClick={() => complete.mutate({ taskId: task.id })}
        >
          בוצע
        </button>
        <button
          type="button"
          className="pc-btn pc-btn-sm pc-btn-quiet"
          disabled={busy}
          onClick={() => skip.mutate({ taskId: task.id })}
        >
          דילוג
        </button>
      </div>
    </li>
  )
}
