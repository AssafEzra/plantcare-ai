/* The plant's photographs: reorder, choose the main one, add, remove (section 20).
 *
 * The gallery is a plant's *portraits* — its `gallery` and `identification` images.
 * Health photographs are evidence for one check, usually a close-up of the damage,
 * and they belong with that check rather than in the grid of what the plant looks
 * like. Migration 0019 draws the same line in the database, so the set shown here,
 * the set that can be reordered and the set the last-image rule protects are one set.
 *
 * Ordering is done with buttons, not HTML5 drag and drop. Section 20 asks for "drag &
 * drop", and the honest reading of that is "the user can change the order" — native
 * dragging does not work by touch at all, which is most of this application's use,
 * and a keyboard user cannot reach it either. Pointer dragging is added on top: the
 * buttons are what make it work everywhere, and they are what a screen reader
 * announces.
 *
 * A reorder is sent as the whole set. The endpoint refuses a partial list, because
 * naming only some images leaves the rest at whatever number they had.
 */

import { useRef, useState } from 'react'
import {
  isPortrait,
  useDeleteImage,
  useReorderImages,
  useSetMainImage,
  useUploadImages,
  type GalleryImage,
} from '../api/plantDetail'
import { ACCEPTED_MIME, MAX_BYTES } from '../api/identification'
import { ApiError } from '../lib/errors'
import './PlantGallery.css'

type Notice = { kind: 'notice' | 'error'; text: string } | null

