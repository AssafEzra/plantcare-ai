/* Push notifications, imported into the generated service worker
 * (vite.config.ts → workbox.importScripts).
 *
 * The server sends a small JSON payload (app/notifications/selection.py):
 *   { kind: 'today' | 'late', title, body, url, tag }
 * `kind` picks the coloured icon - green for today's work, red for late - because
 * the phone draws the notification and its text cannot be coloured. iPhone shows
 * the app icon regardless, which is why the title also starts with 🟢 or 🔴.
 *
 * `tag` makes a re-sent notification replace the earlier one instead of stacking.
 */

self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch {
    data = { title: 'PlantCare', body: event.data ? event.data.text() : '' }
  }

  const icon = data.kind === 'late' ? '/notify-late.png' : '/notify-today.png'

  // iPhone requires every push to show a notification; there is no silent path.
  event.waitUntil(
    self.registration.showNotification(data.title || 'PlantCare', {
      body: data.body || '',
      tag: data.tag || data.kind || 'plantcare',
      icon,
      badge: '/notify-badge.png',
      lang: 'he',
      dir: 'rtl',
      data: { url: data.url || '/tasks' },
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = new URL(event.notification.data?.url || '/tasks', self.location.origin).href

  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      for (const client of windows) {
        if (new URL(client.url).origin === self.location.origin) {
          await client.focus()
          if ('navigate' in client) await client.navigate(target)
          return
        }
      }
      await self.clients.openWindow(target)
    })(),
  )
})
