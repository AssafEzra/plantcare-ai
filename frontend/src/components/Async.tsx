/* Loading, error, empty — in one place.
 *
 * Section 42 requires every asynchronous flow to define loading, success, error,
 * empty and retry, and says a screen must never be left "stuck" without feedback.
 * Doing that per screen guarantees it will be forgotten somewhere, so screens wrap
 * their content in this instead and supply only the empty state, which is the part
 * that genuinely differs.
 */

import type { ReactNode } from 'react'
import { ApiError, GENERIC } from '../lib/errors'
import './Async.css'

type QueryLike = {
  isPending: boolean
  error: unknown
  refetch: () => void
  isFetching: boolean
}

export default function Async({
  query,
  empty,
  emptyState,
  children,
  loadingLabel = 'טוען…',
}: {
  query: QueryLike
  /** The caller decides what "no rows" means; only it knows the shape. */
  empty?: boolean
  emptyState?: ReactNode
  children: ReactNode
  loadingLabel?: string
}) {
  if (query.isPending) {
    return (
      <div className="pc-async" role="status" aria-live="polite">
        <span className="pc-spinner" aria-hidden="true" />
        <span>{loadingLabel}</span>
      </div>
    )
  }

  if (query.error) {
    const message = query.error instanceof ApiError ? query.error.message : GENERIC
    return (
      <div className="pc-async">
        <p className="pc-formerror" role="alert">
          {message}
        </p>
        <button
          type="button"
          className="pc-btn"
          onClick={() => query.refetch()}
          disabled={query.isFetching}
        >
          {query.isFetching ? 'מנסה שוב…' : 'נסו שוב'}
        </button>
      </div>
    )
  }

  if (empty) {
    return <div className="pc-async pc-asyncempty">{emptyState ?? <p>אין מה להציג.</p>}</div>
  }

  return <>{children}</>
}