export default function PlantGallery({
  plantId,
  images,
  canEdit,
}: {
  plantId: string
  images: GalleryImage[]
  /** An archived plant is a record, not something to rearrange. */
  canEdit: boolean
}) {
  const portraits = images.filter(isPortrait)

  /* The order being edited. Held locally so a drag or a nudge redraws immediately
     rather than after a round trip, and reset whenever the server's answer arrives —
     which is what makes a rejected reorder snap back instead of lying about itself.

     Adjusted during render rather than in an effect. React re-renders immediately
     without committing the first pass, so the grid never paints the stale order; an
     effect would paint it once and then correct it, and would also fire a second render
     on every legitimate reorder. `seen` is the server's order as a string, so the
     comparison is one cheap equality rather than an array diff. */
  const serverOrder = portraits.map((image) => image.id).join(',')
  const [order, setOrder] = useState<string[]>(() => (serverOrder ? serverOrder.split(',') : []))
  const [seen, setSeen] = useState(serverOrder)
  const [notice, setNotice] = useState<Notice>(null)
  const [dragging, setDragging] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  if (seen !== serverOrder) {
    setSeen(serverOrder)
    setOrder(serverOrder ? serverOrder.split(',') : [])
  }

  const reorder = useReorderImages(plantId)
  const setMain = useSetMainImage(plantId)
  const remove = useDeleteImage(plantId)
  const upload = useUploadImages(plantId)

  const byId = new Map(portraits.map((image) => [image.id, image]))
  const shown = order.map((id) => byId.get(id)).filter((image): image is GalleryImage => !!image)
  const busy = reorder.isPending || setMain.isPending || remove.isPending || upload.isPending

  function commit(next: string[]) {
    setOrder(next)
    setNotice(null)
    reorder.mutate(next, {
      onError: (error) => {
        setOrder(portraits.map((image) => image.id))
        setNotice({ kind: 'error', text: message(error, 'לא הצלחנו לשמור את הסדר.') })
      },
    })
  }

  function move(id: string, by: number) {
    const from = order.indexOf(id)
    const to = from + by
    if (from < 0 || to < 0 || to >= order.length) return
    const next = [...order]
    next.splice(to, 0, ...next.splice(from, 1))
    commit(next)
  }

  function dropOn(targetId: string) {
    if (!dragging || dragging === targetId) return
    const next = order.filter((id) => id !== dragging)
    next.splice(order.indexOf(targetId), 0, dragging)
    setDragging(null)
    commit(next)
  }

  function add(files: FileList | null) {
    if (!files?.length) return
    setNotice(null)

    const accepted: File[] = []
    const rejected: string[] = []
    for (const file of Array.from(files)) {
      if (!ACCEPTED_MIME.includes(file.type)) rejected.push(`${file.name}: סוג קובץ לא נתמך`)
      else if (file.size > MAX_BYTES) rejected.push(`${file.name}: גדול מ-10MB`)
      else accepted.push(file)
    }
    if (fileInput.current) fileInput.current.value = ''
    if (rejected.length) setNotice({ kind: 'error', text: rejected.join(' · ') })
    if (!accepted.length) return

    upload.mutate(accepted, {
      onError: (error) =>
        setNotice({ kind: 'error', text: message(error, 'לא הצלחנו להעלות את התמונות.') }),
    })
  }

  function removeImage(image: GalleryImage) {
    setNotice(null)
    remove.mutate(image.id, {
      onSuccess: (result) =>
        setNotice(
          result.outcome === 'hidden'
            ? {
                /* FINAL section 20: an image the AI has used is hidden rather than
                   destroyed, because an assessment that cited it must stay legible.
                   The user is told which of the two happened. */
                kind: 'notice',
                text: 'התמונה הוסרה מהגלריה. היא נשמרת כראיה לניתוח שהתבסס עליה.',
              }
            : { kind: 'notice', text: 'התמונה נמחקה.' },
        ),
      onError: (error) =>
        setNotice({ kind: 'error', text: message(error, 'לא הצלחנו להסיר את התמונה.') }),
    })
  }

  return (
    <div className="pc-gallery">
      {notice && (
        <p
          className={notice.kind === 'error' ? 'pc-formerror' : 'pc-formnotice'}
          role={notice.kind === 'error' ? 'alert' : 'status'}
        >
          {notice.text}
        </p>
      )}

      {shown.length === 0 ? (
        <p className="pc-placeholder-note">אין עדיין תמונות לצמח הזה.</p>
      ) : (
        <ul className="pc-gallerygrid">
          {shown.map((image, index) => (
            <li
              key={image.id}
              className={`pc-galleryitem${image.is_main ? ' is-main' : ''}${
                dragging === image.id ? ' is-dragging' : ''
              }`}
              draggable={canEdit && shown.length > 1}
              onDragStart={() => setDragging(image.id)}
              onDragEnd={() => setDragging(null)}
              onDragOver={(event) => {
                if (dragging) event.preventDefault()
              }}
              onDrop={() => dropOn(image.id)}
            >
              <img
                src={image.thumbnail_url ?? image.url ?? ''}
                alt={image.is_main ? 'התמונה הראשית של הצמח' : `תמונה ${index + 1}`}
                loading="lazy"
              />

              {image.is_main && <span className="pc-gallerymain">ראשית</span>}

              {canEdit && (
                <div className="pc-galleryactions">
                  {/* Ordering by keyboard and by touch. `aria-label` carries the
                      position, so a screen reader hears what actually moves. */}
                  <button
                    type="button"
                    className="pc-galleryicon"
                    disabled={busy || index === 0}
                    onClick={() => move(image.id, -1)}
                    aria-label={`העברת תמונה ${index + 1} אחורה`}
                  >
                    ‹
                  </button>
                  <button
                    type="button"
                    className="pc-galleryicon"
                    disabled={busy || index === shown.length - 1}
                    onClick={() => move(image.id, 1)}
                    aria-label={`העברת תמונה ${index + 1} קדימה`}
                  >
                    ›
                  </button>
                  {!image.is_main && (
                    <button
                      type="button"
                      className="pc-galleryicon"
                      disabled={busy}
                      onClick={() => setMain.mutate(image.id)}
                      aria-label={`הגדרת תמונה ${index + 1} כתמונה ראשית`}
                      title="הגדרה כתמונה ראשית"
                    >
                      ★
                    </button>
                  )}
                  <button
                    type="button"
                    className="pc-galleryicon is-danger"
                    disabled={busy}
                    onClick={() => removeImage(image)}
                    aria-label={`הסרת תמונה ${index + 1}`}
                  >
                    ✕
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {canEdit && (
        <>
          <input
            ref={fileInput}
            type="file"
            id={`pc-gallery-add-${plantId}`}
            className="pc-sr-only"
            accept={ACCEPTED_MIME.join(',')}
            capture="environment"
            multiple
            disabled={busy}
            onChange={(event) => add(event.target.files)}
          />
          <label htmlFor={`pc-gallery-add-${plantId}`} className="pc-galleryadd">
            {upload.isPending ? 'מעלים…' : 'הוספת תמונות'}
          </label>
          {shown.length > 1 && (
            <p className="pc-placeholder-note">
              אפשר לגרור תמונה למקום אחר, או להשתמש בחצים. התמונה המסומנת בכוכב היא
              הראשית.
            </p>
          )}
        </>
      )}
    </div>
  )
}

function message(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}
