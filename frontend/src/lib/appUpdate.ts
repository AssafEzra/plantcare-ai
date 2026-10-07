/* The service worker update, in one place.
 *
 * Two things ask about updates: `UpdatePrompt`, which offers one when the worker
 * finds it on its own, and the version card in Settings, which asks on demand.
 * Both need the same registration and the same way to activate a waiting worker,
 * and registering twice would produce two workers racing to control the page.
 *
 * `registerType: 'prompt'` is the setting all of this exists to honour: a worker
 * that activates by itself can reload the page under someone mid-action. Nothing
 * here activates anything until `applyUpdate` is called, and only a user gesture
 * calls it.
 */

import { registerSW } from 'virtual:pwa-register'

type Listener = () => void

const listeners = new Set<Listener>()
let waiting = false

/* The function `registerSW` hands back: calling it with `true` tells the waiting
   worker to take over and reloads the page. Captured once, at module load, which
   is also when the worker is registered. */
const updateSW = registerSW({
  onNeedRefresh() {
    waiting = true
    for (const notify of listeners) notify()
  },
})

/** Is a new version installed and waiting to be activated? */
export function updateWaiting(): boolean {
  return waiting
}

/** Subscribe to that changing. Returns the unsubscribe. */
export function onUpdateWaiting(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/**
 * Ask the push service whether a newer worker exists, and wait for the answer.
 *
 * `registration.update()` resolves when the check completes, but `onNeedRefresh`
 * fires from the worker's own state change, which can land a moment later - so a
 * caller that reads the flag immediately would be told "up to date" about an
 * update it just found. The short settle below is what makes "I checked and there
 * is nothing" an honest answer rather than a race.
 *
 * Returns whether an update is now waiting. `false` also covers "no worker is
 * registered at all", which is the dev server's normal state.
 */
export async function checkForUpdate(): Promise<boolean> {
  if (!('serviceWorker' in navigator)) return false

  const registration = await navigator.serviceWorker.getRegistration()
  if (!registration) return false

  await registration.update()
  await new Promise((resolve) => setTimeout(resolve, 600))

  // Read the registration as well as the flag: `onNeedRefresh` is the normal
  // signal, but a worker already sitting in `waiting` from an earlier visit never
  // fires it again, and that is precisely the stuck state worth reporting.
  if (registration.waiting) waiting = true
  return waiting
}

/** Activate the waiting worker and reload. Only ever from a user gesture. */
export async function applyUpdate(): Promise<void> {
  await updateSW(true)
}

/** Can this browser check at all? False on the dev server, which registers none. */
export function updatesSupported(): boolean {
  return 'serviceWorker' in navigator
}

export const BUILD_COMMIT = __APP_COMMIT__
export const BUILD_TIME = __APP_BUILT_AT__
