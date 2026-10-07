/* "A new version is ready." The prompt vite.config.ts assumes exists.
 *
 * `registerType: 'prompt'` was chosen deliberately, and the reason is good: a
 * service worker that activates on its own can reload the page underneath someone
 * who has just marked a task done or approved a plan, and that work is gone with no
 * explanation. So the new worker installs and waits to be told.
 *
 * Nothing ever told it. The prompt was never built, so every update downloaded,
 * entered `waiting`, and stayed there — the old bundle kept serving until the user
 * happened to close every tab and window of the app at once. Deploying changed
 * nothing anybody could see. That is the worst of both: the caution of `prompt` and
 * the staleness of no update mechanism at all.
 *
 * This is the missing half. The worker still never activates by itself; it activates
 * when the user says so, which is the whole point of the setting. Settings has a
 * button that asks for the same thing on demand; both go through `lib/appUpdate`, so
 * the worker is registered once.
 */

import { useEffect, useState } from 'react'
import { applyUpdate, onUpdateWaiting, updateWaiting } from '../lib/appUpdate'
import './UpdatePrompt.css'

export default function UpdatePrompt() {
  const [ready, setReady] = useState(updateWaiting)
  const [dismissed, setDismissed] = useState(false)

  useEffect(() => onUpdateWaiting(() => setReady(true)), [])

  if (!ready || dismissed) return null

  return (
    <div className="pc-updateprompt" role="status">
      <span>יש גרסה חדשה של האפליקציה.</span>
      <button type="button" className="pc-btn pc-btn-sm" onClick={() => void applyUpdate()}>
        רענון
      </button>
      {/* Dismissable, because "later" is a legitimate answer. The worker stays in
          `waiting` and the prompt returns on the next load, so the update is
          postponed rather than refused. */}
      <button
        type="button"
        className="pc-updateprompt-later"
        onClick={() => setDismissed(true)}
        aria-label="לא עכשיו"
      >
        ×
      </button>
    </div>
  )
}
