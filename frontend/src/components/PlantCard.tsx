/* The plant card.
 *
 * Section 14: the card is informational only. There are NO quick actions inside it —
 * clicking it opens the plant dashboard and nothing else. Resist adding a "done"
 * button here; that decision was taken deliberately so the card never competes with
 * the dashboard for the same gesture.
 *
 * The whole card is one link rather than a div with a click handler, so it is
 * keyboard reachable, announces itself as a link, and supports open-in-new-tab.
 */

import { Link } from 'react-router-dom'
import type { Plant } from '../api/plants'
import { plantName } from '../api/plants'
import { actionLabel } from '../api/careTasks'
import { statusStyle, PLANT_STATUS_LABELS } from '../lib/status'
import StatusBadge from './StatusBadge'
import { formatDueDate } from '../lib/dates'
import './PlantCard.css'

export default function PlantCard({ plant }: { plant: Plant }) {
  const name = plantName(plant)
  const health = statusStyle(plant.current_health_status)
  const isActive = plant.status === 'ACTIVE'

  return (
    <Link to={`/plants/${plant.id}`} className="pc-plantcard">
      <div className="pc-plantthumb">
        {plant.thumbnail_url ? (
          <img src={plant.thumbnail_url} alt="" loading="lazy" />
        ) : (
          <span className="pc-plantthumb-empty" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 21v-8" />
              <path d="M12 13c0-3.5 2.4-6.4 5.8-7-.3 3.7-2.7 6.4-5.8 7z" />
              <path d="M12 15c0-3-2-5.6-5-6.2.3 3.2 2.3 5.6 5 6.2z" />
            </svg>
          </span>
        )}
      </div>

      <div className="pc-plantbody">
        <h3 className="pc-plantname">{name}</h3>

        {/* Only when it adds something. A plant the user never renamed carries the
            species as its display name, and repeating it reads as a bug. */}
        {plant.species_name && plant.name && plant.species_name !== plant.name && (
          <p className="pc-plantspecies">{plant.species_name}</p>
        )}

        <div className="pc-plantmeta">
          {/* Only an active plant's health means anything; one still being
              identified has no assessment behind the value. */}
          {isActive ? (
            <StatusBadge label={health.label} tone={health.tone} glyph={health.glyph} />
          ) : (
            <StatusBadge
              label={PLANT_STATUS_LABELS[plant.status] ?? plant.status}
              tone="neutral"
              glyph="•"
            />
          )}

          {plant.awaiting_confirmation && (
            <StatusBadge label="ממתין לאישור הזיהוי" tone="warning" glyph="!" />
          )}
        </div>

        {plant.next_task && (
          <p className="pc-plantnext">
            {actionLabel(plant.next_task.action_type)} · {formatDueDate(plant.next_task.due_at_utc)}
          </p>
        )}
      </div>
    </Link>
  )
}
