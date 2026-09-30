/* What actually changes if the user approves a proposal (FINAL section 12).
 *
 * A port of app/domain/services/care_plan_diff.py, field for field. The API sends
 * both `rules` and `current_rules` on a proposal and computes no difference between
 * them, so the comparison has to happen on whichever client is showing it — this is
 * the second copy of it, and the two are kept identical deliberately.
 *
 * Pure: no clock, no fetch. A comparison a user leans on to make a decision must not
 * be something that varies run to run.
 */

/* What counts as a difference. `instructions` deliberately does not: the agent
   rewords the same advice run to run, and reporting "the wording changed" as a change
   to the schedule would bury the ones that matter. */
const COMPARED = ['interval_days', 'preferred_time_local', 'preferred_weekday'] as const

export type ComparedField = (typeof COMPARED)[number]

export type RuleLike = {
  action_type: string
  interval_days?: number
  preferred_time_local?: string
  preferred_weekday?: string | null
  is_active?: boolean
  [key: string]: unknown
}

export type ChangeKind = 'changed' | 'added' | 'removed' | 'unchanged'

export type RuleChange = {
  actionType: string
  kind: ChangeKind
  before?: RuleLike
  after?: RuleLike
  fields: ComparedField[]
}

/* One rule per action is the shape the Care Agent produces and the shape the schedule
   assumes: two watering rules on one plant would materialise two tasks and tell the
   user to water twice. Keyed on action for the same reason. */
function active(rules: RuleLike[]): Map<string, RuleLike> {
  const found = new Map<string, RuleLike>()
  for (const rule of rules) {
    if (rule.is_active === false) continue
    if (!rule.action_type) continue
    found.set(rule.action_type, rule)
  }
  return found
}

/**
 * Compare `08:00` and `08:00:00` as equal.
 *
 * Postgres returns `time` as `HH:MM:SS`; the agent's contract accepts `HH:MM`.
 * Without this every proposal would report a time change on every rule, which would
 * make the whole diff worthless by crying wolf on all of it.
 */
function normalise(value: unknown): string | null {
  if (value === null || value === undefined) return null
  const text = String(value)
  if (text.length === 5 && text[2] === ':') return `${text}:00`
  return text
}

const ORDER: Record<ChangeKind, number> = { changed: 0, added: 1, removed: 2, unchanged: 3 }

/**
 * Compare two sets of care rules, what changed first.
 *
 * An empty `current` yields every proposed rule as `added`, which is the honest
 * description of a first plan — the caller decides whether to render that as a diff
 * or simply as the plan.
 */
export function diffRules(current: RuleLike[] | null, proposed: RuleLike[] | null): RuleChange[] {
  const before = active(current ?? [])
  const after = active(proposed ?? [])

  const actions = [...new Set([...before.keys(), ...after.keys()])].sort()
  const changes: RuleChange[] = []

  for (const action of actions) {
    const old = before.get(action)
    const next = after.get(action)

    if (!old && next) {
      changes.push({ actionType: action, kind: 'added', after: next, fields: [] })
    } else if (old && !next) {
      changes.push({ actionType: action, kind: 'removed', before: old, fields: [] })
    } else if (old && next) {
      const fields = COMPARED.filter((field) => normalise(old[field]) !== normalise(next[field]))
      changes.push({
        actionType: action,
        kind: fields.length ? 'changed' : 'unchanged',
        before: old,
        after: next,
        fields: [...fields],
      })
    }
  }

  return changes.sort(
    (a, b) => ORDER[a.kind] - ORDER[b.kind] || a.actionType.localeCompare(b.actionType),
  )
}

export function hasChanges(changes: RuleChange[]): boolean {
  return changes.some((change) => change.kind !== 'unchanged')
}
