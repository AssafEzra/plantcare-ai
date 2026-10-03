/* What a health check found, in the shape a card can carry.
 *
 * Shared by the בריאות list and by the plant's own page, which had drifted into two
 * different answers to the same question: the list showed the top finding, its evidence
 * and the first recommendations, and the plant page rendered the whole assessment
 * inline — a wall of prose between the care plan and the growing conditions, which is
 * where a reader stops reading.
 *
 * Both now show the same summary and both open the same dialog for the rest. §16 is
 * what makes that split safe rather than lossy: an issue is a possibility, it always
 * travels with the evidence it rests on even in the two-line form, and the full
 * reasoning is one press away rather than one navigation away.
 */

import type { HealthHistoryEntry, IssueBrief } from '../api/health'
import { SEVERITY_LABELS } from '../lib/careVocab'
import { formatStamp } from '../lib/dates'
import { statusStyle } from '../lib/status'
import './HealthInsight.css'

export function HealthInsight({
  issues,
  recommendations,
  unreadable,
  reason,
}: {
  issues: IssueBrief[]
  recommendations: string[]
  /** The check could not reach a verdict — an outcome, not an error. */
  unreadable: boolean
  reason?: string | null
}) {
  return (
    <div className="pc-healthinsight">
      {unreadable ? (
        <p className="pc-healthnote">
          {reason || 'לא הצלחנו לקבוע את מצב הצמח מהתמונות האלה.'}
        </p>
      ) : issues.length === 0 && recommendations.length === 0 ? (
        <p className="pc-healthnote">הבדיקה לא העלתה ממצא מיוחד.</p>
      ) : null}

      {issues.map((issue, index) => (
        <p key={index} className="pc-healthissue">
          <span className="pc-healthissuename">
            {issue.issue_name}
            {issue.severity && SEVERITY_LABELS[issue.severity]
              ? ` · חומרה ${SEVERITY_LABELS[issue.severity]}`
              : ''}
          </span>
          {/* §16: an issue a reader cannot check is one they can only believe. */}
          {issue.evidence && <span className="pc-healthevidence">על סמך: {issue.evidence}</span>}
        </p>
      ))}

      {recommendations.map((text, index) => (
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
  )
}

/** When the check ran, and the way into it. The date is the handle, deliberately. */
export function AssessedPill({ at, onOpen }: { at: string; onOpen: () => void }) {
  return (
    <button type="button" className="pc-healthdate" onClick={onOpen}>
      <span className="pc-healthdatelabel">נבדק ב־{formatStamp(at)}</span>
      <span className="pc-healthdatego">לבדיקה המלאה</span>
    </button>
  )
}

/**
 * The checks before this one: a date and the verdict it reached, nothing else.
 *
 * Previous assessments are never modified (§16), so this is an append-only record of
 * what was thought at each point — and what makes it worth showing is the direction of
 * travel, which a list repeating every finding would bury.
 */
export function PastChecks({
  entries,
  onOpen,
}: {
  entries: HealthHistoryEntry[]
  onOpen: (assessmentId: string) => void
}) {
  if (!entries.length) return null

  return (
    <div className="pc-healthpast">
      <span className="pc-eyebrow">בדיקות קודמות</span>
      <ul>
        {entries.map((entry) => {
          const status = statusStyle(entry.overall_status)
          return (
            <li key={entry.id}>
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
            </li>
          )
        })}
      </ul>
    </div>
  )
}
