/* One care task, and the two things a user can do about it.
 *
 * The single renderer, used by Home and by the plant dashboard. The Streamlit build had
 * two, and they disagreed: the plant's own page drew a task read-only while Home offered
 * Done and Skip, so a task due today could only be completed from the other screen.
 * Owning the mutations here rather than taking callbacks is what makes that impossible
 * to repeat — there is one definition of what pressing "בוצע" does.
 *
 * Both actions are always offered on an actionable task. Skip is not a lesser option to
 * be hidden: a user who did not water today should be able to say so, and the schedule
 * treats a skip differently from silence — silence becomes an overdue task and
 * eventually a missed one, while a skip is a decision the plan can act on.
 */

import { Link } from 'react-router-dom'
import { useIsReadOnly } from '../lib/viewAs'
import ActionIcon from '../lib/actionIcon'
import {
  actionLabel,
  dueText,
  useCompleteTask,
  useSkipTask,
  type CareTask,
} from '../api/careTasks'

export default function CareTaskCard({
  task,
  actionable = true,
  linkToPlant = true,
  plantId,
}: {
  task: CareTask
  /** False for a task that is not due yet — see `isDue` in api/careTasks.ts. */
  actionable?: boolean
  /** The plant's own page already says which plant this is. */
  linkToPlant?: boolean
  /** Present on the plant dashboard, so its own view model is refetched too. */
  plantId?: string
}) {
  const readOnly = useIsReadOnly()
  const complete = useCompleteTask(plantId)
  const skip = useSkipTask(plantId)
  const busy = complete.isPending || skip.isPending
  const failed = complete.error || skip.error

  const overdue = task.status === 'OVERDUE'

  return (
    <li className={`pc-taskrow${overdue ? ' is-overdue' : ''}`}>
      <span className="pc-taskicon" aria-hidden="true">
        <ActionIcon type={task.action_type} />
      </span>

      <div className="pc-taskinfo">
        <span className="pc-taskaction">{actionLabel(task.action_type)}</span>
        {linkToPlant && (
          <Link to={`/plants/${task.plant_id}`} className="pc-taskplant">
            {task.plant_name ?? 'צמח'}
          </Link>
        )}
        <span className={overdue ? 'pc-taskdue is-late' : 'pc-taskdue'}>{dueText(task)}</span>
        {failed && (
          <span className="pc-taskerror" role="alert">
            הפעולה לא נרשמה. אפשר לנסות שוב.
          </span>
        )}
      </div>

      {actionable && !readOnly && (
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
      )}
    </li>
  )
}
