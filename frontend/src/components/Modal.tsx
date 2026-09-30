/* A dialog, for a decision that should have the screen to itself.
 *
 * Two of these exist in the product and both are there for the same reason. The care
 * proposal used to render inline on the plant page, so an approve/reject choice sat
 * in the middle of a scrolling page beside the health card and the timeline; the
 * health check used to be an inline form, so a user who had just noticed something
 * had to scroll past the whole plan to report it. A modal cannot be scrolled past.
 *
 * Built on <dialog>, not a div with a high z-index. `showModal()` gives focus
 * containment, an inert background, Escape-to-close and the top layer without any of
 * it being written here — four things a hand-rolled overlay gets wrong one at a time.
 */

import { useEffect, useRef, type ReactNode } from 'react'
import './Modal.css'

export default function Modal({
  title,
  onClose,
  children,
  labelledBy = 'pc-modal-title',
}: {
  title: string
  onClose: () => void
  children: ReactNode
  labelledBy?: string
}) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog || dialog.open) return
    dialog.showModal()
    return () => dialog.close()
  }, [])

  return (
    <dialog
      ref={ref}
      className="pc-modal"
      aria-labelledby={labelledBy}
      /* Escape fires `cancel`, and without this the element closes while the state
         that renders it stays true — so it never reopens. */
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      /* The backdrop is part of the dialog's own box, so a click that lands on the
         element itself rather than on the card inside it is a click outside. */
      onClick={(event) => {
        if (event.target === ref.current) onClose()
      }}
    >
      <div className="pc-modalbody">
        <header className="pc-modalhead">
          <h2 id={labelledBy}>{title}</h2>
          <button type="button" className="pc-modalclose" onClick={onClose} aria-label="סגירה">
            ✕
          </button>
        </header>
        <div className="pc-modalcontent">{children}</div>
      </div>
    </dialog>
  )
}
