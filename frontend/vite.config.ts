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
      includeAssets: ['favicon.svg', 'apple-touch-icon.png'],
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
      },
      devOptions: { enabled: false },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/v1': { target: API_TARGET, changeOrigin: true },
    },
  },
})
