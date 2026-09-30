/* הגדרות — profile and reminders.
 *
 * Two forms answering two different questions, and the second one is the one people
 * get wrong. A care rule decides *when a task is due*; the preferred time here decides
 * *when we are allowed to write to you*. A user who waters in the evening still wants
 * to be told in the morning, so they are separate settings and the copy says so.
 *
 * Both forms send only what actually changed. `PATCH /v1/me` and
 * `PUT /v1/notification-preferences` both refuse an empty body, so a save with nothing
 * moved would be a 422 rather than a no-op — the screen says "nothing to save" instead.
 */

import { useState } from 'react'
import { useMe, useUpdateProfile } from '../api/profile'
import {
  DELIVERY_LABELS,
  useDeliveries,
  usePreferences,
  useUpdatePreferences,
  type NotificationDelivery,
} from '../api/notifications'
import { formatStamp } from '../lib/dates'
import { useIsReadOnly } from '../lib/viewAs'
import { ApiError } from '../lib/errors'
import Async from '../components/Async'
import './Settings.css'

export default function Settings() {
  const profile = useMe()
  const preferences = usePreferences()
  const readOnly = useIsReadOnly()

  return (
    <section className="pc-settings">
      <header className="pc-pagehead">
        <h1>הגדרות</h1>
      </header>

      {readOnly && (
        <p className="pc-placeholder-note">
          צפייה בהגדרות של משתמש אחר. אי אפשר לשנות אותן מכאן.
        </p>
      )}

      <Async query={profile} loadingLabel="טוען את הפרופיל…">
        {profile.data && <ProfileForm profile={profile.data} readOnly={readOnly} />}
      </Async>

      <div className="pc-sectionhead">
        <h2>תזכורות</h2>
      </div>

      <Async query={preferences} loadingLabel="טוען העדפות…">
        {preferences.data && (
          <RemindersForm preferences={preferences.data} readOnly={readOnly} />
        )}
      </Async>

      <Deliveries />
    </section>
  )
}

/* --- profile -------------------------------------------------------------- */

/**
 * Every IANA zone the browser knows, with the usual choices first.
 *
 * `Intl.supportedValuesOf` is the browser's own copy of the tz database, which is the
 * same list `zoneinfo` validates against server-side — so an option offered here is one
 * the API will accept. Where it is unavailable the preferred few are still offered
 * rather than nothing: a user who cannot change their timezone at all is worse off than
 * one who can only pick from five.
 */
const PREFERRED_ZONES = [
  'Asia/Jerusalem',
  'Europe/Berlin',
  'Europe/London',
  'America/New_York',
  'UTC',
]

function timezones(current: string): string[] {
  let all: string[] = []
  try {
    all = Intl.supportedValuesOf('timeZone')
  } catch {
    all = []
  }
  const rest = all.filter((zone) => !PREFERRED_ZONES.includes(zone))
  const options = [...PREFERRED_ZONES, ...rest]
  // The stored zone always appears, even if this browser has never heard of it —
  // otherwise the select would silently show someone else's value as theirs.
  return options.includes(current) ? options : [current, ...options]
}

function ProfileForm({
  profile,
  readOnly,
}: {
  profile: NonNullable<ReturnType<typeof useMe>['data']>
  readOnly: boolean
}) {
  const [name, setName] = useState(profile.display_name ?? '')
  const [timezone, setTimezone] = useState(profile.timezone)
  const [nothing, setNothing] = useState(false)
  const update = useUpdateProfile()

  const zones = timezones(profile.timezone)

  function submit() {
    setNothing(false)
    const changes: { display_name?: string | null; timezone?: string } = {}
    if (name.trim() !== (profile.display_name ?? '')) changes.display_name = name.trim() || null
    if (timezone !== profile.timezone) changes.timezone = timezone

    if (!Object.keys(changes).length) {
      setNothing(true)
      return
    }
    update.mutate(changes)
  }

  return (
    <form
      className="pc-card"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <h2>פרופיל</h2>

      <label className="pc-field">
        <span>שם</span>
        <input
          type="text"
          maxLength={120}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </label>

      <label className="pc-field">
        <span>אזור זמן</span>
        <select value={timezone} onChange={(event) => setTimezone(event.target.value)}>
          {zones.map((zone) => (
            <option key={zone} value={zone}>
              {zone}
            </option>
          ))}
        </select>
        <small>התזכורות והמשימות מחושבות לפי אזור הזמן הזה.</small>
      </label>

      {/* The address is not editable here: it is the account's identity, and changing
          it is an authentication flow rather than a profile edit. */}
      <p className="pc-placeholder-note">
        אימייל: <span className="pc-ltr">{profile.email}</span>
      </p>

      {update.error ? (
        <p className="pc-formerror" role="alert">
          {update.error instanceof ApiError ? update.error.message : 'ההגדרות לא נשמרו.'}
        </p>
      ) : null}
      {update.isSuccess && (
        <p className="pc-formnotice" role="status">
          ההגדרות נשמרו.
        </p>
      )}
      {nothing && <p className="pc-placeholder-note">אין שינויים לשמור.</p>}

      {!readOnly && (
        <button type="submit" className="pc-btn" disabled={update.isPending}>
          {update.isPending ? 'שומרים…' : 'שמירה'}
        </button>
      )}
    </form>
  )
}

