/* Why the session ended, written down on the device.
 *
 * The app signs itself out now and then, and nothing recorded why. The database can
 * say what the *server* did, and for these events the answer was "nothing": the
 * sessions were still live, still refreshing, never revoked. So the loss happens in
 * the browser, and the browser is where it has to be caught - by the time anyone can
 * ask, the only evidence left is a login screen.
 *
 * `onAuthStateChange` already knows. It reports `SIGNED_OUT` with the same words
 * whether the user pressed יציאה or a token refresh was refused, and the handler
 * discarded the event name entirely. Keeping it, with a timestamp and whether we
 * asked for it, is the whole of this file.
 *
 * It lives in `localStorage` because at the moment a session ends there is no token
 * left to report anything to the API with, and because the next launch - possibly
 * days later - is when someone will want to read it.
 */

const KEY = 'pc.session-ends'

/** Enough to see a pattern, few enough to read at a glance. */
const KEEP = 10

/** How long after asking for a sign-out the resulting event still counts as ours. */
const DELIBERATE_WINDOW_MS = 10_000

export type SessionEnd = {
  /** ISO 8601, UTC. */
  at: string
  /** The Supabase event, kept verbatim rather than interpreted. */
  event: string
  /** True when this app asked for it - the יציאה button. */
  deliberate: boolean
}

/* Set by `signOut` just before it asks Supabase to end the session, and read by the
 * listener a moment later. A module variable rather than storage: the two run in the
 * same tab within a few milliseconds of each other, and a value that outlived the
 * page would be worse than none - it would label the next spontaneous sign-out as
 * deliberate, which is the one distinction this file exists to make. */
let askedAt = 0

export function signingOutDeliberately(): void {
  askedAt = Date.now()
}

function wasDeliberate(): boolean {
  const asked = askedAt !== 0 && Date.now() - askedAt < DELIBERATE_WINDOW_MS
  askedAt = 0
  return asked
}

export function recordSessionEnd(event: string): void {
  const entry: SessionEnd = {
    at: new Date().toISOString(),
    event,
    deliberate: wasDeliberate(),
  }
  try {
    window.localStorage.setItem(KEY, JSON.stringify([entry, ...sessionEnds()].slice(0, KEEP)))
  } catch {
    /* Private mode, or storage is full. A diagnostic that breaks the thing it is
       diagnosing is worse than no diagnostic. */
  }
}

export function sessionEnds(): SessionEnd[] {
  try {
    const raw = window.localStorage.getItem(KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    /* Validated rather than trusted. This is storage a previous version of the app
       wrote, and the shape is allowed to have changed under us. */
    return parsed.filter(
      (row): row is SessionEnd =>
        typeof row === 'object' &&
        row !== null &&
        typeof (row as SessionEnd).at === 'string' &&
        typeof (row as SessionEnd).event === 'string' &&
        typeof (row as SessionEnd).deliberate === 'boolean',
    )
  } catch {
    return []
  }
}
