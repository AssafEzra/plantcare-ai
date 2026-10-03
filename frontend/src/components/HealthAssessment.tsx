/* A health assessment (FINAL section 16).
 *
 *     "The Agent must not present definitive diagnosis."
 *
 * The interface carries as much of that as the schema does. Observations and possible
 * issues are rendered in visibly different registers — one is what was seen, the other
 * what it might mean — and an issue always shows the evidence it rests on, so a user
 * can disagree with the reasoning rather than only with the verdict.
 */

import type { Assessment } from '../api/health'
import { CONFIDENCE_LABELS, SEVERITY_LABELS } from '../lib/careVocab'
import { assessedAt } from '../lib/dates'
import { statusStyle, trendStyle } from '../lib/status'
import StatusBadge from './StatusBadge'
import './HealthAssessment.css'

export default function HealthAssessment({
  assessment,
  onAdjustPlan,
  adjusting,
}: {
  assessment: Assessment
  /** Absent when there is no plan to adjust, or the plant is archived. */
  onAdjustPlan?: (assessmentId: string) => void
  adjusting?: boolean
}) {
  const status = statusStyle(assessment.overall_status)
  const trend = assessment.trend ? trendStyle(assessment.trend) : null
  const unreadable = assessment.overall_status === 'UNKNOWN'
  const wantsPlanChange = assessment.recommendations.some((r) => r.requires_care_plan_adjustment)

  return (
    <section className="pc-card pc-assessment">
      <header className="pc-assessmenthead">
        <div>
          <h3>תוצאות הבדיקה</h3>
          <p className="pc-placeholder-note">{assessedAt(assessment.created_at)}</p>
        </div>
        <div className="pc-assessmentbadges">
          <StatusBadge label={status.label} tone={status.tone} glyph={status.glyph} />
          {trend && <StatusBadge label={trend.label} tone={trend.tone} glyph={trend.glyph} />}
        </div>
      </header>

      {trend && unreadable && (
        /* The trend is computed from earlier *readable* checks, so it can be
           meaningful even when this one is not. Beside a "we could not tell" verdict it
           would otherwise read as this check's own conclusion, which is exactly the
           overclaiming section 16 forbids. */
        <p className="pc-placeholder-note">המגמה מבוססת על בדיקות קודמות, לא על הבדיקה הזו.</p>
      )}

      {unreadable && (
        /* An insufficient check is saved with its reason. Presented as an outcome
           rather than an error, because it is one — and the reason says what would
           actually help. */
        <p className="pc-formnotice" role="status">
          {assessment.insufficient_information_reason ||
            'לא הצלחנו לקבוע את מצב הצמח מהתמונות האלה.'}
        </p>
      )}

      {assessment.confidence_level && (
        <p className="pc-placeholder-note">
          רמת ודאות: {CONFIDENCE_LABELS[assessment.confidence_level] ?? assessment.confidence_level}
        </p>
      )}

      {assessment.observations.length > 0 && (
        <>
          <h4>מה נראה בתמונות</h4>
          <ul>
            {assessment.observations.map((observation, index) => (
              <li key={index}>{observation.observation_text}</li>
            ))}
          </ul>
        </>
      )}

      {assessment.possible_issues.length > 0 && (
        <>
          <h4>ממצאים אפשריים</h4>
          {/* Deliberately framed as possibilities, and each one shows what it rests on.
              A finding a user cannot check is a finding they can only believe or
              ignore. */}
          <p className="pc-placeholder-note">
            אלה אפשרויות, לא אבחנה. כדאי לבדוק אותן מול הצמח עצמו.
          </p>
          <ul className="pc-issues">
            {assessment.possible_issues.map((issue, index) => (
              <li key={index} className="pc-issue">
                <p className="pc-issuename">
                  {issue.issue_name}
                  {issue.severity && SEVERITY_LABELS[issue.severity]
                    ? ` · חומרה ${SEVERITY_LABELS[issue.severity]}`
                    : ''}
                </p>
                {issue.evidence && (
                  <p className="pc-placeholder-note">על סמך: {issue.evidence}</p>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      {assessment.recommendations.length > 0 && (
        <>
          <h4>מה כדאי לעשות</h4>
          <ul>
            {assessment.recommendations.map((recommendation, index) => (
              <li key={index}>{recommendation.recommendation_text}</li>
            ))}
          </ul>

          {wantsPlanChange && onAdjustPlan && (
            <>
              {/* Section 16: the Health Agent cannot change the plan. This raises a
                  proposal the user approves, which is the only route there is. */}
              <p className="pc-placeholder-note">חלק מההמלצות נוגעות לתדירות הטיפול עצמה.</p>
              <button
                type="button"
                className="pc-btn"
                disabled={adjusting}
                onClick={() => onAdjustPlan(assessment.id)}
              >
                {adjusting ? 'מכינים הצעה…' : 'הצעת עדכון לתוכנית הטיפול'}
              </button>
            </>
          )}
        </>
      )}

      {assessment.sources.length > 0 && (
        <details className="pc-reco">
          <summary>מקורות</summary>
          <ul>
            {assessment.sources.map((source, index) => (
              <li key={index}>
                {source.url ? (
                  <a href={source.url} target="_blank" rel="noopener noreferrer">
                    {source.title || source.url}
                  </a>
                ) : (
                  source.title
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
