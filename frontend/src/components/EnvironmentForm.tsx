/* Growing conditions — תנאי הגידול (FINAL section 18).
 *
 * Every field is optional. Section 18 says the Care Agent works with partial data, and
 * this is the environment the *user* can describe: someone who knows their plant is on
 * a north-facing windowsill should not have to invent a humidity reading to say so.
 *
 * Numbers are left empty rather than defaulted. A temperature nobody typed is not
 * 20°C, and a care plan built on an invented number is worse than one built on an
 * admitted gap.
 *
 * `onSave` receives every field, including the ones left blank, because the endpoint
 * replaces the row — "I no longer know the humidity" is a real edit, and omitting the
 * key would silently keep the old value.
 */

import { useState } from 'react'
import type { Environment } from '../api/plantDetail'
import {
  DIRECTION_LABELS,
  LIGHT_LABELS,
  LOCATION_LABELS,
  describeEnvironment,
  ENVIRONMENT_FIELDS,
} from '../lib/careVocab'
import { ApiError } from '../lib/errors'

const UNSET = ''

export function EnvironmentSummary({ environment }: { environment: Environment | null }) {
  const filled = ENVIRONMENT_FIELDS.filter(([field]) => {
    const value = environment?.[field as keyof Environment]
    return value !== null && value !== undefined && value !== ''
  })

  if (!filled.length) {
    return (
      <p className="pc-placeholder-note">
        עדיין לא הוגדרו תנאי גידול. אפשר למלא כאן — כל שדה הוא רשות.
      </p>
    )
  }

  return (
    <dl className="pc-kv">
      {filled.map(([field, label]) => (
        <div key={field} style={{ display: 'contents' }}>
          <dt>{label}</dt>
          <dd>{describeEnvironment(field, environment?.[field as keyof Environment])}</dd>
        </div>
      ))}
    </dl>
  )
}

export default function EnvironmentForm({
  environment,
  onSave,
  saving,
  error,
}: {
  environment: Environment | null
  onSave: (values: Partial<Environment>) => void
  saving: boolean
  error: unknown
}) {
  const [location, setLocation] = useState(environment?.location_type ?? UNSET)
  const [light, setLight] = useState(environment?.light_level ?? UNSET)
  const [direction, setDirection] = useState(environment?.light_direction ?? UNSET)
  const [temperature, setTemperature] = useState(
    environment?.temperature_c === null || environment?.temperature_c === undefined
      ? ''
      : String(environment.temperature_c),
  )
  const [humidity, setHumidity] = useState(
    environment?.humidity_percent === null || environment?.humidity_percent === undefined
      ? ''
      : String(environment.humidity_percent),
  )
  const [room, setRoom] = useState(environment?.room ?? '')
  const [notes, setNotes] = useState(environment?.notes ?? '')

  function submit() {
    onSave({
      location_type: location || null,
      light_level: light || null,
      light_direction: direction || null,
      temperature_c: temperature.trim() === '' ? null : Number(temperature),
      humidity_percent: humidity.trim() === '' ? null : Number(humidity),
      room: room.trim() || null,
      notes: notes.trim() || null,
    })
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      {/* Section 12: an environment change produces a proposal, never a silent
          rewrite. Saying so here sets the expectation before the user changes one. */}
      <p className="pc-placeholder-note">
        עדכון התנאים מפעיל בדיקה של תוכנית הטיפול, אך לא משנה אותה אוטומטית.
      </p>

      <Choice label="מיקום" labels={LOCATION_LABELS} value={location} onChange={setLocation} />
      <Choice label="עוצמת אור" labels={LIGHT_LABELS} value={light} onChange={setLight} />
      <Choice
        label="כיוון החלון"
        labels={DIRECTION_LABELS}
        value={direction}
        onChange={setDirection}
      />

      <label className="pc-field">
        <span>טמפרטורה (°C)</span>
        <input
          type="number"
          min={-50}
          max={60}
          step={1}
          value={temperature}
          placeholder="לא ידוע"
          onChange={(event) => setTemperature(event.target.value)}
        />
      </label>

      <label className="pc-field">
        <span>לחות (%)</span>
        <input
          type="number"
          min={0}
          max={100}
          step={5}
          value={humidity}
          placeholder="לא ידוע"
          onChange={(event) => setHumidity(event.target.value)}
        />
      </label>

      <label className="pc-field">
        <span>חדר</span>
        <input
          type="text"
          maxLength={120}
          value={room}
          placeholder="למשל: הסלון"
          onChange={(event) => setRoom(event.target.value)}
        />
      </label>

      <label className="pc-field">
        <span>הערות</span>
        <textarea
          rows={3}
          maxLength={2000}
          value={notes}
          placeholder="למשל: מעל רדיאטור, מול חלון גדול"
          onChange={(event) => setNotes(event.target.value)}
        />
      </label>

      {error ? (
        <p className="pc-formerror" role="alert">
          {error instanceof ApiError ? error.message : 'לא הצלחנו לשמור את התנאים.'}
        </p>
      ) : null}

      <button type="submit" className="pc-btn" disabled={saving}>
        {saving ? 'שומרים…' : 'שמירת תנאי הגידול'}
      </button>
    </form>
  )
}

function Choice({
  label,
  labels,
  value,
  onChange,
}: {
  label: string
  labels: Record<string, string>
  value: string
  onChange: (next: string) => void
}) {
  return (
    <label className="pc-field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value={UNSET}>לא צוין</option>
        {Object.entries(labels).map(([code, text]) => (
          <option key={code} value={code}>
            {text}
          </option>
        ))}
      </select>
    </label>
  )
}
