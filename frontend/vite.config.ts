import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// The API is a separate service (DEPLOYMENT section 3). In development it runs on
// loopback:8000 and the dev server proxies `/v1` to it, so the browser sees one
// origin and no CORS configuration is needed for local work. Production hosting is
// an open decision — see docs/MIGRATION_AUDIT.md section 5 — so the base URL is read
// from an env var rather than hard-coded here.
const API_TARGET = process.env.VITE_DEV_API_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'prompt',
      // `prompt`, not `autoUpdate`: a care task the user just marked done must not be
      // wiped by a service worker reloading the page underneath them. Section 41 asks
      // for installability, not aggressive caching.
      includeAssets: [
        'favicon.svg',
        'apple-touch-icon.png',
        'notify-today.png',
        'notify-late.png',
        'notify-badge.png',
      ],
      manifest: {
        name: 'PlantCare AI',
        short_name: 'PlantCare',
        description: 'טיפול בצמחי בית בעזרת בינה מלאכותית',
        lang: 'he',
        dir: 'rtl',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        orientation: 'portrait',
        background_color: '#F7F5EF',
        theme_color: '#2F6B4F',
        icons: [
          { src: 'pwa-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512.png', sizes: '512x512', type: 'image/png' },
          {
            src: 'pwa-512-maskable.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        // Shell only. Section 41 forbids offline business logic without approval, so
        // no API response is cached and no write is queued — a request made offline
        // fails and the UI says so, which is honest.
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        navigateFallbackDenylist: [/^\/v1\//],
        // Push and notification-click handlers live in public/push-sw.js. Imported
        // rather than switching to injectManifest, so the generated caching stays as
        // it is and the push code is one plain file.
        importScripts: ['push-sw.js'],
      },
      devOptions: { enabled: false },
    }),
  ],
  server: {
    port: 5173,
    // A tunnel arrives carrying its own Host header, which Vite rejects by default as
    // a DNS-rebinding guard. The suffix is admitted so a phone can reach this server
    // over https: `getUserMedia` and the service worker both demand a secure context,
    // and a LAN address (http://192.168.x.x) is not one.
    allowedHosts: ['.trycloudflare.com'],
    proxy: {
      '/v1': { target: API_TARGET, changeOrigin: true },
    },
  },
  // In development Vite injects every stylesheet as a <style> block through JavaScript,
  // so it can hot-reload them. The cost is that DevTools sees 24 anonymous blocks and
  // one real file, cannot name the source of any rule, and has nothing on disk to save
  // an edit back into — which makes styling by hand in the browser a dead end.
  //
  // Source maps restore the link: the Styles pane then reads "tokens.css:21" and, with
  // the folder added under Sources → Workspace, an edit made in the browser is written
  // to the actual file. Development only; the production build is untouched.
  css: { devSourcemap: true },
  // `npm run preview` serves the built bundle, and it is the only way to exercise the
  // service worker at all — `devOptions.enabled` is false above, so the dev server
  // registers none and installability cannot be judged there. Both settings are
  // repeated rather than shared: `preview` inherits nothing from `server`.
  preview: {
    port: 4173,
    allowedHosts: ['.trycloudflare.com'],
    proxy: {
      '/v1': { target: API_TARGET, changeOrigin: true },
    },
  },
})
