/* Choosing photographs: take one, or pick from the device.
 *
 * Two controls, not one. A single input carrying `capture="environment"` is the
 * standard trick and it is wrong in both directions: on a phone the attribute makes
 * the control open the camera and *only* the camera, so there was no way to reach the
 * gallery; on a desktop, where there is no capture device to hand to, browsers ignore
 * the attribute and some refuse the picker outright. Reported from real use — "the
 * camera is not working" — and the honest fix is to stop asking one button to mean two
 * things.
 *
 * So: one input with `capture`, one without, each with its own label. The camera input
 * is deliberately not `multiple` — a capture session hands back one photograph, and
 * asking for many from a camera is a request no platform honours.
 *
 * Validation mirrors the database's own constraints (mime in jpeg/png/webp, at most
 * 10 MB) so a file that would be rejected server-side is refused before it is
 * uploaded. The server remains the authority; this is courtesy, not trust.
 */

import { useEffect, useId, useRef, useState } from 'react'
import { ACCEPTED_MIME, MAX_BYTES, MAX_IMAGES } from '../api/identification'
import './ImagePicker.css'

export type PickedImage = { file: File; url: string }

export default function ImagePicker({
  images,
  onChange,
  max = MAX_IMAGES,
  label = 'תמונות הצמח',
}: {
  images: PickedImage[]
  onChange: (next: PickedImage[]) => void
  max?: number
  label?: string
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const cameraRef = useRef<HTMLInputElement>(null)
  const [problem, setProblem] = useState<string | null>(null)

  /* Generated, not hardcoded. A label reaches its input by id, so two pickers on one
     screen sharing a literal would point both labels at whichever input rendered
     first — and the health-check dialog already renders over a page that could grow
     one. */
  const cameraId = useId()
  const fileId = useId()

  /* Object URLs are a manual allocation; without this every retake leaks one for as
     long as the tab lives. */
  useEffect(() => {
    return () => {
      for (const image of images) URL.revokeObjectURL(image.url)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const full = images.length >= max

  function add(files: FileList | null) {
    if (!files?.length) return
    setProblem(null)

    const accepted: PickedImage[] = []
    const rejected: string[] = []

    for (const file of Array.from(files)) {
      /* A camera capture can arrive with an empty `type` on some Android builds, so
         the extension is the fallback rather than an outright rejection of a
         photograph the user just took. */
      const mime = file.type || guessMime(file.name)
      if (!ACCEPTED_MIME.includes(mime)) {
        rejected.push(`${file.name}: סוג קובץ לא נתמך`)
      } else if (file.size > MAX_BYTES) {
        rejected.push(`${file.name}: גדול מ-10MB`)
      } else if (images.length + accepted.length >= max) {
        rejected.push(`${file.name}: אפשר עד ${max} תמונות`)
      } else {
        accepted.push({ file, url: URL.createObjectURL(file) })
      }
    }

    if (rejected.length) setProblem(rejected.join(' · '))
    if (accepted.length) onChange([...images, ...accepted])

    /* Both are cleared, not just the one that fired: choosing the same file twice in a
       row is a real thing to do, and an input still holding it fires no change event. */
    if (fileRef.current) fileRef.current.value = ''
    if (cameraRef.current) cameraRef.current.value = ''
  }

  function remove(index: number) {
    URL.revokeObjectURL(images[index].url)
    onChange(images.filter((_, i) => i !== index))
  }

  return (
    <div className="pc-picker">
      <div className="pc-pickerhead">
        <span className="pc-pickerlabel">{label}</span>
        {/* One LTR run, not two isolated numbers around a slash: in an RTL
            container the latter lays out as "4/1". */}
        <span className="pc-pickercount pc-ltr">{`${images.length}/${max}`}</span>
      </div>

      {images.length > 0 && (
        <ul className="pc-pickergrid">
          {images.map((image, index) => (
            <li key={image.url}>
              <img src={image.url} alt={`תמונה ${index + 1}`} />
              <button
                type="button"
                className="pc-pickerremove"
                onClick={() => remove(index)}
                aria-label={`הסרת תמונה ${index + 1}`}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="pc-pickeractions">
        <input
          ref={cameraRef}
          type="file"
          accept={ACCEPTED_MIME.join(',')}
          capture="environment"
          className="pc-sr-only"
          id={cameraId}
          onChange={(e) => add(e.target.files)}
          disabled={full}
        />
        <label
          htmlFor={cameraId}
          className={`pc-pickerbtn${full ? ' is-full' : ''}`}
        >
          <span className="pc-pickericon" aria-hidden="true">
            ◉
          </span>
          צילום
        </label>

        <input
          ref={fileRef}
          type="file"
          accept={ACCEPTED_MIME.join(',')}
          multiple
          className="pc-sr-only"
          id={fileId}
          onChange={(e) => add(e.target.files)}
          disabled={full}
        />
        <label htmlFor={fileId} className={`pc-pickerbtn${full ? ' is-full' : ''}`}>
          <span className="pc-pickericon" aria-hidden="true">
            ⬆
          </span>
          בחירה מהמכשיר
        </label>
      </div>

      {full && <p className="pc-placeholder-note">{`הגעתם ל-${max} תמונות`}</p>}

      {problem && (
        <p className="pc-formerror" role="alert">
          {problem}
        </p>
      )}
    </div>
  )
}

/** Only the three the database accepts; anything else stays unrecognised. */
function guessMime(name: string): string {
  const ext = name.toLowerCase().split('.').pop() ?? ''
  if (ext === 'jpg' || ext === 'jpeg') return 'image/jpeg'
  if (ext === 'png') return 'image/png'
  if (ext === 'webp') return 'image/webp'
  return ''
}
