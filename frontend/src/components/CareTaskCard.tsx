/* One care task, as a small card, and the two things a user can do about it.
 *
 * The single renderer, used by משימות and by the plant dashboard. The Streamlit build
 * had two, and they disagreed: the plant's own page drew a task read-only while Home
 * offered Done and Skip, so a task due today could only be completed from the other
 * screen. Owning the mutations here rather than taking callbacks is what makes that
 * impossible to repeat — there is one definition of what pressing "בוצע" does.
 *
 * Both actions are always offered on an actionable task. Skip is not a lesser option to
 * be hidden: a user who did not water today should be able to say so, and the schedule
 * treats a skip differently from silence — silence becomes an overdue task and
 * eventually a missed one, while a skip is a decision the plan can act on.
 *
 * What the card SAYS was the thing missing. A row read "השקיה · קרוטון · באיחור של יום"
 * and stopped there, which is a reminder, not a reason: the care plan had already
 * written down why this plant is watered every nine days and what to look at while
 * doing it, and the interface threw that sentence away. It is on the card now, under
 * the plant's own photograph, so the answer to "why am I being asked this?" is in the
 * same place as the ask.
 *
 * The photograph is shown only where it identifies something. The plant dashboard
 * passes `linkToPlant={false}` because the whole page is that plant, and the server
 * sends no thumbnail for the upcoming list — so both fall back to the action glyph on
 * its own, which is the right weight for a row nobody has to act on yet.
 */

import { Link } from 'react-router-dom'
import type { CSSProperties } from 'react'
import { useIsReadOnly } from '../lib/viewAs'
import ActionIcon from '../lib/actionIcon'
import {
  actionLabel,
  dueText,
  useCompleteTask,
  useSkipTask,
  type CareTask,
} from '../api/careTasks'
import './CareTaskCard.css'

/* Same rule as the plant card's empty tile: a stable hue per plant, kept in the straw
   to leaf-green range, so an unphotographed plant still has a colour of its own. */
function hueOf(id: string): number {
  let h = 0
  for (let i = 0; i < id.length; i += 1) h = (h * 31 + id.charCodeAt(i)) % 360
  return 60 + (h % 110)
}

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
  const photo = linkToPlant ? task.thumbnail_url : null
  const instructions = task.instructions?.trim() || null
  const every = task.interval_days && task.interval_days > 0 ? task.interval_days : null

  return (
    <li
      className={`pc-taskrow${overdue ? ' is-overdue' : ''}`}
      style={{ '--pc-plant-hue': hueOf(task.plant_id) } as CSSProperties}
    >
      {/* The picture says which plant; the glyph on its corner says what to do. With no
          picture the glyph takes the whole tile rather than floating in an empty one. */}
      <span className={`pc-taskmedia${photo ? ' has-photo' : ''}`} aria-hidden="true">
        {photo && <img src={photo} alt="" loading="lazy" />}
        <span className="pc-taskicon">
          <ActionIcon type={task.action_type} />
        </span>
      </span>

      <div className="pc-taskinfo">
        <span className="pc-taskhead">
          <span className="pc-taskaction">{actionLabel(task.action_type)}</span>
          <span className={overdue ? 'pc-taskdue is-late' : 'pc-taskdue'}>{dueText(task)}</span>
        </span>

        {linkToPlant && (
          <Link to={`/plants/${task.plant_id}`} className="pc-taskplant">
            {task.plant_name ?? 'צמח'}
          </Link>
        )}

        {/* The care plan's own words. Clamped to three lines: it is the reason for the
            task, not the plan document, and a paragraph here buries the next task. */}
        {instructions && <p className="pc-taskwhy">{instructions}</p>}

        {every && (
          <span className="pc-taskevery">
            חוזר כל <span className="pc-num">{every}</span> ימים
          </span>
        )}

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
