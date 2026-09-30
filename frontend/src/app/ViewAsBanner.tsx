/* "You are looking at someone else's account."
 *
 * Rendered in the shell rather than on the admin screen, because the whole point of
 * the mode is that the administrator then leaves the admin screen: they go to Home,
 * or to a plant, to see what the user sees. A banner that lived on the panel would be
 * invisible exactly when it matters.
 *
 * The mode is read-only and the API enforces that — every non-GET carrying the
 * act-as header is refused — so this says what is happening rather than guarding
 * anything. Leaving it clears the store, which changes every query key through
 * `scoped()`, so the administrator's own data is refetched rather than read from the
 * cache of the account they were just looking at.
 */

import { useQueryClient } from '@tanstack/react-query'
import { leaveViewAs, useViewAs } from '../lib/viewAs'

export default function ViewAsBanner() {
  const { userId, email } = useViewAs()
  const queryClient = useQueryClient()

  if (!userId) return null

  return (
    <div className="pc-viewas" role="status">
      <span>
        צפייה כמשתמש <strong className="pc-ltr">{email ?? userId.slice(0, 8)}</strong> · קריאה
        בלבד
      </span>
      <button
        type="button"
        className="pc-btn pc-btn-sm"
        onClick={() => {
          leaveViewAs()
          /* Not merely invalidate: the keys the cache holds are the ones built while
             acting as somebody else, so they are not stale — they are a different
             person's, and they should not be sitting in memory once the mode ends. */
          queryClient.clear()
        }}
      >
        חזרה לחשבון שלי
      </button>
    </div>
  )
}
