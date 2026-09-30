/* Approving a care plan, in a window, with what actually changes (FINAL section 12).
 *
 * Two things are deliberate here. It opens as a dialog, so the decision has the screen
 * to itself rather than competing with the health card and the timeline — the inline
 * version put an approve/reject choice in the middle of a scrolling page. And above
 * the plan it shows the *difference*: the agent's sentence first, because that is the
 * why, then the computed diff, which is the what.
 *
 * The diff is `lib/carePlanDiff.ts`: pure, deterministic, a port of the Python of the
 * same name. A comparison a user leans on to make a decision must not be something a
 * model rephrases differently each run — showing both schedules in full and leaving
 * the reader to spot that watering moved from seven days to five is work the software
 * should do.
 *
 * A first plan has nothing to diff against, and says so by simply showing the plan.
 */

import { actionLabel } from '../api/careTasks'
import type { CarePlanVersion } from '../api/plantDetail'
import { SOURCE_LABELS, WEEKDAY_LABELS } from '../lib/careVocab'
import { diffRules, hasChanges, type ComparedField, type RuleChange } from '../lib/carePlanDiff'
import { ApiError } from '../lib/errors'
import Modal from './Modal'
import { Recommendations, RuleList } from './CarePlanCard'
import './ProposalDialog.css'

const FIELD_LABELS: Record<ComparedField, string> = {
  interval_days: 'תדירות',
  preferred_time_local: 'שעה',
  preferred_weekday: 'יום בשבוע',
}

const REVIEW_NOTICES: Record<string, { tone: 'warning' | 'danger'; text: string }> = {
  pending: {
    tone: 'warning',
    text: 'המידע המקצועי שעליו מבוססת התוכנית ממתין לאישור מומחה.',
  },
  rejected: {
    tone: 'danger',
    text: 'המידע המקצועי שעליו מבוססת התוכנית לא אושר. אנחנו מכינים גרסה מתוקנת.',
  },
}

function valueText(field: ComparedField, value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (field === 'interval_days') {
    const days = Number(value)
    return days === 1 ? 'כל יום' : `כל ${days} ימים`
  }
  if (field === 'preferred_weekday') return WEEKDAY_LABELS[String(value)] ?? String(value)
  return String(value).slice(0, 5)
}

/**
 * One rule's difference, as a sentence.
 *
 * Written to be read in one pass: what it is, then what happened, then the numbers.
 * Anything that needs the reader to hold two lists in their head is the problem this
 * is solving.
 */
function changeLine(change: RuleChange): string {
  const label = actionLabel(change.actionType)

  if (change.kind === 'added') {
    return `${label} · נוסף, ${valueText('interval_days', change.after?.interval_days)}`
  }
  if (change.kind === 'removed') return `${label} · הוסר`
  if (change.kind === 'changed') {
    const parts = change.fields.map(
      (field) =>
        `${FIELD_LABELS[field]}: ${valueText(field, change.before?.[field])} ← ${valueText(
          field,
          change.after?.[field],
        )}`,
    )
    return `${label} · ${parts.join(' · ')}`
  }
  return `${label} · ללא שינוי`
}

function Changes({ proposal }: { proposal: CarePlanVersion }) {
  // No previous plan means nothing to compare against, which is the honest state of a
  // first plan rather than a diff worth drawing.
  if (!proposal.current_rules.length) return null

  const changes = diffRules(proposal.current_rules, proposal.rules)

  if (!hasChanges(changes)) {
    // Worth saying out loud. A proposal that changes no rule is a recommendation
    // change only, and a user who approves expecting a new schedule should not have
    // to discover that by watching for one.
    return (
      <p className="pc-formnotice" role="status">
        לוח הזמנים נשאר כפי שהוא. ההמלצות המקצועיות עודכנו.
      </p>
    )
  }

  const unchanged = changes.filter((change) => change.kind === 'unchanged')

  return (
    <div className="pc-changes">
      <h4>מה משתנה</h4>
      <ul>
        {changes
          .filter((change) => change.kind !== 'unchanged')
          .map((change) => (
            <li key={change.actionType}>{changeLine(change)}</li>
          ))}
      </ul>
      {unchanged.length > 0 && (
        <p className="pc-placeholder-note">
          ללא שינוי: {unchanged.map((change) => actionLabel(change.actionType)).join(' · ')}
        </p>
      )}
    </div>
  )
}

export default function ProposalDialog({
  proposal,
  onApprove,
  onReject,
  onClose,
  busy,
  error,
}: {
  proposal: CarePlanVersion
  onApprove: () => void
  onReject: () => void
  onClose: () => void
  busy: boolean
  error: unknown
}) {
  const notice = REVIEW_NOTICES[proposal.knowledge_review]
  const missing = ((proposal.operational_preferences?.missing_context ?? []) as string[]) || []

  return (
    <Modal title="הצעת עדכון לתוכנית טיפול" onClose={onClose}>
      <h3>{SOURCE_LABELS[proposal.source_type] ?? proposal.source_type}</h3>
      <p className="pc-placeholder-note">
        גרסה <span className="pc-num">{proposal.version_number}</span>
      </p>

      {notice && (
        <p className={notice.tone === 'danger' ? 'pc-formerror' : 'pc-formnotice'} role="status">
          {notice.text}
        </p>
      )}

      {/* The agent's own sentence first: it is the reason, and the diff below is the
          consequence. Reversed, the numbers arrive with nothing to explain them. */}
      {proposal.change_summary && <p className="pc-changesummary">{proposal.change_summary}</p>}

      <Changes proposal={proposal} />

      <h4>ההמלצות המקצועיות</h4>
      <Recommendations recommendations={proposal.professional_recommendations} />

      <h4>מה נתזמן עבורך</h4>
      <RuleList rules={proposal.rules} />

      {/* Not a question. Nothing here waits on an answer. */}
      {missing.length > 0 && (
        <p className="pc-placeholder-note">מידע שהיה עוזר לדייק את התוכנית: {missing.join(' · ')}</p>
      )}

      {error ? (
        <p className="pc-formerror" role="alert">
          {error instanceof ApiError ? error.message : 'משהו השתבש. אפשר לנסות שוב.'}
        </p>
      ) : null}

      <div className="pc-actionrow">
        <button type="button" className="pc-btn" disabled={busy} onClick={onApprove}>
          {busy ? 'מעדכנים…' : 'אישור התוכנית'}
        </button>
        <button
          type="button"
          className="pc-btn pc-btn-quiet"
          disabled={busy}
          onClick={onReject}
        >
          דחייה
        </button>
      </div>
    </Modal>
  )
}
