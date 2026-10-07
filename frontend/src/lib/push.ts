/* What this device can do about push, and the browser calls to register it.
 *
 * Push is offered on phones and tablets only (a product decision: reminders are
 * for the device that is in your hand at home, and desktop push waits for the
 * browser to be open). Tablets count as phones.
 *
 * iPhone and iPad allow push only in the app installed to the home screen
 * (iOS 16.4+). In a Safari tab `PushManager` is missing, so the page shows the
 * "Share → Add to Home Screen" steps instead of a button that cannot work.
 */

export type Platform = 'ios' | 'android' | 'other'

export function isIOS(): boolean {
  const ua = navigator.userAgent
  // iPadOS 13+ reports itself as a Mac; touch support gives it away.
  return /iPad|iPhone|iPod/.test(ua) || (ua.includes('Macintosh') && navigator.maxTouchPoints > 1)
}

export function isAndroid(): boolean {
  return /Android/i.test(navigator.userAgent)
}

/** A phone or a tablet: touch-first, with a coarse pointer, or a mobile OS. */
export function isPhoneOrTablet(): boolean {
  if (isIOS() || isAndroid()) return true
  const coarse = window.matchMedia?.('(pointer: coarse)').matches ?? false
  return coarse && navigator.maxTouchPoints > 0
}

/** Opened from the home-screen icon rather than a browser tab. */
export function isStandalone(): boolean {
  const legacy = (navigator as Navigator & { standalone?: boolean }).standalone === true
  return legacy || (window.matchMedia?.('(display-mode: standalone)').matches ?? false)
}

export function pushSupported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

export function platform(): Platform {
  if (isIOS()) return 'ios'
  if (isAndroid()) return 'android'
  return 'other'
}

/** "iPhone · Safari", "Android · Chrome" - so a list of devices is readable. */
export function deviceLabel(): string {
  const ua = navigator.userAgent
  const device = /iPad/.test(ua)
    ? 'iPad'
    : isIOS()
      ? 'iPhone'
      : isAndroid()
        ? /Mobile/.test(ua)
          ? 'Android'
          : 'טאבלט Android'
        : 'מכשיר'
  const browser = /SamsungBrowser/.test(ua)
    ? 'Samsung Internet'
    : /Firefox|FxiOS/.test(ua)
      ? 'Firefox'
      : /EdgA|EdgiOS/.test(ua)
        ? 'Edge'
        : /CriOS|Chrome/.test(ua)
          ? 'Chrome'
          : 'Safari'
  return `${device} · ${browser}`
}

/** The VAPID public key, base64url, as the bytes `subscribe()` wants. */
function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = (base64url + '='.repeat((4 - (base64url.length % 4)) % 4))
    .replace(/-/g, '+')
    .replace(/_/g, '/')
  const raw = atob(padded)
  const bytes = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i)
  return bytes
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null

  /* `getRegistration`, not `ready`. `navigator.serviceWorker.ready` resolves only
     once a worker is active and otherwise waits for ever - it has no rejection and
     no timeout. The dev server registers none (`devOptions.enabled: false` in
     vite.config.ts), so on localhost this call never settled, and because sign-out
     forgets the device before it does anything else, pressing "יציאה" hung there
     silently and left the user signed in. `getRegistration` resolves with
     `undefined` when there is nothing, which is an answer rather than a wait. */
  const registration = await navigator.serviceWorker.getRegistration()
  if (!registration) return null
  return registration.pushManager.getSubscription()
}

/**
 * Ask for permission and subscribe. Must be called from a tap: browsers refuse a
 * permission prompt that no user gesture started, and a "Don't allow" cannot be
 * asked again from the page.
 */
export async function subscribe(publicKey: string): Promise<PushSubscription> {
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') throw new Error(permission)

  const registration = await navigator.serviceWorker.ready
  const existing = await registration.pushManager.getSubscription()
  if (existing) return existing
  return registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: keyBytes(publicKey),
  })
}

/** The body `POST /v1/push/subscriptions` takes. */
export function subscriptionBody(subscription: PushSubscription) {
  return {
    ...subscription.toJSON(),
    device_label: deviceLabel(),
    platform: platform(),
  }
}
