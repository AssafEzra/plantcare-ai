/* The version block's decision table, which is the part that can be silently wrong.
 *
 * Every row below is one of the eight states the block was designed against. Two
 * pairs of them are the reason this file exists at all, because each pair is the
 * *same* inequality with opposite meanings:
 *
 *   - "the local API is stale" and "the local bundle is stale" both mean a commit
 *     differs from another commit. Only the tree's live HEAD separates them.
 *   - "this browser is behind" and "production was rolled back" are the same, on a
 *     host with no git to ask. Only the build times separate them.
 *
 * Get either backwards and the block confidently tells you to restart the wrong
 * thing - which is worse than having no block, because the whole point of it is to
 * be the thing you can trust when nothing else is.
 */

import { describe, expect, it } from 'vitest'
import { describeVersions } from './versionRows'
import type { BuildInfo, Versions } from '../api/admin'

const EARLIER = '2026-10-07T08:00:00.000Z'
const LATER = '2026-10-09T08:00:00.000Z'

function build(commit: string, builtAt: string | null = EARLIER): BuildInfo {
  return { commit, started_at: EARLIER, bundle_built_at: builtAt, revision: null }
}

function versions(overrides: Partial<Versions>): Versions {
  return {
    role: 'local',
    production: null,
    production_status: 'unconfigured',
    production_behind: null,
    production_ahead: null,
    server: null,
    head: null,
    ...overrides,
  }
}

/** The three rows, by the label the block renders. */
function rows(v: Versions, bundleCommit: string, bundleTime = EARLIER) {
  const [production, server, browser] = describeVersions(v, bundleCommit, bundleTime)
  return { production, server, browser }
}

describe('served from production', () => {
  const onProduction = (bundle: string, builtAt: string | null = EARLIER) =>
    rows(
      versions({ role: 'production', production: build('cd0f30d', builtAt), production_status: 'self' }),
      bundle,
      builtAt === null ? EARLIER : builtAt,
    )

  it('says everything is current when the browser matches', () => {
    const { production, server, browser } = onProduction('cd0f30d')

    expect(production.tone).toBe('ok')
    expect(browser.tone).toBe('ok')
    expect(browser.refresh).toBe(false)
    // There is no second server to report when you are looking at production.
    expect(server.note).toBe('לא רלוונטי')
    expect(server.tone).toBe('muted')
  })

  it('calls an older bundle stale and offers a refresh', () => {
    const v = versions({
      role: 'production',
      production: build('cd0f30d', LATER),
      production_status: 'self',
    })

    const { browser, production } = rows(v, 'bf23bfe', EARLIER)

    expect(browser.note).toBe('מיושן')
    expect(browser.refresh).toBe(true)
    // Suppressed while another row is warning: which process needs attention is
    // the useful fact, not how production compares.
    expect(production.note).toBe('')
  })

  it('calls a newer bundle a mismatch rather than stale', () => {
    /* The deployment went backwards - a revision rolled back under a browser
       holding the newer bundle. Saying "your browser is out of date" there would
       send someone to refresh a page that is already ahead. */
    const v = versions({
      role: 'production',
      production: build('bf23bfe', EARLIER),
      production_status: 'self',
    })

    const { browser } = rows(v, 'cd0f30d', LATER)

    expect(browser.note).toBe('לא תואם')
    expect(browser.refresh).toBe(true)
  })

  it('will not guess which is older when the build time is missing', () => {
    const v = versions({
      role: 'production',
      production: build('bf23bfe', null),
      production_status: 'self',
    })

    const { browser } = rows(v, 'cd0f30d')

    expect(browser.note).toBe('לא תואם')
  })
})

