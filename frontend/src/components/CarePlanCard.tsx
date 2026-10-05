/* The care plan in force, and the one thing the user may change about it.
 *
 * FINAL section 12's central rule becomes visible here: professional recommendations
 * are rendered as text with no edit control anywhere near them, while frequency sits
 * in an input. A user should be able to tell which half they own by looking, without
 * reading a note about it.
 *
 * `Recommendations` and `RuleList` are exported because the proposal dialog shows the
 * same two things about a plan that is not active yet. One renderer, so the plan a
 * user approves cannot be described differently from the plan they end up with.
 */

import { useState } from 'react'
import { whyNotSaveable } from '../api/carePlan'
import { actionLabel } from '../api/careTasks'
import type { CarePlanVersion, CareRule } from '../api/plantDetail'
import {
  RECOMMENDATION_LABELS,
  SOURCE_LABELS,
  WEEKDAY_LABELS,
  clockTime,
  intervalText,
} from '../lib/careVocab'
import {
  INTENSITY_LABELS,
  scheduleLine,
  warningText,
  type CareIntensity,
  type CareScheduleSummary,
} from '../lib/careSchedule'
import { ApiError } from '../lib/errors'
import ReviewBadge from './ReviewBadge'
import './CarePlanCard.css'

/**
 * The professional half. Text only — there is no input anywhere in this function.
 *
 * FINAL section 12 says this content is not directly editable. The clearest way to
 * say so is to give it nothing to type into.
 */
export function Recommendations({
  recommendations,
}: {
  recommendations: CarePlanVersion['professional_recommendations']
}) {
  const warnings = (recommendations.warnings ?? []) as string[]

  return (
    <div className="pc-recommendations">
      {recommendations.summary && <p>{recommendations.summary}</p>}

      {RECOMMENDATION_LABELS.map(([field, label]) => {
        const text = recommendations[field] as string | undefined
        if (!text) return null
        return (
          <details key={field} className="pc-reco">
            <summary>{label}</summary>
            <p>{text}</p>
          </details>
        )
      })}

      {warnings.map((warning, index) => (
        <p key={index} className="pc-warning" role="note">
          {warning}
        </p>
      ))}
    </div>
  )
}

function ruleLine(rule: Pick<CareRule, 'interval_days' | 'preferred_time_local'> & {
  preferred_weekday?: string | null
}): string {
  let line = `${intervalText(rule.interval_days)} בשעה ${clockTime(rule.preferred_time_local)}`
  if (rule.preferred_weekday) {
    line += ` · בימי ${WEEKDAY_LABELS[rule.preferred_weekday] ?? rule.preferred_weekday}`
  }
  return line
}

export function RuleList({ rules }: { rules: CareRule[] }) {
  if (!rules.length) return <p className="pc-placeholder-note">אין כללי טיפול בתוכנית הזו.</p>

  return (
    <ul className="pc-rulelist">
      {rules.map((rule) => (
        <li key={rule.id} className="pc-rule">
          <p className="pc-ruleaction">{actionLabel(rule.action_type)}</p>
          <p className="pc-ruledetail">{ruleLine(rule)}</p>
          {rule.instructions && <p className="pc-placeholder-note">{rule.instructions}</p>}
        </li>
      ))}
    </ul>
  )
}

export default function CarePlanCard({
  plan,
  onAdjust,
  adjusting,
  adjustError,
  canEdit,
  schedule = null,
  onSetIntensity,
  settingIntensity = false,
  intensitySaved = false,
  intensityError = null,
}: {
  plan: CarePlanVersion
  onAdjust: (overrides: Record<string, { interval_days: number }>, summary: string) => void
  adjusting: boolean
  adjustError: unknown
  canEdit: boolean
  schedule?: CareScheduleSummary | null
  onSetIntensity?: (intensity: CareIntensity | null) => void
  settingIntensity?: boolean
  intensitySaved?: boolean
  intensityError?: unknown
}) {
  const grouped = schedule && schedule.effective !== 'HIGH' && schedule.care_days.length > 0

  return (
    <section className="pc-card pc-planCard">
      <div className="pc-planhead">
        <h3>תוכנית הטיפול</h3>
        <ReviewBadge review={plan.knowledge_review} />
      </div>
      {/* One sentence, outside the fold: the rules below still say "every 3 days",
          and this is what reconciles them with tasks that arrive on care days. */}
      {grouped && <p className="pc-scheduleline">{scheduleLine(schedule.care_days)}</p>}
      <p className="pc-placeholder-note">
        גרסה <span className="pc-num">{plan.version_number}</span> ·{' '}
        {SOURCE_LABELS[plan.source_type] ?? plan.source_type}
      </p>

      <h4>ההמלצות המקצועיות</h4>
      <Recommendations recommendations={plan.professional_recommendations} />

      {/* Folded away, with the one control that changes it inside. The schedule is a
          list of four or five rules and a form under it — the longest thing on this
          card, read once when the plan is new and then left alone, and it sat open
          between the advice above it and whatever came next. Closed, "התזמון שלך" is
          one line; open, everything about the schedule is in one place, which is also
          where it is changed from. */}
      <details className="pc-schedule">
        <summary>התזמון שלך</summary>
        <RuleList rules={plan.rules} />

        {canEdit && schedule && onSetIntensity && (
          <IntensityControl
            schedule={schedule}
            onChange={onSetIntensity}
            saving={settingIntensity}
            saved={intensitySaved}
            error={intensityError}
          />
        )}

        {canEdit && (
          <AdjustForm
            plan={plan}
            onAdjust={onAdjust}
            adjusting={adjusting}
            adjustError={adjustError}
          />
        )}
      </details>
    </section>
  )
}

