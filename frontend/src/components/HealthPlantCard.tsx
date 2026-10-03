/* A plant's health, as a full-width card.
 *
 * One per row, deliberately. The plant card on the collection is a tile because what it
 * carries is a name and a photograph; this one carries the last check's finding, the
 * evidence that finding rests on, what to do about it, and the dates of every check
 * before it. Two of those to a row would set the longest text on the screen in the
 * narrowest column on it.
 *
 * Every date is a button. §16 forbids presenting a definitive diagnosis, so a headline
 * on a card is only honest if the reasoning behind it is one press away — the full
 * assessment opens over the list, which is also what makes a row of past dates worth
 * showing at all.
 *
 * It still starts no check of its own. The check belongs to the plant dashboard, where
 * the plant's photographs are, so "בדיקה חדשה" is a link that opens it there.
 */

import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import type { Plant } from '../api/plants'
import { plantName } from '../api/plants'
import type { HealthHistoryEntry, PlantHealthOverview } from '../api/health'
import { SEVERITY_LABELS } from '../lib/careVocab'
import { formatStamp } from '../lib/dates'
import { statusStyle, trendStyle } from '../lib/status'
import StatusBadge from './StatusBadge'
import './HealthPlantCard.css'

/* The plant card's rule, so an unphotographed plant has the same colour on both
   screens: a stable hue per id, kept between straw and leaf green. */
function hueOf(id: string): number {
  let h = 0
  for (let i = 0; i < id.length; i += 1) h = (h * 31 + id.charCodeAt(i)) % 360
  return 60 + (h % 110)
}

export default function HealthPlantCard({
  plant,
  health,
  onOpenAssessment,
}: {
  plant: Plant
  /** Absent for a plant that has never been assessed. */
  health?: PlantHealthOverview
  onOpenAssessment: (assessmentId: string) => void
}) {
  const name = plantName(plant)
  const status = statusStyle(plant.current_health_status)
  const species =
    plant.species_name && plant.name && plant.species_name !== plant.name
      ? plant.species_name
      : null

  const latest = health?.latest
  /* UNABLE_TO_DETERMINE is the absence of a trend, not a trend. On the plant's own page
     it sits beside one assessment and reads as a caveat; on a list of seven cards it was
     the same grey chip seven times, saying nothing about any of them. */
  const trend =
    latest?.trend && latest.trend !== 'UNABLE_TO_DETERMINE' ? trendStyle(latest.trend) : null
  const unreadable = latest?.overall_status === 'UNKNOWN'

  return (
    <article
      className="pc-healthcard"
      style={{ '--pc-plant-hue': hueOf(plant.id) } as CSSProperties}
    >
      <Link to={`/plants/${plant.id}`} className="pc-healthphoto" aria-hidden="true" tabIndex={-1}>
        {plant.thumbnail_url ? (
          <img src={plant.thumbnail_url} alt="" loading="lazy" />
        ) : (
          <span className="pc-healthphoto-empty">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 21v-8" />
              <path d="M12 13c0-3.5 2.4-6.4 5.8-7-.3 3.7-2.7 6.4-5.8 7z" />
              <path d="M12 15c0-3-2-5.6-5-6.2.3 3.2 2.3 5.6 5 6.2z" />
            </svg>
          </span>
        )}
      </Link>

      <div className="pc-healthbody">
        <header className="pc-healthhead">
          <div className="pc-healthwho">
            <h3>
              <Link to={`/plants/${plant.id}`}>{name}</Link>
            </h3>
            {species && <p className="pc-healthspecies">{species}</p>}
          </div>
          <div className="pc-healthbadges">
            <StatusBadge label={status.label} tone={status.tone} glyph={status.glyph} />
            {trend && <StatusBadge label={trend.label} tone={trend.tone} glyph={trend.glyph} />}
          </div>
        </header>

        {latest ? (
          <>
            <div className="pc-healthinsight">
              {unreadable ? (
                /* Saved with its reason, and presented as an outcome rather than an
                   error, because that is what it is. */
                <p className="pc-healthnote">
                  {latest.insufficient_information_reason ||
                    'לא הצלחנו לקבוע את מצב הצמח מהתמונות האלה.'}
                </p>
              ) : latest.issues.length === 0 && latest.recommendations.length === 0 ? (
                <p className="pc-healthnote">הבדיקה לא העלתה ממצא מיוחד.</p>
              ) : null}

              {latest.issues.map((issue, index) => (
                <p key={index} className="pc-healthissue">
                  <span className="pc-healthissuename">
                    {issue.issue_name}
                    {issue.severity && SEVERITY_LABELS[issue.severity]
                      ? ` · חומרה ${SEVERITY_LABELS[issue.severity]}`
                      : ''}
                  </span>
                  {/* §16: an issue a reader cannot check is one they can only believe. */}
                  {issue.evidence && (
                    <span className="pc-healthevidence">על סמך: {issue.evidence}</span>
                  )}
                </p>
              ))}

              {latest.recommendations.map((text, index) => (
                <p key={index} className="pc-healthreco">
                  <span className="pc-healthrecoglyph" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M4 12.5l5 5L20 6.5" />
                    </svg>
                  </span>
                  {text}
                </p>
              ))}
            </div>

            <button
              type="button"
              className="pc-healthdate"
              onClick={() => onOpenAssessment(latest.id)}
            >
              <span className="pc-healthdatelabel">נבדק ב־{formatStamp(latest.created_at)}</span>
              <span className="pc-healthdatego">לבדיקה המלאה</span>
            </button>
          </>
        ) : (
          <p className="pc-healthnote">עדיין לא בוצעה בדיקת בריאות לצמח הזה.</p>
        )}

        {health && health.history.length > 0 && (
          <div className="pc-healthpast">
            <span className="pc-eyebrow">בדיקות קודמות</span>
            <ul>
              {health.history.map((entry) => (
                <li key={entry.id}>
                  <PastCheck entry={entry} onOpen={onOpenAssessment} />
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="pc-healthactions">
          {/* The check runs on the plant's own page, where its photographs are. */}
          <Link to={`/plants/${plant.id}?health-check=1`} className="pc-btn pc-btn-sm">
            בדיקה חדשה
          </Link>
          <Link to={`/plants/${plant.id}`} className="pc-btn pc-btn-sm pc-btn-quiet">
            לדף הצמח
          </Link>
        </div>
      </div>
    </article>
  )
}

/** A date and the verdict it reached. Nothing else — the rest is one press away. */
function PastCheck({
  entry,
  onOpen,
}: {
  entry: HealthHistoryEntry
  onOpen: (assessmentId: string) => void
}) {
  const status = statusStyle(entry.overall_status)
  return (
    <button
      type="button"
      className={`pc-pastcheck pc-tone-${status.tone}`}
      onClick={() => onOpen(entry.id)}
    >
      <span className="pc-pastdate">{formatStamp(entry.created_at)}</span>
      <span className="pc-pastverdict">
        <span aria-hidden="true">{status.glyph}</span> {status.label}
      </span>
    </button>
  )
}
