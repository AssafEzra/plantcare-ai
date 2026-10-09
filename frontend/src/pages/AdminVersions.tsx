/* Three versions, side by side.
 *
 * "Is what I am looking at running the code we think it is?" had no answer inside
 * the application, and getting it wrong cost real time twice: once a liveness check
 * answered `ok` from an API process started an hour earlier, and the restart was
 * reported as done; once a service worker served an old bundle from a current
 * server, and the only way to find out was reading a script name in developer
 * tools.
 *
 * Three things go stale on their own and look identical from outside - the deployed
 * service, the local API process, and the bundle this browser cached - so all three
 * are shown rather than one summary verdict. The verdicts themselves live in
 * `adminVersions.ts`; this file only renders them.
 *
 * A table, not a list: it is a matrix with a column of labels and a column of
 * values, and a real `<th scope="row">` gives a screen reader the pairing for free.
 */

import { useState } from 'react'
import { useVersions } from '../api/admin'
import { BUILD_COMMIT, BUILD_TIME, applyUpdate, checkForUpdate, updateWaiting } from '../lib/appUpdate'
import { describeVersions, type Tone } from './versionRows'
import Async from '../components/Async'

const TONE_CLASS: Record<Tone, string> = {
  ok: 'pc-versions-ok',
  warn: 'pc-versions-warn',
  fail: 'pc-fail',
  muted: 'pc-versions-muted',
}

/* The one action this block offers. A bare reload cannot fix a stale bundle - a
   worker in control re-serves the same cached shell, which is the exact failure
   being diagnosed here - so the waiting worker is activated when there is one, and
   a reload is the fallback for the dev server, which registers no worker at all. */
async function refresh(): Promise<void> {
  await checkForUpdate()
  if (updateWaiting()) {
    await applyUpdate()
    return
  }
  window.location.reload()
}

export default function AdminVersions() {
  const query = useVersions()
  const [busy, setBusy] = useState(false)

  return (
    <Async query={query} loadingLabel="טוען גרסאות…">
      {query.data && (
        <table className="pc-versions">
          <tbody>
            {describeVersions(query.data, BUILD_COMMIT, BUILD_TIME).map((row) => (
              <tr key={row.label}>
                <th scope="row">{row.label}</th>
                <td>
                  {row.commit ? (
                    <span className="pc-ltr pc-commit">{row.commit}</span>
                  ) : (
                    <span aria-hidden="true">—</span>
                  )}
                </td>
                <td className={TONE_CLASS[row.tone]}>{row.note}</td>
                <td>
                  {row.refresh && (
                    <button
                      type="button"
                      className="pc-btn pc-btn-sm"
                      disabled={busy}
                      onClick={() => {
                        setBusy(true)
                        void refresh().finally(() => setBusy(false))
                      }}
                    >
                      {busy ? 'מרעננים…' : 'רענון'}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Async>
  )
}
