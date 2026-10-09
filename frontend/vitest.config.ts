/* Tests for the logic that does not need a browser.
 *
 * Its own file rather than a `test` block in `vite.config.ts`, because that config
 * carries the PWA plugin and a `define` that shells out to git on every load - both
 * pointless here, and the git call would run once per test file.
 *
 * Deliberately narrow. This runs pure functions: decision tables, comparators, date
 * helpers. It does not render components and does not pretend to be a browser, so
 * it needs no jsdom and stays fast enough to run on every change.
 *
 * It is not a substitute for looking at the page. Nothing here would have caught
 * any of the three bugs in the plant drag - a pointer capture that threw, a hit
 * test that returned the dragged card, an optimistic update that left the sort key
 * stale. Those needed a real browser. What this covers is the part where a wrong
 * answer is silent: which of three versions is stale, which plant sorts first.
 */

import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
    /* The constants `vite.config.ts` injects at build time. Declared here too, or
       anything importing `lib/appUpdate` fails to resolve them under test. */
    define: {
      __APP_COMMIT__: JSON.stringify('testcommit'),
      __APP_BUILT_AT__: JSON.stringify('2026-01-01T00:00:00.000Z'),
    },
  },
})
