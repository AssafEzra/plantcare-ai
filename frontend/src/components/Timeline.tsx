/* The plant's history (FINAL section 19).
 *
 * The timeline merges five sources, so the one thing it must not do is look like five
 * lists stacked together. Every entry gets the same shape — marker, summary, when — and
 * the marker is what says where it came from.
 *
 * Glyphs rather than the Streamlit build's Material icon names, which were a Streamlit
 * feature and are not carried over. Each is `aria-hidden`: it duplicates information
 * the summary already carries in words, which is the rule the status badges follow too.
 */

import type { HistoryEntry } from '../api/plantDetail'
import { timelineWhen } from '../lib/dates'
import './Timeline.css'

const MARKERS: Record<string, string> = {
  PLANT_CREATED: '🌱',
  PLANT_ARCHIVED: '📦',
  PLANT_RESTORED: '↩',
  PLANT_RENAMED: '✎',
  ENVIRONMENT_CHANGED: '🌡',
  MAIN_IMAGE_CHANGED: '🖼',
  REPOTTED: '🪴',
  MOVED: '→',
  PRUNED: '✂',
  CUSTOM_NOTE: '📝',
  CARE_DONE: '✓',
  CARE_SKIPPED: '↷',
  CARE_MISSED: '⏰',
  CARE_CORRECTED: '↺',
  HEALTH_ASSESSMENT: '♥',
  IDENTIFICATION: '🔍',
  CARE_PLAN_VERSION: '📅',
}

const FALLBACK = '•'

export default function Timeline({ entries }: { entries: HistoryEntry[] }) {
  if (!entries.length) return <p className="pc-placeholder-note">עדיין אין היסטוריה לצמח הזה.</p>

  return (
    <ol className="pc-timeline">
      {entries.map((entry, index) => {
        const detail = entry.detail ?? {}
        /* A note the user wrote, or a plan's change summary: the entry says what
           happened, and this says what the person said about it. */
        const note = (detail.note ?? detail.change_summary) as string | undefined

        return (
          <li key={`${entry.occurred_at}-${entry.kind}-${index}`} className="pc-timelineitem">
            <span className="pc-timelinemarker" aria-hidden="true">
              {MARKERS[entry.kind] ?? FALLBACK}
            </span>
            <div className="pc-timelinebody">
              <p className="pc-timelinesummary">{entry.summary}</p>
              <p className="pc-placeholder-note">{timelineWhen(entry.occurred_at)}</p>
              {note && note !== entry.summary && <p className="pc-timelinenote">„{note}”</p>}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
