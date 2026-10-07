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
import { useCareImpact, useMe, useUpdateProfile, type Profile } from '../api/profile'
import { useSetPlantIntensity } from '../api/plantDetail'
import {
  INTENSITY_HINTS,
  INTENSITY_LABELS,
  WEEK,
  warningText,
  type CareIntensity,
  type Weekday,
} from '../lib/careSchedule'
import { WEEKDAY_LABELS } from '../lib/careVocab'
import {
  DELIVERY_LABELS,
  useDeliveries,
  usePreferences,
  useUpdatePreferences,
  type NotificationDelivery,
  type NotificationPreferences,
} from '../api/notifications'
import {
  usePushConfig,
  usePushDevices,
  useRegisterThisDevice,
  useRemoveDevice,
  useThisEndpoint,
  useToggleDevice,
  type PushDevice,
} from '../api/push'
import { isIOS, isPhoneOrTablet, isStandalone, pushSupported } from '../lib/push'
import { formatDate } from '../lib/dates'
import { formatStamp } from '../lib/dates'
import { useIsReadOnly } from '../lib/viewAs'
import { ApiError } from '../lib/errors'
import Async from '../components/Async'
import './Settings.css'
import PageHero from '../components/PageHero'
import VersionCard from './VersionCard'

export default function Settings() {
  const profile = useMe()
  const preferences = usePreferences()
  const readOnly = useIsReadOnly()

  return (
    <section className="pc-settings">
      <PageHero eyebrow="החשבון שלכם" title="הגדרות" subtitle="פרופיל, אזור זמן ותזכורות" />

      {readOnly && (
        <p className="pc-placeholder-note">
          צפייה בהגדרות של משתמש אחר. אי אפשר לשנות אותן מכאן.
        </p>
      )}

      <Async query={profile} loadingLabel="טוען את הפרופיל…">
        {profile.data && <ProfileForm profile={profile.data} readOnly={readOnly} />}
      </Async>

      <div className="pc-sectionhead">
        <h2>עוצמת טיפול</h2>
      </div>

      <Async query={profile} loadingLabel="טוען…">
        {profile.data && <CareIntensityForm profile={profile.data} readOnly={readOnly} />}
      </Async>

      <div className="pc-sectionhead">
        <h2>תזכורות</h2>
      </div>

      <Async query={preferences} loadingLabel="טוען העדפות…">
        {preferences.data && (
          <>
            <RemindersCard preferences={preferences.data} readOnly={readOnly} />
            <EmailCard preferences={preferences.data} readOnly={readOnly} />
          </>
        )}
      </Async>

      <PushCard readOnly={readOnly} />

      <Deliveries />

      <div className="pc-sectionhead">
        <h2>גרסה</h2>
      </div>

      <VersionCard />
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

/* --- care intensity ------------------------------------------------------- */

const LEVELS: CareIntensity[] = ['HIGH', 'MEDIUM', 'LOW']

/**
 * How tightly care is grouped onto weekdays.
 *
 * Saving applies at once to every plant that follows the setting - no proposal, no
 * approval - so the plants it would leave short are listed *before* saving, each with
 * a way to keep that one plant on high.
 */
function CareIntensityForm({ profile, readOnly }: { profile: Profile; readOnly: boolean }) {
  const [intensity, setIntensity] = useState<CareIntensity>(profile.care_intensity ?? 'HIGH')
  const [lowDay, setLowDay] = useState<Weekday>(profile.care_day_low ?? 'FRIDAY')
  const [mediumDays, setMediumDays] = useState<Weekday[]>(
    profile.care_days_medium?.length === 2 ? profile.care_days_medium : ['TUESDAY', 'FRIDAY'],
  )
  const [nothing, setNothing] = useState(false)
  const update = useUpdateProfile()
  const pin = useSetPlantIntensity()

  const mediumValid = mediumDays.length === 2 && mediumDays[0] !== mediumDays[1]
  const changes: Partial<Pick<Profile, 'care_intensity' | 'care_day_low' | 'care_days_medium'>> =
    {}
  if (intensity !== profile.care_intensity) changes.care_intensity = intensity
  if (lowDay !== profile.care_day_low) changes.care_day_low = lowDay
  if (mediumDays.join() !== (profile.care_days_medium ?? []).join()) {
    changes.care_days_medium = mediumDays
  }
  const dirty = Object.keys(changes).length > 0

  const impact = useCareImpact(
    { intensity, care_day_low: lowDay, care_days_medium: mediumDays },
    intensity !== 'HIGH' && mediumValid,
  )
  const affected = impact.data ?? []

  function submit() {
    setNothing(false)
    if (!dirty) {
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
      <fieldset className="pc-intensitylevels" disabled={readOnly}>
        <legend className="pc-sr-only">עוצמת טיפול</legend>
        {LEVELS.map((level) => (
          <label key={level} className="pc-toggle">
            <input
              type="radio"
              name="care-intensity"
              value={level}
              checked={intensity === level}
              onChange={() => setIntensity(level)}
            />
            <span>
              <strong>{INTENSITY_LABELS[level]}</strong> — {INTENSITY_HINTS[level]}
            </span>
          </label>
        ))}
      </fieldset>

      {intensity === 'LOW' && (
        <label className="pc-field">
          <span>יום הטיפול</span>
          <DaySelect value={lowDay} onChange={setLowDay} disabled={readOnly} />
        </label>
      )}

      {intensity === 'MEDIUM' && (
        <div className="pc-daypair">
          {[0, 1].map((index) => (
            <label key={index} className="pc-field">
              <span>{index === 0 ? 'יום טיפול ראשון' : 'יום טיפול שני'}</span>
              <DaySelect
                value={mediumDays[index]}
                disabled={readOnly}
                onChange={(day) =>
                  setMediumDays((current) =>
                    index === 0 ? [day, current[1]] : [current[0], day],
                  )
                }
              />
            </label>
          ))}
          {!mediumValid && (
            <p className="pc-formerror" role="alert">
              יש לבחור שני ימים שונים.
            </p>
          )}
        </div>
      )}

      {intensity !== 'HIGH' && (
        <p className="pc-placeholder-note">
          המשימות מועברות ליום הטיפול הקרוב, ולא מוקדם מדי אחרי הפעם הקודמת. אפשר לשנות
          צמח מסוים מהכרטיס שלו.
        </p>
      )}

      {affected.length > 0 && (
        <div className="pc-intensitywarn" role="note">
          <p>צמחים שעלולים לקבל פחות מדי טיפול:</p>
          <ul>
            {affected.map((plant) => (
              <li key={plant.plant_id}>
                <strong>{plant.plant_name ?? 'צמח ללא שם'}</strong>
                <ul>
                  {plant.tasks.map((task) => (
                    <li key={task.action_type}>{warningText(task)}</li>
                  ))}
                </ul>
                {!readOnly && (
                  <button
                    type="button"
                    className="pc-btn pc-btn-sm"
                    disabled={pin.isPending}
                    onClick={() => pin.mutate({ plantId: plant.plant_id, intensity: 'HIGH' })}
                  >
                    להשאיר את הצמח הזה על גבוהה
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {update.error ? (
        <p className="pc-formerror" role="alert">
          {update.error instanceof ApiError ? update.error.message : 'ההגדרות לא נשמרו.'}
        </p>
      ) : null}
      {update.isSuccess && !dirty && (
        <p className="pc-formnotice" role="status">
          נשמר. המשימות הקיימות הועברו בהתאם.
        </p>
      )}
      {nothing && <p className="pc-placeholder-note">אין שינויים לשמור.</p>}

      {!readOnly && (
        <button
          type="submit"
          className="pc-btn"
          disabled={update.isPending || (intensity === 'MEDIUM' && !mediumValid)}
        >
          {update.isPending ? 'שומרים…' : 'שמירת עוצמת הטיפול'}
        </button>
      )}
    </form>
  )
}

function DaySelect({
  value,
  onChange,
  disabled,
}: {
  value: Weekday
  onChange: (day: Weekday) => void
  disabled: boolean
}) {
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value as Weekday)}
    >
      {WEEK.map((day) => (
        <option key={day} value={day}>
          {WEEKDAY_LABELS[day]}
        </option>
      ))}
    </select>
  )
}

/* --- reminders ------------------------------------------------------------ */

/* Each control saves on change: a switch that needs a separate Save button is a
   switch that looks on and is not. */

const DUE_DAY_OPTIONS = [
  { value: 0, label: 'לא להזכיר' },
  { value: 1, label: 'יום אחד' },
  { value: 2, label: 'יומיים' },
  { value: 3, label: '3 ימים' },
]

function SaveState({ update }: { update: ReturnType<typeof useUpdatePreferences> }) {
  if (update.error) {
    return (
      <p className="pc-formerror" role="alert">
        {update.error instanceof ApiError ? update.error.message : 'השינוי לא נשמר.'}
      </p>
    )
  }
  if (update.isSuccess && !update.isPending) {
    return (
      <p className="pc-formnotice" role="status">
        נשמר.
      </p>
    )
  }
  return null
}

/**
 * What the reminders say and when. The time is fixed at 07:30 for now - stored per
 * user so it can become a choice later, but not offered yet.
 */
function RemindersCard({
  preferences,
  readOnly,
}: {
  preferences: NotificationPreferences
  readOnly: boolean
}) {
  const update = useUpdatePreferences()

  return (
    <div className="pc-card">
      <p className="pc-placeholder-note">
        כל בוקר ב-07:30 נשלחות{' '}
        <span className="pc-remind-today">המשימות של היום</span> ובנפרד{' '}
        <span className="pc-remind-late">המשימות שבאיחור</span>, רק כשיש מה לספר.
      </p>

      <label className="pc-field">
        <span>להזכיר על משימה שבאיחור</span>
        <select
          value={preferences.due_reminder_days}
          disabled={readOnly || update.isPending}
          onChange={(event) =>
            update.mutate({ due_reminder_days: Number(event.target.value) })
          }
        >
          {DUE_DAY_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <small>כמה ימים אחרי מועד המשימה עוד להזכיר עליה.</small>
      </label>

      <label className="pc-toggle">
        <input
          type="checkbox"
          checked={preferences.evening_enabled}
          disabled={readOnly || update.isPending}
          onChange={(event) => update.mutate({ evening_enabled: event.target.checked })}
        />
        <span>תזכורת ערב ב-19:00 על משימות היום שעדיין פתוחות (בטלפון בלבד)</span>
      </label>

      <SaveState update={update} />
    </div>
  )
}

function EmailCard({
  preferences,
  readOnly,
}: {
  preferences: NotificationPreferences
  readOnly: boolean
}) {
  const update = useUpdatePreferences()

  return (
    <div className="pc-card">
      <h2>מייל</h2>
      <label className="pc-toggle">
        <input
          type="checkbox"
          checked={preferences.email_enabled}
          disabled={readOnly || update.isPending}
          onChange={(event) => update.mutate({ email_enabled: event.target.checked })}
        />
        <span>תזכורות במייל</span>
      </label>
      <p className="pc-placeholder-note">
        {preferences.email_enabled
          ? 'מייל אחד בבוקר, עם המשימות של היום ועם המשימות שבאיחור.'
          : 'התזכורות במייל כבויות. המשימות עדיין מופיעות במסך הבית.'}
      </p>
      <SaveState update={update} />
    </div>
  )
}

/* --- push ------------------------------------------------------------------ */

/**
 * Phone and tablet notifications.
 *
 * Turning reminders on has to happen on the phone itself: only its browser can ask
 * for permission. After that the server holds the registration, so the device list
 * - on every device, desktop included - can pause, resume or remove it.
 */
function PushCard({ readOnly }: { readOnly: boolean }) {
  const config = usePushConfig()
  const devices = usePushDevices()
  const thisEndpoint = useThisEndpoint()

  const onPhone = isPhoneOrTablet()
  const list = devices.data ?? []
  const thisDevice = list.find((device) => device.endpoint === thisEndpoint.data)
  const others = list.filter((device) => device !== thisDevice)

  return (
    <div className="pc-card pc-push">
      <h2>התראות בטלפון</h2>

      {config.data && !config.data.configured && (
        <p className="pc-placeholder-note">ההתראות בטלפון עדיין לא הופעלו בשרת.</p>
      )}

      {onPhone ? (
        <ThisDevice
          device={thisDevice}
          publicKey={config.data?.public_key ?? null}
          readOnly={readOnly}
        />
      ) : (
        list.length === 0 && (
          <p className="pc-placeholder-note">
            ההתראות זמינות בטלפון ובטאבלט. פתחו שם את האפליקציה והפעילו אותן.
          </p>
        )
      )}

      {others.length > 0 && (
        <>
          <h3 className="pc-push-sub">{onPhone ? 'מכשירים נוספים' : 'המכשירים שלך'}</h3>
          <ul className="pc-devices">
            {others.map((device) => (
              <DeviceRow key={device.id} device={device} readOnly={readOnly} />
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function ThisDevice({
  device,
  publicKey,
  readOnly,
}: {
  device: PushDevice | undefined
  publicKey: string | null
  readOnly: boolean
}) {
  const register = useRegisterThisDevice()
  const toggle = useToggleDevice()
  const permission = typeof Notification === 'undefined' ? 'default' : Notification.permission

  /* iPhone: push exists only in the app installed to the home screen. A button
     here could never work, so the steps take its place. */
  if (isIOS() && !isStandalone()) {
    return (
      <div className="pc-install">
        <p>כדי לקבל תזכורות באייפון, צריך להוסיף את האפליקציה למסך הבית:</p>
        <ol>
          <li>
            לחצו על כפתור השיתוף <span aria-hidden="true">⬆️</span> בתחתית Safari
          </li>
          <li>בחרו „הוספה למסך הבית"</li>
          <li>פתחו את PlantCare מהאייקון החדש וחזרו לכאן</li>
        </ol>
      </div>
    )
  }

  if (!pushSupported()) {
    return <p className="pc-placeholder-note">הדפדפן הזה לא תומך בהתראות. נסו Chrome.</p>
  }

  if (permission === 'denied') {
    return (
      <p className="pc-placeholder-note">
        ההתראות חסומות במכשיר הזה. כדי לאפשר אותן: הגדרות הטלפון ← PlantCare (או הדפדפן) ←
        התראות.
      </p>
    )
  }

  if (device) {
    return (
      <div className="pc-thisdevice">
        <label className="pc-toggle">
          <input
            type="checkbox"
            checked={device.enabled}
            disabled={readOnly || toggle.isPending}
            onChange={(event) => toggle.mutate({ id: device.id, enabled: event.target.checked })}
          />
          <span>תזכורות במכשיר הזה ({device.device_label ?? 'המכשיר הזה'})</span>
        </label>
      </div>
    )
  }

  return (
    <div className="pc-thisdevice">
      <button
        type="button"
        className="pc-btn"
        disabled={readOnly || !publicKey || register.isPending}
        onClick={() => publicKey && register.mutate(publicKey)}
      >
        {register.isPending ? 'מפעילים…' : 'הפעלת תזכורות במכשיר הזה'}
      </button>
      <p className="pc-placeholder-note">הטלפון יבקש אישור להציג התראות.</p>
      {register.error ? (
        <p className="pc-formerror" role="alert">
          {register.error instanceof Error && register.error.message === 'denied'
            ? 'לא ניתן אישור. אפשר לשנות זאת בהגדרות הטלפון.'
            : 'ההפעלה לא הצליחה. נסו שוב.'}
        </p>
      ) : null}
    </div>
  )
}

function DeviceRow({ device, readOnly }: { device: PushDevice; readOnly: boolean }) {
  const toggle = useToggleDevice()
  const remove = useRemoveDevice()
  const busy = toggle.isPending || remove.isPending

  return (
    <li>
      <label className="pc-toggle">
        <input
          type="checkbox"
          checked={device.enabled}
          disabled={readOnly || busy}
          onChange={(event) => toggle.mutate({ id: device.id, enabled: event.target.checked })}
        />
        <span>
          {device.device_label ?? 'מכשיר'}{' '}
          <small className="pc-num">· נוסף {formatDate(device.created_at)}</small>
        </span>
      </label>
      {!readOnly && (
        <button
          type="button"
          className="pc-btn pc-btn-sm pc-btn-quiet"
          disabled={busy}
          onClick={() => remove.mutate({ id: device.id, endpoint: device.endpoint })}
        >
          הסרה
        </button>
      )}
    </li>
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