describe('served from localhost', () => {
  const local = (overrides: Partial<Versions>) =>
    versions({ production: build('cd0f30d'), production_status: 'ok', ...overrides })

  it('reports a healthy machine, with production behind it', () => {
    const v = local({ server: build('93a7853'), head: '93a7853', production_behind: 1 })

    const { production, server, browser } = rows(v, '93a7853')

    expect(server.note).toBe('תקין')
    expect(browser.note).toBe('תקין')
    expect(production.note).toBe('1 מאחור')
    expect(production.refresh).toBe(false)
  })

  it('names the API process when it is the stale one', () => {
    /* The case a commit comparison alone cannot reach: the server started before
       the last commit while the bundle did not. */
    const v = local({ server: build('cd0f30d'), head: '93a7853' })

    const { server, browser } = rows(v, '93a7853')

    expect(server.tone).toBe('fail')
    expect(server.note).toContain('הפעלה מחדש')
    // No button: a page cannot restart the process that served it.
    expect(server.refresh).toBe(false)
    expect(browser.note).toBe('תקין')
  })

  it('names the bundle when that is the stale one instead', () => {
    const v = local({ server: build('93a7853'), head: '93a7853' })

    const { server, browser } = rows(v, 'cd0f30d')

    expect(server.note).toBe('תקין')
    expect(browser.tone).toBe('fail')
    expect(browser.refresh).toBe(true)
  })

  it('reports both when both are behind', () => {
    const v = local({ server: build('cd0f30d'), head: '93a7853' })

    const { server, browser } = rows(v, 'cd0f30d')

    expect(server.tone).toBe('fail')
    expect(browser.tone).toBe('fail')
  })

  it('warns when production is ahead of this tree', () => {
    /* Deployed, then reset or force-pushed. It matters more than being behind and
       would read as zero if the comparison used two dots instead of three. */
    const v = local({ server: build('93a7853'), head: '93a7853', production_ahead: 2 })

    const { production } = rows(v, '93a7853')

    expect(production.note).toBe('2 לפני')
    expect(production.tone).toBe('warn')
  })

  it('leaves the production line blank when it cannot be reached', () => {
    const v = local({ production: null, production_status: 'unreachable', server: build('93a7853'), head: '93a7853' })

    const { production, server, browser } = rows(v, '93a7853')

    expect(production.note).toBe('לא זמין')
    expect(production.commit).toBeNull()
    expect(production.refresh).toBe(false)
    // The two local answers still arrive, which is the point of degrading.
    expect(server.note).toBe('תקין')
    expect(browser.note).toBe('תקין')
  })

  it('tells "not set up" apart from "did not answer"', () => {
    const v = versions({ server: build('93a7853'), head: '93a7853' })

    expect(rows(v, '93a7853').production.note).toBe('לא מוגדר')
  })
})

describe('when a commit cannot be established', () => {
  it('passes no verdict on an unknown bundle', () => {
    /* Every comparison against `unknown` is vacuous, and a deployed image built
       before the commit was baked in reports exactly that. Claiming "mismatch"
       there would send someone chasing a difference that was never measured. */
    const v = versions({
      role: 'production',
      production: build('cd0f30d'),
      production_status: 'self',
    })

    const { browser } = rows(v, 'unknown')

    expect(browser.note).toBe('לא ידוע')
    expect(browser.refresh).toBe(false)
  })

  it('passes no verdict on an unknown server', () => {
    const v = versions({ server: build('unknown'), head: '93a7853' })

    const { server } = rows(v, '93a7853')

    expect(server.note).toBe('לא ידוע')
    expect(server.tone).toBe('muted')
  })
})

describe('invariants', () => {
  const everyState: Versions[] = [
    versions({ role: 'production', production: build('cd0f30d'), production_status: 'self' }),
    versions({ server: build('93a7853'), head: '93a7853' }),
    versions({ server: build('cd0f30d'), head: '93a7853', production_status: 'unreachable' }),
    versions({
      server: build('93a7853'),
      head: '93a7853',
      production: build('cd0f30d'),
      production_status: 'ok',
      production_behind: 3,
    }),
  ]

  it('never offers to refresh someone else’s server', () => {
    for (const v of everyState) {
      expect(describeVersions(v, '93a7853', EARLIER)[0].refresh).toBe(false)
    }
  })

  it('offers a refresh only on the browser line', () => {
    for (const v of everyState) {
      const [, server, browser] = describeVersions(v, 'something-else', EARLIER)
      expect(server.refresh).toBe(false)
      expect([true, false]).toContain(browser.refresh)
    }
  })

  it('always returns the three lines in a fixed order', () => {
    for (const v of everyState) {
      expect(describeVersions(v, '93a7853', EARLIER).map((row) => row.label)).toEqual([
        'ייצור',
        'שרת מקומי',
        'דפדפן',
      ])
    }
  })
})
