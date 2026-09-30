/* Starting a health check, with photographs taken now (FINAL section 16).
 *
 * Reported from real use of the Streamlit build: "when starting a health check it
 * should lead to a new window and give option to load pic, not just select one".
 *
 * The old form was an inline box offering a multiselect over images already in the
 * plant's gallery, which is the wrong shape for the thing being asked. A health check
 * is prompted by something the user has *just noticed*, and the photograph that shows
 * it does not exist yet — worse, a plant with no photographs reached a dead end,
 * "upload one first" with nothing there to upload with.
 *
 * A dialog rather than a page: the check belongs to the plant the user is looking at,
 * and its result lands on that same page. Sending them elsewhere and back would lose
 * the context that makes the answer meaningful.
 *
 * Uploading is a real round trip per file, so it happens on submit rather than on
 * selection — an upload that only matters if the check is actually sent should not
 * happen while the user is still deciding.
 */

import { useState } from 'react'
import { MAX_HEALTH_IMAGES } from '../api/health'
import type { GalleryImage } from '../api/plantDetail'
import { formatStamp } from '../lib/dates'
import { ApiError } from '../lib/errors'
import ImagePicker, { type PickedImage } from './ImagePicker'
import Modal from './Modal'

export default function HealthCheckDialog({
  gallery,
  onSubmit,
  onClose,
  busy,
  error,
}: {
  gallery: GalleryImage[]
  onSubmit: (files: File[], existingImageIds: string[], note: string | null) => void
  onClose: () => void
  busy: boolean
  error: unknown
}) {
  const [picked, setPicked] = useState<PickedImage[]>([])
  const [chosen, setChosen] = useState<string[]>([])
  const [note, setNote] = useState('')

  const total = picked.length + chosen.length
  const tooMany = total > MAX_HEALTH_IMAGES

  function toggle(imageId: string) {
    setChosen((current) =>
      current.includes(imageId)
        ? current.filter((id) => id !== imageId)
        : [...current, imageId],
    )
  }

  return (
    <Modal title="בדיקת בריאות" onClose={onClose}>
      <p>
        אפשר לצלם עכשיו, להעלות מהמכשיר, או לבחור תמונות קיימות — עד{' '}
        <span className="pc-num">{MAX_HEALTH_IMAGES}</span> בסך הכול. תמונות חדות באור יום,
        מקרוב ומרחוק, עוזרות מאוד.
      </p>

      <ImagePicker
        images={picked}
        onChange={setPicked}
        max={MAX_HEALTH_IMAGES}
        label="תמונות חדשות"
      />

      {gallery.length > 0 && (
        <fieldset className="pc-pickexisting">
          <legend>או מתוך התמונות הקיימות</legend>
          <ul>
            {gallery.map((image, index) => (
              <li key={image.id}>
                <label>
                  <input
                    type="checkbox"
                    checked={chosen.includes(image.id)}
                    onChange={() => toggle(image.id)}
                  />
                  {/* The number, not the date alone. Three photographs taken in one
                      afternoon produced three options reading identically, and the time
                      was not enough either — the three that prompted this were uploaded
                      at 17:08:05, :11 and :15, all the same minute. */}
                  <span className="pc-num">{index + 1}</span>. תמונה מ-
                  <span className="pc-num">{formatStamp(image.created_at)}</span>
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
      )}

      <label className="pc-field">
        <span>מה מטריד אותך? (אופציונלי)</span>
        <input
          type="text"
          maxLength={1000}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="למשל: העלים התחתונים מצהיבים כבר שבועיים"
        />
      </label>

      {/* Said here rather than left to the server: the user has already spent the
          effort of choosing, and a 422 after submit wastes an upload. */}
      {tooMany && (
        <p className="pc-formerror" role="alert">
          נבחרו <span className="pc-num">{total}</span> תמונות. אפשר עד{' '}
          <span className="pc-num">{MAX_HEALTH_IMAGES}</span> בבדיקה אחת.
        </p>
      )}
      {total === 0 && <p className="pc-placeholder-note">צריך לפחות תמונה אחת כדי לבדוק.</p>}

      {error ? (
        <p className="pc-formerror" role="alert">
          {error instanceof ApiError ? error.message : 'לא הצלחנו להתחיל את הבדיקה.'}
        </p>
      ) : null}

      <div className="pc-actionrow">
        <button
          type="button"
          className="pc-btn"
          disabled={busy || total === 0 || tooMany}
          onClick={() =>
            onSubmit(
              picked.map((image) => image.file),
              chosen,
              note.trim() || null,
            )
          }
        >
          {busy ? 'שולחים…' : 'שליחה לבדיקה'}
        </button>
        <button type="button" className="pc-btn pc-btn-quiet" disabled={busy} onClick={onClose}>
          ביטול
        </button>
      </div>
    </Modal>
  )
}