/* --- reminders ------------------------------------------------------------ */

/** `HH:MM:SS` from Postgres; `<input type="time">` wants `HH:MM`. */
function clock(value: string): string {
  return (value || '08:00').slice(0, 5)
}

function RemindersForm({
  preferences,
  readOnly,
}: {
  preferences: NonNullable<ReturnType<typeof usePreferences>['data']>
  readOnly: boolean
}) {
  const [emailEnabled, setEmailEnabled] = useState(preferences.email_enabled)
  const [time, setTime] = useState(clock(preferences.preferred_time_local))
  const [digest, setDigest] = useState(preferences.daily_digest)
  const [nothing, setNothing] = useState(false)
  const update = useUpdatePreferences()

  function submit() {
    setNothing(false)
    const changes: Record<string, unknown> = {}
    if (emailEnabled !== preferences.email_enabled) changes.email_enabled = emailEnabled
    if (digest !== preferences.daily_digest) changes.daily_digest = digest
    if (time !== clock(preferences.preferred_time_local)) changes.preferred_time_local = time

    if (!Object.keys(changes).length) {
      setNothing(true)
      return
    }
    update.mutate(changes)
  }

  return (
    <form
      className="pc-card"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <label className="pc-toggle">
        <input
          type="checkbox"
          checked={emailEnabled}
          onChange={(event) => setEmailEnabled(event.target.checked)}
        />
        <span>תזכורות במייל</span>
      </label>

      <label className="pc-field">
        <span>שעה מועדפת</span>
        <input
          type="time"
          step={1800}
          value={time}
          onChange={(event) => setTime(event.target.value)}
        />
        {/* A10 made visible. The rule says when a task is due; this says when we are
            allowed to write. The two being confusable is exactly the ambiguity the
            specification left open. */}
        <small>השעה שבה נשלח לך את התזכורת. זמני הטיפול עצמם נקבעים בתוכנית הטיפול.</small>
      </label>

      <label className="pc-toggle">
        <input
          type="checkbox"
          checked={digest}
          onChange={(event) => setDigest(event.target.checked)}
        />
        <span>סיכום יומי</span>
      </label>
      <p className="pc-placeholder-note">הודעה אחת עם כל משימות היום, במקום הודעה לכל משימה.</p>

      {update.error ? (
        <p className="pc-formerror" role="alert">
          {update.error instanceof ApiError ? update.error.message : 'ההעדפות לא נשמרו.'}
        </p>
      ) : null}
      {update.isSuccess && (
        <p className="pc-formnotice" role="status">
          הגדרות התזכורות נשמרו.
        </p>
      )}
      {nothing && <p className="pc-placeholder-note">אין שינויים לשמור.</p>}

      {!readOnly && (
        <button type="submit" className="pc-btn" disabled={update.isPending}>
          {update.isPending ? 'שומרים…' : 'שמירת התזכורות'}
        </button>
      )}

      {!emailEnabled && (
        /* Said plainly rather than left to be inferred from a switch: a user who turned
           reminders off should know the work is still tracked in the app. */
        <p className="pc-placeholder-note">
          התזכורות במייל כבויות. המשימות עדיין מופיעות במסך הבית.
        </p>
      )}
    </form>
  )
}

/* --- what we actually sent ------------------------------------------------ */

function Deliveries() {
  const [open, setOpen] = useState(false)
  const query = useDeliveries(open)

  return (
    <details
      className="pc-reco pc-deliveries"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>התראות שנשלחו</summary>

      {open && (
        <Async
          query={query}
          loadingLabel="טוען…"
          empty={(query.data?.length ?? 0) === 0}
          emptyState={<p>עדיין לא נשלחו אליך התראות.</p>}
        >
          <ul className="pc-deliverylist">
            {query.data?.map((delivery) => (
              <Delivery key={delivery.id} delivery={delivery} />
            ))}
          </ul>
        </Async>
      )}
    </details>
  )
}

function Delivery({ delivery }: { delivery: NotificationDelivery }) {
  const when = delivery.sent_at ?? delivery.scheduled_at
  return (
    <li>
      <span className={`pc-deliverystatus is-${delivery.status.toLowerCase()}`}>
        {DELIVERY_LABELS[delivery.status] ?? delivery.status}
      </span>
      <span className="pc-num">{formatStamp(when)}</span>
      {delivery.error_message && (
        <span className="pc-deliveryerror">{delivery.error_message}</span>
      )}
    </li>
  )
}
