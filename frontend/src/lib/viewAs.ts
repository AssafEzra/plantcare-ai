/* "View as user" — the id an administrator is currently looking at.
 *
 * A module-level store rather than React state, for the same reason the Streamlit
 * build keeps it in session state (app/ui/state/api_client.py): *every* request must
 * carry the header for the mode to be coherent. A screen that forgot it would blend
 * the administrator's own empty account into somebody else's session. The API client
 * reads this synchronously, so it cannot be missed.
 *
 * The API refuses any non-read method carrying the header, so the mode cannot write
 * even if a screen offers a button.
 */

import { useSyncExternalStore } from 'react'

const KEY = 'pc.actAs'

type State = { userId: string | null; email: string | null }

let state: State = read()
const listeners = new Set<() => void>()

function read(): State {
  try {
    const raw = sessionStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as State) : { userId: null, email: null }
  } catch {
    return { userId: null, email: null }
  }
}

function write(next: State) {
  state = next
  try {
    if (next.userId) sessionStorage.setItem(KEY, JSON.stringify(next))
    else sessionStorage.removeItem(KEY)
  } catch {
    /* private mode — the mode still works for this tab, it just will not survive
       a reload. Losing it fails safe: the admin returns to their own account. */
  }
  listeners.forEach((fn) => fn())
}

/** Read synchronously, from anywhere, including the API client. */
export function actingAs(): string | null {
  return state.userId
}

export function actingAsEmail(): string | null {
  return state.email
}

export function enterViewAs(userId: string, email: string | null) {
  write({ userId, email })
}

export function leaveViewAs() {
  write({ userId: null, email: null })
}

function subscribe(fn: () => void) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

/** React binding, so a banner re-renders when the mode changes. */
export function useViewAs(): State {
  return useSyncExternalStore(
    subscribe,
    () => state,
    () => ({ userId: null, email: null }),
  )
}

/**
 * Is the current session looking at somebody else's account?
 *
 * The API is the enforcement — every non-GET carrying the act-as header is refused —
 * but a screen that still offers the controls invites an administrator to press
 * something that will fail, and a 403 is a worse explanation than not being asked. So
 * writes are hidden rather than merely doomed.
 */
export function useIsReadOnly(): boolean {
  return useViewAs().userId !== null
}

