/* Which version this is, and a way to ask for a newer one.
 *
 * "Is the app I am looking at running the code we just deployed?" had no answer
 * inside the app. A stale service worker serves an old bundle from a current
 * server, so the server cannot be asked, and the only way to find out was to read
 * the script name in developer tools. The commit below is baked into this bundle at
 * build time (vite.config.ts), so it describes the code actually running.
 *
 * The button is the same check the worker does on its own, asked on demand:
 * `registration.update()`, then look for a worker in `waiting`.
 */

import { useState } from 'react'
import {
  BUILD_COMMIT,
  BUILD_TIME,
  applyUpdate,
  checkForUpdate,
  updateWaiting,
  updatesSupported,
} from '../lib/appUpdate'
import './VersionCard.css'

type State = 'idle' | 'checking' | 'current' | 'available'

function buildDate(): string {
  // The date alone: the time of day says nothing useful to a reader and makes the
  // line long enough to wrap on a phone.
  try {
    return new Date(BUILD_TIME).toISOString().slice(0, 10)
  } catch {
    return 'unknown'
  }
}

export default function VersionCard() {
  const [state, setState] = useState<State>(() => (updateWaiting() ? 'available' : 'idle'))

  async function check() {
    setState('checking')
    setState((await checkForUpdate()) ? 'available' : 'current')
  }

  return (
    <div className="pc-card pc-version">
      <p className="pc-version-line">
        <span>גרסה</span>{' '}
        <span className="pc-num">{buildDate()}</span>{' '}
        <span className="pc-ltr pc-version-commit">{BUILD_COMMIT}</span>
      </p>

      {!updatesSupported() ? (
        /* No service worker, so there is nothing to check. Said plainly rather
           than offering a button that cannot do anything - which is the mistake
           the knowledge panel made with its empty state. */
        <p className="pc-placeholder-note">בדיקת עדכונים זמינה רק באפליקציה המותקנת.</p>
      ) : state === 'available' ? (
        <>
          <p className="pc-formnotice">יש גרסה חדשה.</p>
          <button type="button" className="pc-btn pc-btn-sm" onClick={() => void applyUpdate()}>
            רענון
          </button>
        </>
      ) : (
        <>
          {state === 'current' && <p className="pc-placeholder-note">האפליקציה מעודכנת.</p>}
          <button
            type="button"
            className="pc-btn pc-btn-sm pc-btn-quiet"
            disabled={state === 'checking'}
            onClick={() => void check()}
          >
            {state === 'checking' ? 'בודקים…' : 'בדיקת עדכון'}
          </button>
        </>
      )}
    </div>
  )
}
