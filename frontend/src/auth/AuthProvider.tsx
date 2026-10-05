/* Authentication state.
 *
 * Mirrors app/ui/state/session.py, which the audit identified as the whole of the
 * current auth implementation — there is no auth endpoint on the API. The semantics
 * carried over deliberately:
 *
 *   - sign-up normally yields NO session, because email confirmation is on
 *     (FINAL section 22). The caller must tell the user to check their inbox rather
 *     than assume they are signed in. `signUp` returns true in that case.
 *   - a failed remote sign-out must not strand the user in a signed-in UI, so local
 *     state is cleared regardless.
 *
 * What is NOT carried over is session_store.py, the custom Streamlit component built
 * to survive a page refresh. The browser does that natively.
 */

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'
import { useQueryClient } from '@tanstack/react-query'
import { supabase } from '../lib/supabase'
import { leaveViewAs } from '../lib/viewAs'
import { forgetThisDevice } from '../api/push'
import { AuthContext, type AuthContextValue } from './context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const queryClient = useQueryClient()

  useEffect(() => {
    let active = true

    supabase.auth.getSession().then(({ data }) => {
      if (!active) return
      setSession(data.session)
      setLoading(false)
    })

    const { data: sub } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(next)
      setLoading(false)
    })

    return () => {
      active = false
      sub.subscription.unsubscribe()
    }
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    if (error) throw error
  }, [])

  const signUp = useCallback(
    async (email: string, password: string, displayName?: string) => {
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: displayName ? { data: { display_name: displayName } } : undefined,
      })
      if (error) throw error
      return data.session === null
    },
    [],
  )

  const sendPasswordReset = useCallback(async (email: string) => {
    const { error } = await supabase.auth.resetPasswordForEmail(email)
    if (error) throw error
  }, [])

  const signOut = useCallback(async () => {
    try {
      // Before the session goes: the request needs it. A shared phone must stop
      // receiving this account's reminders the moment the account leaves.
      await forgetThisDevice()
    } catch {
      /* Offline or never subscribed; the next owner's registration frees it. */
    }
    try {
      await supabase.auth.signOut()
    } catch {
      /* Clearing local state is what actually matters. */
    }
    leaveViewAs()
    // Every cached read belongs to the account that just left.
    queryClient.clear()
    setSession(null)
  }, [queryClient])

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      userId: session?.user.id ?? null,
      email: session?.user.email ?? null,
      loading,
      signIn,
      signUp,
      sendPasswordReset,
      signOut,
    }),
    [session, loading, signIn, signUp, sendPasswordReset, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
