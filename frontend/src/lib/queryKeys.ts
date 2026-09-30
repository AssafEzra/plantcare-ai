/* Query keys, scoped to the acting identity.
 *
 * This is not decoration. `st.cache_data` in the Streamlit build is keyed on its
 * arguments and shared across sessions, so `cached_get` mixes the user id — and the
 * view-as target — into the key. A React query cache is per-tab rather than
 * per-server, so the cross-user leak is not the risk here; the view-as one is.
 *
 * Without the target in the key, an administrator entering or leaving "view as user"
 * keeps the cache from before the switch and is shown the wrong person's plants. That
 * is a privacy failure that looks exactly like a rendering bug, so the key is built
 * in one place and screens never assemble their own.
 *
 * Usage:  useQuery({ queryKey: scoped(userId, ['plants']), ... })
 */

import { actingAs } from './viewAs'

export type ScopedKey = readonly unknown[]

/**
 * Prefix a key with the identity the request will actually be made as.
 *
 * @param userId the signed-in user's id, or null before sign-in
 * @param key    the logical key, e.g. ['plants'] or ['plant', plantId]
 */
export function scoped(userId: string | null | undefined, key: ScopedKey): ScopedKey {
  return ['u', userId ?? 'anon', 'as', actingAs() ?? 'self', ...key]
}