const FOLLOW = 'FOLLOW'

/**
 * This plant's care intensity: follow Settings (the default), or pin it.
 *
 * Deliberately not part of the frequency form below it. That form makes a proposal to
 * approve; this applies the moment it changes, and the caption says so, because two
 * controls that look alike and behave differently is the confusion to avoid.
 */
function IntensityControl({
  schedule,
  onChange,
  saving,
  saved,
  error,
}: {
  schedule: CareScheduleSummary
  onChange: (intensity: CareIntensity | null) => void
  saving: boolean
  saved: boolean
  error: unknown
}) {
  const value = schedule.override ?? FOLLOW

  return (
    <div className="pc-intensity">
      <label className="pc-field">
        <span>ימי טיפול</span>
        <select
          value={value}
          disabled={saving}
          onChange={(event) =>
            onChange(
              event.target.value === FOLLOW ? null : (event.target.value as CareIntensity),
            )
          }
        >
          <option value={FOLLOW}>
            לפי ההגדרות ({INTENSITY_LABELS[schedule.owner_intensity]})
          </option>
          {(['HIGH', 'MEDIUM', 'LOW'] as const).map((level) => (
            <option key={level} value={level}>
              {INTENSITY_LABELS[level]}
            </option>
          ))}
        </select>
        <small>חל מיד, בלי אישור. ימי הטיפול עצמם נקבעים בהגדרות.</small>
      </label>

      {saved && !saving && (
        <p className="pc-formnotice" role="status">
          עודכן.
        </p>
      )}
      {error ? (
        <p className="pc-formerror" role="alert">
          {error instanceof ApiError ? error.message : 'השינוי לא נשמר.'}
        </p>
      ) : null}

      {schedule.warnings.length > 0 && (
        <div className="pc-intensitywarn" role="note">
          <ul>
            {schedule.warnings.map((warning) => (
              <li key={warning.action_type}>{warningText(warning)}</li>
            ))}
          </ul>
          <button
            type="button"
            className="pc-btn pc-btn-sm"
            disabled={saving}
            onClick={() => onChange('HIGH')}
          >
            להשאיר את הצמח הזה על גבוהה
          </button>
        </div>
      )}
    </div>
  )
}

/**
 * Change frequency. Nothing else.
 *
 * That is the editable half of section 12, and keeping it in its own disclosure keeps
 * it visually separate from the advice above it.
 *
 * The caption says what the control does *before* it is used. An earlier version said
 * the professional recommendations are preserved — true, and not the thing a user is
 * about to be surprised by. An adjustment produces a proposal: the schedule does not
 * move until it is approved, and "manual changing does nothing" was made of exactly
 * that expectation.
 */
function AdjustForm({
  plan,
  onAdjust,
  adjusting,
  adjustError,
}: {
  plan: CarePlanVersion
  onAdjust: (overrides: Record<string, { interval_days: number }>, summary: string) => void
  adjusting: boolean
  adjustError: unknown
}) {
  const [days, setDays] = useState<Record<string, number>>(() =>
    Object.fromEntries(plan.rules.map((rule) => [rule.id, rule.interval_days])),
  )
  const [summary, setSummary] = useState('')

  const overrides: Record<string, { interval_days: number }> = {}
  for (const rule of plan.rules) {
    const next = days[rule.id]
    if (Number.isFinite(next) && next !== rule.interval_days) {
      overrides[rule.action_type] = { interval_days: next }
    }
  }

  const blocked = whyNotSaveable(overrides, summary)

  return (
    <details className="pc-adjust">
      <summary>שינוי תדירות</summary>

      <p className="pc-placeholder-note">
        אפשר לשנות מתי מזכירים לך. ההמלצות המקצועיות נשארות כפי שהן. השינוי נשמר כהצעה
        שממתינה לאישור שלכם — לוח הזמנים מתעדכן רק אחרי שתאשרו אותה.
      </p>

      {plan.rules.map((rule) => (
        <label key={rule.id} className="pc-field">
          <span>{actionLabel(rule.action_type)} — כל כמה ימים</span>
          <input
            type="number"
            min={1}
            max={365}
            value={days[rule.id] ?? rule.interval_days}
            onChange={(event) =>
              setDays((current) => ({ ...current, [rule.id]: Number(event.target.value) }))
            }
          />
        </label>
      ))}

      <label className="pc-field">
        <span>מה השתנה? (חובה)</span>
        <input
          type="text"
          maxLength={500}
          value={summary}
          onChange={(event) => setSummary(event.target.value)}
          placeholder="למשל: הדירה חמה יותר בקיץ"
        />
        <small>נשמר בהיסטוריית הגרסאות, כדי שיהיה אפשר להבין מאוחר יותר למה השתנה משהו.</small>
      </label>

      {adjustError ? (
        <p className="pc-formerror" role="alert">
          {adjustError instanceof ApiError ? adjustError.message : 'לא הצלחנו לשמור את השינוי.'}
        </p>
      ) : null}

      <button
        type="button"
        className="pc-btn"
        disabled={Boolean(blocked) || adjusting}
        onClick={() => onAdjust(overrides, summary.trim())}
      >
        {adjusting ? 'שומרים…' : 'שמירת השינוי'}
      </button>

      {/* Why the button is disabled, said out loud. Both rules are real — a version
          after the first cannot be written without a change summary, and an adjustment
          with no override is not an adjustment — but the Streamlit screen enforced
          them in silence, and a greyed-out button with no reason beside it is
          indistinguishable from a broken one. */}
      {blocked && <p className="pc-placeholder-note">{blocked}</p>}
    </details>
  )
}
