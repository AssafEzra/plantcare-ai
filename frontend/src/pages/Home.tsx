/* Home — phase 3 only proves the wiring.
 *
 * The real action-oriented dashboard (today's care with done/skip, plants needing
 * attention, counts) is phase 5. What this shows is that a signed-in browser reaches
 * the API with a working bearer token and gets its own profile back — the whole point
 * of phase 3.
 *
 * It also demonstrates the loading/error/empty discipline section 42 requires of
 * every asynchronous flow.
 */

import { useMe } from '../api/profile'
import { ApiError } from '../lib/errors'

export default function Home() {
  const { data, isPending, error, refetch, isFetching } = useMe()

  return (
    <section className="pc-placeholder">
      <h1>בית</h1>

      {isPending && <p className="pc-placeholder-note">טוען…</p>}

      {error && (
        <>
          <p className="pc-formerror" role="alert">
            {error instanceof ApiError ? error.message : 'משהו השתבש. אפשר לנסות שוב.'}
          </p>
          <button type="button" className="pc-btn" onClick={() => refetch()} disabled={isFetching}>
            נסו שוב
          </button>
        </>
      )}

      {data && (
        <>
          <p>
            שלום {data.display_name || data.email}. החיבור ל-API עובד.
          </p>
          <dl className="pc-kv">
            <dt>אימייל</dt>
            <dd className="pc-ltr">{data.email}</dd>
            <dt>הרשאה</dt>
            <dd>{data.role === 'ADMIN' ? 'מנהל מערכת' : 'משתמש'}</dd>
            <dt>אזור זמן</dt>
            <dd className="pc-ltr">{data.timezone}</dd>
          </dl>
          <p className="pc-placeholder-note">
            לוח הבית המלא יועבר בשלב 5 של המיגרציה.
          </p>
        </>
      )}
    </section>
  )
}
