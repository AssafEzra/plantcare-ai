/* The auth context and its hook, separate from the provider component.
 *
 * Split out because a module exporting both a component and a non-component breaks
 * React Fast Refresh — editing the provider would do a full reload instead of
 * preserving state, which is exactly the kind of small friction that accumulates.
 */

import { createContext, useContext } from 'react'
import type { Session } from '@supabase/supabase-js'

export type AuthContextValue = {
  session: Session | null
  userId: string | null
  email: string | null
  /** True until the first session check resolves; routes must not redirect before. */
  loading: boolean
  signIn: (email: string, password: string) => Promise<void>
  /** Resolves true when email confirmation is required and no session was created. */
  signUp: (email: string, password: string, displayName?: string) => Promise<boolean>
  sendPasswordReset: (email: string) => Promise<void>
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
