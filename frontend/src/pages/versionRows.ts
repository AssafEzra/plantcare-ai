/* Which of the three versions is behind, and what to say about it.
 *
 * Kept out of the component and free of React on purpose. This is a decision table
 * with eight states, two of which differ only in which side of an inequality is
 * older, and it is much easier to be sure it is right when it reads as one function
 * than when it is spread through JSX.
 *
 * The thing to understand before changing it: two different commits tell you only
 * that they differ, never which is older. So the comparison never uses the two
 * commits alone.
 *
 *  - On a development machine the server reports `head`, the tree's commit right
 *    now. A process whose own commit is not `head` started before the last commit;
 *    a bundle whose commit is not `head` was built before it. Each is then an
 *    equality test, and the two cases stop looking alike.
 *  - On production there is no git in the image, so `head` is null. There, build
 *    *times* are compared instead: the bundle carries the moment it was built, and
 *    the server reports the mtime of the index.html it is serving, which is that
 *    same moment. A browser holding an older bundle is behind; a browser holding a
 *    newer one means the deployment was rolled back under it.
 *
 * Where neither is available the row says the two differ and stops. It never
 * guesses which is older - a confident wrong answer here is worse than no answer,
 * because the whole point is to be the thing you can trust when nothing else is.
 */

import type { Versions } from '../api/admin'

export type Tone = 'ok' | 'warn' | 'fail' | 'muted'

export type VersionRow = {
  label: string
  /** The commit to print, or null where there is nothing to print. */
  commit: string | null
  /** A short Hebrew note, or '' for no note. */
  note: string
  tone: Tone
  /** Whether this row offers the refresh button. Only ever the browser row. */
  refresh: boolean
}

const UNKNOWN = 'unknown'

/** Is this a commit we can compare at all? */
function known(commit: string | null | undefined): boolean {
  return Boolean(commit) && commit !== UNKNOWN
}

function olderThan(a: string | null, b: string | null): boolean | null {
  if (!a || !b) return null
  const left = Date.parse(a)
  const right = Date.parse(b)
  if (Number.isNaN(left) || Number.isNaN(right)) return null
  if (left === right) return null
  return left < right
}

function serverRow(versions: Versions): VersionRow {
  if (versions.role === 'production') {
    /* There is no second server when you are looking at production. Said plainly
       rather than left blank, so the row is not read as a failed lookup. */
    return { label: 'שרת מקומי', commit: null, note: 'לא רלוונטי', tone: 'muted', refresh: false }
  }

  const server = versions.server
  if (!server) return { label: 'שרת מקומי', commit: null, note: 'לא זמין', tone: 'muted', refresh: false }

  if (!known(server.commit)) {
    return { label: 'שרת מקומי', commit: server.commit, note: 'לא ידוע', tone: 'muted', refresh: false }
  }

  if (known(versions.head) && server.commit !== versions.head) {
    /* No button: a page cannot restart the process that served it. The note says
       what to do instead, because that is the whole value of knowing. */
    return {
      label: 'שרת מקומי',
      commit: server.commit,
      note: 'מיושן · נדרשת הפעלה מחדש',
      tone: 'fail',
      refresh: false,
    }
  }

  return { label: 'שרת מקומי', commit: server.commit, note: 'תקין', tone: 'ok', refresh: false }
}

function browserRow(versions: Versions, bundleCommit: string, bundleTime: string): VersionRow {
  const label = 'דפדפן'
  /* The server that served this page - which is production when you are on
     production, and the local API when you are not. */
  const serving = versions.server ?? versions.production

  if (!known(bundleCommit) || !serving || !known(serving.commit)) {
    return { label, commit: bundleCommit, note: 'לא ידוע', tone: 'muted', refresh: false }
  }

  if (versions.role === 'local' && known(versions.head)) {
    if (bundleCommit !== versions.head) {
      return { label, commit: bundleCommit, note: 'מיושן', tone: 'fail', refresh: true }
    }
    return { label, commit: bundleCommit, note: 'תקין', tone: 'ok', refresh: false }
  }

  if (bundleCommit === serving.commit) {
    return { label, commit: bundleCommit, note: 'תקין', tone: 'ok', refresh: false }
  }

  /* Commits differ and there is no git to order them, so compare build times. The
     bundle being older is the ordinary stale-browser case. The bundle being newer
     means the server went backwards - a rolled-back revision - and a refresh is
     still the right offer, because it fetches whatever is actually deployed. */
  const bundleIsOlder = olderThan(bundleTime, serving.bundle_built_at)
  return {
    label,
    commit: bundleCommit,
    note: bundleIsOlder === true ? 'מיושן' : 'לא תואם',
    tone: 'fail',
    refresh: true,
  }
}

function productionRow(versions: Versions, othersAreClean: boolean): VersionRow {
  const label = 'ייצור'
  /* Never a button on this row: you cannot refresh someone else's server. */
  switch (versions.production_status) {
    case 'unconfigured':
      return { label, commit: null, note: 'לא מוגדר', tone: 'muted', refresh: false }
    case 'unreachable':
      return { label, commit: null, note: 'לא זמין', tone: 'warn', refresh: false }
    case 'self': {
      const commit = versions.production?.commit ?? UNKNOWN
      return {
        label,
        commit,
        note: known(commit) && othersAreClean ? 'תקין' : '',
        tone: known(commit) ? 'ok' : 'muted',
        refresh: false,
      }
    }
    case 'ok': {
      const commit = versions.production?.commit ?? UNKNOWN
      const { production_behind: behind, production_ahead: ahead } = versions

      /* Suppressed while another row is warning: the useful fact then is which
         process needs attention, not how far production is from this tree. */
      if (!othersAreClean) return { label, commit, note: '', tone: 'muted', refresh: false }

      if (ahead && ahead > 0) {
        return { label, commit, note: `${ahead} לפני`, tone: 'warn', refresh: false }
      }
      if (behind && behind > 0) {
        return { label, commit, note: `${behind} מאחור`, tone: 'muted', refresh: false }
      }
      return { label, commit, note: 'תקין', tone: 'ok', refresh: false }
    }
  }
}

export function describeVersions(
  versions: Versions,
  bundleCommit: string,
  bundleTime: string,
): VersionRow[] {
  const server = serverRow(versions)
  const browser = browserRow(versions, bundleCommit, bundleTime)
  const clean = server.tone !== 'fail' && browser.tone !== 'fail'

  return [productionRow(versions, clean), server, browser]
}
