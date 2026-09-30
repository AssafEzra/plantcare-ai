/* The only route to application data.
 *
 * Mirrors app/ui/state/api_client.py: attach the bearer token and the act-as header
 * in one place so no caller can forget either, unwrap the API_CONTRACTS envelope,
 * and translate errors into Hebrew before they reach a screen.
 */

import { supabase } from './supabase'
import { actingAs } from './viewAs'
import { ApiError, OFFLINE, GENERIC, translate } from './errors'

/* Empty in development: vite.config.ts proxies /v1 to the API, so the browser sees
   one origin. Production sets this once a host exists — see docs/MIGRATION_AUDIT.md
   section 5. */
const BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export const ACT_AS_HEADER = 'X-Act-As-User'

async function headers(extra: HeadersInit = {}): Promise<Headers> {
  const h = new Headers({ Accept: 'application/json', ...extra })

  // getSession() refreshes an expired token before returning it, so a long-idle tab
  // recovers on its own rather than bouncing the user to sign-in.
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  if (token) h.set('Authorization', `Bearer ${token}`)

  const target = actingAs()
  if (target) h.set(ACT_AS_HEADER, target)

  return h
}

type RequestOptions = {
  params?: Record<string, string | number | boolean | undefined | null>
  json?: unknown
  body?: FormData
  signal?: AbortSignal
}

export async function request<T = unknown>(
  method: string,
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const url = new URL(`${BASE}${path}`, window.location.origin)
  for (const [key, value] of Object.entries(opts.params ?? {})) {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value))
  }

  const init: RequestInit = { method, signal: opts.signal }

  if (opts.body) {
    // FormData sets its own multipart boundary; setting Content-Type breaks it.
    init.body = opts.body
    init.headers = await headers()
  } else if (opts.json !== undefined) {
    init.body = JSON.stringify(opts.json)
    init.headers = await headers({ 'Content-Type': 'application/json' })
  } else {
    init.headers = await headers()
  }

  let response: Response
  try {
    response = await fetch(url, init)
  } catch (cause) {
    // A transport failure is not the API's error envelope, so it needs its own
    // message: "the server is unreachable" is actionable, "something went wrong"
    // is not. An aborted request is the caller's doing and is rethrown as-is.
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
    throw new ApiError('NETWORK_ERROR', OFFLINE)
  }

  if (!response.ok) {
    let payload: unknown
    try {
      payload = await response.json()
    } catch {
      throw new ApiError('INTERNAL_ERROR', GENERIC, { status: response.status })
    }
    throw translate(payload, response.status)
  }

  if (response.status === 204) return undefined as T
  const text = await response.text()
  if (!text) return undefined as T

  // Every successful response is a DataEnvelope; screens want its `data`.
  return (JSON.parse(text) as { data: T }).data
}

export const api = {
  get: <T = unknown>(path: string, opts?: RequestOptions) => request<T>('GET', path, opts),
  post: <T = unknown>(path: string, opts?: RequestOptions) => request<T>('POST', path, opts),
  patch: <T = unknown>(path: string, opts?: RequestOptions) => request<T>('PATCH', path, opts),
  put: <T = unknown>(path: string, opts?: RequestOptions) => request<T>('PUT', path, opts),
  delete: <T = unknown>(path: string, opts?: RequestOptions) => request<T>('DELETE', path, opts),
}
