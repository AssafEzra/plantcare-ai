/* Sign in, register, forgot password.
 *
 * The three flows that exist today (app/ui/app_pages/auth.py). Google login is NOT
 * here: the audit found no OAuth anywhere in the system, so adding it would be a new
 * feature rather than a migration — ruled out of scope.
 *
 * Phase 3 builds this because the auth integration cannot be verified without a way
 * to sign in. Phase 5 revisits the presentation.
 */

import { useState, type FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/context'
import './Auth.css'

type Tab = 'signin' | 'register' | 'reset'

/* Supabase returns English strings. The rest of the interface is Hebrew, so the
   handful a user can actually provoke are translated; anything else degrades to a
   general sentence rather than leaking English into the UI. */
function hebrew(message: string): string {
  const m = message.toLowerCase()
  if (m.includes('invalid login credentials')) return 'אימייל או סיסמה שגויים.'
  if (m.includes('email not confirmed')) return 'יש לאשר את כתובת האימייל לפני הכניסה.'
  if (m.includes('already registered')) return 'כתובת האימייל כבר רשומה.'
  if (m.includes('password should be')) return 'הסיסמה קצרה מדי (לפחות 8 תווים).'
  if (m.includes('rate limit') || m.includes('too many')) return 'יותר מדי ניסיונות. נסו שוב בעוד רגע.'
  if (m.includes('unable to validate email')) return 'כתובת האימייל אינה תקינה.'
  return 'משהו השתבש. אפשר לנסות שוב.'
}

export default function Auth() {
  const { session, loading, signIn, signUp, sendPasswordReset } = useAuth()
  const location = useLocation() as { state?: { from?: string } }
  const [tab, setTab] = useState<Tab>('signin')

  if (!loading && session) {
    return <Navigate to={location.state?.from ?? '/'} replace />
  }

  return (
    <div className="pc-authpage">
      <main className="pc-authcard">
        <div className="pc-authbrand">
          <img src="/favicon.svg" alt="" width="40" height="40" />
          <h1>PlantCare AI</h1>
        </div>

        <div className="pc-tabs" role="tablist">
          {(
            [
              ['signin', 'כניסה'],
              ['register', 'הרשמה'],
              ['reset', 'שכחתי סיסמה'],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              role="tab"
              type="button"
              aria-selected={tab === id}
              className={`pc-tabbtn${tab === id ? ' active' : ''}`}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === 'signin' && <SignInForm onSubmit={signIn} />}
        {tab === 'register' && <RegisterForm onSubmit={signUp} />}
        {tab === 'reset' && <ResetForm onSubmit={sendPasswordReset} />}
      </main>
    </div>
  )
}

function useSubmit<A extends unknown[]>(fn: (...args: A) => Promise<unknown>) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  async function run(event: FormEvent, args: A, onDone?: (result: unknown) => void) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const result = await fn(...args)
      onDone?.(result)
    } catch (cause) {
      setError(hebrew(cause instanceof Error ? cause.message : ''))
    } finally {
      setBusy(false)
    }
  }

  return { busy, error, notice, setNotice, run }
}

function Feedback({ error, notice }: { error: string | null; notice: string | null }) {
  if (error) {
    return (
      <p className="pc-formerror" role="alert">
        {error}
      </p>
    )
  }
  if (notice) {
    return (
      <p className="pc-formnotice" role="status">
        {notice}
      </p>
    )
  }
  return null
}

function SignInForm({ onSubmit }: { onSubmit: (e: string, p: string) => Promise<void> }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const { busy, error, notice, run } = useSubmit(onSubmit)

  return (
    <form onSubmit={(e) => run(e, [email.trim(), password])}>
      <label className="pc-field">
        <span>אימייל</span>
        <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label className="pc-field">
        <span>סיסמה</span>
        <input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
      <Feedback error={error} notice={notice} />
      <button type="submit" className="pc-btn pc-btn-block" disabled={busy}>
        {busy ? 'מתחבר…' : 'כניסה'}
      </button>
    </form>
  )
}

function RegisterForm({
  onSubmit,
}: {
  onSubmit: (e: string, p: string, n?: string) => Promise<boolean>
}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const { busy, error, notice, setNotice, run } = useSubmit(onSubmit)

  return (
    <form
      onSubmit={(e) =>
        run(e, [email.trim(), password, name.trim() || undefined], (needsConfirmation) => {
          if (needsConfirmation) {
            setNotice('נשלח אליכם אימייל לאישור הכתובת. יש לאשר אותו לפני הכניסה.')
          }
        })
      }
    >
      <label className="pc-field">
        <span>שם (אופציונלי)</span>
        <input type="text" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="pc-field">
        <span>אימייל</span>
        <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label className="pc-field">
        <span>סיסמה</span>
        <input type="password" required minLength={8} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <small>לפחות 8 תווים</small>
      </label>
      <Feedback error={error} notice={notice} />
      <button type="submit" className="pc-btn pc-btn-block" disabled={busy}>
        {busy ? 'נרשם…' : 'הרשמה'}
      </button>
    </form>
  )
}

function ResetForm({ onSubmit }: { onSubmit: (e: string) => Promise<void> }) {
  const [email, setEmail] = useState('')
  const { busy, error, notice, setNotice, run } = useSubmit(onSubmit)

  return (
    <form
      onSubmit={(e) =>
        run(e, [email.trim()], () =>
          // Deliberately unconditional: saying whether the address exists would
          // let anyone test which emails have accounts.
          setNotice('אם הכתובת רשומה אצלנו, ישלח אליה קישור לאיפוס הסיסמה.'),
        )
      }
    >
      <label className="pc-field">
        <span>אימייל</span>
        <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <Feedback error={error} notice={notice} />
      <button type="submit" className="pc-btn pc-btn-block" disabled={busy}>
        {busy ? 'שולח…' : 'שליחת קישור לאיפוס'}
      </button>
    </form>
  )
}
