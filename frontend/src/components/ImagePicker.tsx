/* Choosing photographs.
 *
 * `capture="environment"` is what makes a phone offer the camera directly; on desktop
 * the same input is an ordinary file chooser, so one control serves both without a
 * separate "take a photo" mode.
 *
 * Validation here mirrors the database's own constraints (mime in jpeg/png/webp,
 * at most 10 MB) so a file that would be rejected server-side is refused before it is
 * uploaded. The server remains the authority; this is courtesy, not trust.
 */

import { useEffect, useRef, useState } from 'react'
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
  const inputRef = useRef<HTMLInputElement>(null)
  const [problem, setProblem] = useState<string | null>(null)

  /* Object URLs are a manual allocation; without this every retake leaks one for as
     long as the tab lives. */
  useEffect(() => {
    return () => {
      for (const image of images) URL.revokeObjectURL(image.url)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function add(files: FileList | null) {
    if (!files?.length) return
    setProblem(null)

    const accepted: PickedImage[] = []
    const rejected: string[] = []

    for (const file of Array.from(files)) {
      if (!ACCEPTED_MIME.includes(file.type)) {
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
    if (inputRef.current) inputRef.current.value = ''
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

      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_MIME.join(',')}
        capture="environment"
        multiple
        className="pc-sr-only"
        id="pc-picker-input"
        onChange={(e) => add(e.target.files)}
        disabled={images.length >= max}
      />
      <label
        htmlFor="pc-picker-input"
        className={`pc-pickerdrop${images.length >= max ? ' is-full' : ''}`}
      >
        {images.length >= max ? `הגעתם ל-${max} תמונות` : 'צילום או בחירת תמונות'}
      </label>

      {problem && (
        <p className="pc-formerror" role="alert">
          {problem}
        </p>
      )}
    </div>
  )
}
