/* The plant card.
 *
 * Section 14: the card is informational only. There are NO quick actions inside it —
 * clicking it opens the plant dashboard and nothing else. Resist adding a "done"
 * button here; that decision was taken deliberately so the card never competes with
 * the dashboard for the same gesture.
 *
 * The whole card is one link rather than a div with a click handler, so it is
 * keyboard reachable, announces itself as a link, and supports open-in-new-tab.
 *
 * The photograph leads and the words follow it. Health sits on the picture, because it
 * is the one fact worth reading before the eye has finished recognising the plant;
 * everything else — name, species, the owner's note, the next task — is set on white
 * below it, where Hebrew is legible without fighting whatever is behind it.
 *
 * A plant with no photograph is not given a grey box. `hueOf` turns its id into a
 * stable hue, so every unphotographed plant has its own colour and is still told apart
 * at a glance; the same id always produces the same one.
 */

import type { CSSProperties, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { Plant } from '../api/plants'
import { plantName } from '../api/plants'
import { actionLabel } from '../api/careTasks'
import { statusStyle, PLANT_STATUS_LABELS } from '../lib/status'
import StatusBadge from './StatusBadge'
import { formatDueDate, dayOffset } from '../lib/dates'
import './PlantCard.css'

/* The action a task describes, as a glyph. Watering is far and away the most common,
   and a row of identical dots tells the eye nothing. */
const ACTION_ICONS: Record<string, ReactNode> = {
  WATERING: <path d="M12 3s5 5.4 5 9a5 5 0 0 1-10 0c0-3.6 5-9 5-9z" />,
  FERTILIZING: (
    <>
      <path d="M12 20v-7" />
      <path d="M12 13c0-3.4 2.4-6.2 5.7-6.8-.3 3.6-2.7 6.2-5.7 6.8z" />
      <path d="M12 15c0-2.9-2-5.4-4.9-6 .3 3.1 2.3 5.4 4.9 6z" />
    </>
  ),
  REPOTTING: (
    <>
      <path d="M5 9h14l-1.6 10.2a2 2 0 0 1-2 1.8H8.6a2 2 0 0 1-2-1.8z" />
      <path d="M4 6h16v3H4z" />
    </>
  ),
  PRUNING: (
    <>
      <circle cx="7" cy="18" r="2.4" />
      <circle cx="17" cy="18" r="2.4" />
      <path d="M8.6 16.2L19 4M15.4 16.2L5 4" />
    </>
  ),
  MISTING: (
    <>
      <path d="M10 21V9a3 3 0 0 1 3-3h4" />
      <path d="M10 9h6" />
      <path d="M19 4.5h.01M21.5 7h.01M19 9.5h.01" />
    </>
  ),
  ROTATING: (
    <>
      <path d="M20 12a8 8 0 1 1-2.3-5.7" />
      <path d="M20 4v4h-4" />
    </>
  ),
  INSPECTION: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M20 20l-4.2-4.2" />
    </>
  ),
}

/* The only tag that goes on the photograph besides health. Stitch's design puts a
   second chip there; it filled it with a vitality percentage we do not measure, so
   this carries the one thing that is both true and urgent. Absent when neither. */
function dueTag(plant: Plant): { label: string; tone: 'danger' | 'warning' } | null {
  if (!plant.next_task) return null
  if (plant.next_task.status === 'OVERDUE') return { label: 'באיחור', tone: 'danger' }
  const days = dayOffset(plant.next_task.due_at_utc)
  if (days < 0) return { label: 'באיחור', tone: 'danger' }
  if (days === 0) return { label: 'להיום', tone: 'warning' }
  return null
}

function hueOf(id: string): number {
  let h = 0
  for (let i = 0; i < id.length; i += 1) h = (h * 31 + id.charCodeAt(i)) % 360
  /* Kept off the blues and purples: this is a plant app and a lilac tile reads as a
     bug. 60–170 is straw through leaf green. */
  return 60 + (h % 110)
}

export default function PlantCard({ plant, index = 0 }: { plant: Plant; index?: number }) {
  const name = plantName(plant)
  const health = statusStyle(plant.current_health_status)
  const isActive = plant.status === 'ACTIVE'
  const species =
    plant.species_name && plant.name && plant.species_name !== plant.name
      ? plant.species_name
      : null
  const note = plant.notes?.trim() || null
  const due = dueTag(plant)

  return (
    <Link
      to={`/plants/${plant.id}`}
      className="pc-plantcard"
      /* Drives the entrance stagger. Capped so the twentieth card is not still
         waiting to appear a second after the first one landed. */
      style={{ '--pc-card-i': Math.min(index, 11) } as CSSProperties}
    >
      <div className="pc-plantthumb" style={{ '--pc-plant-hue': hueOf(plant.id) } as CSSProperties}>
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

        <div className="pc-plantbadges">
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

        {due && <span className={`pc-plantdue pc-plantdue-${due.tone}`}>{due.label}</span>}
      </div>

      <div className="pc-plantbody">
        <h3 className="pc-plantname">{name}</h3>
        {species && <p className="pc-plantspecies">{species}</p>}

        {/* The owner's own note, not a generated one. Shown only when they wrote it. */}
        {note && (
          <p className="pc-plantnote">
            <span aria-hidden="true">·</span> {note}
          </p>
        )}
      </div>

      <div className="pc-plantfoot">
        {plant.next_task ? (
          <>
            <span className="pc-planttaskicon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                {ACTION_ICONS[plant.next_task.action_type] ?? <circle cx="12" cy="12" r="7" />}
              </svg>
            </span>
            <span className="pc-planttask">
              {actionLabel(plant.next_task.action_type)}
              <span className="pc-planttaskwhen">{formatDueDate(plant.next_task.due_at_utc)}</span>
            </span>
          </>
        ) : (
          <span className="pc-planttask pc-planttask-none">אין טיפול מתוכנן</span>
        )}

        <span className="pc-plantgo" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 6l-6 6 6 6" />
          </svg>
        </span>
      </div>
    </Link>
  )
}
