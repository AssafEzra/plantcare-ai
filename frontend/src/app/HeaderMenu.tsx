/* A header popover: trigger button plus a panel.
 *
 * Shared by the notification bell and the user menu so the dismissal behaviour is
 * identical and correct in one place — Escape closes and returns focus to the
 * trigger, a click outside closes, and the panel is labelled by its trigger.
 *
 * Deliberately not a <dialog>: these are menus, not modals. Trapping focus and
 * blocking the page behind them would be wrong for a bell.
 */

import { useEffect, useId, useRef, useState, type ReactNode } from 'react'

export default function HeaderMenu({
  label,
  icon,
  children,
  badge,
}: {
  label: string
  icon: ReactNode
  children: (close: () => void) => ReactNode
  /** Small count on the trigger; omitted when zero. */
  badge?: number
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelId = useId()

  useEffect(() => {
    if (!open) return

    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false)
        triggerRef.current?.focus()
      }
    }

    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <div className="pc-menu" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="pc-iconbtn"
        aria-label={label}
        aria-expanded={open}
        aria-haspopup="true"
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((v) => !v)}
      >
        {icon}
        {badge !== undefined && badge > 0 && (
          <span className="pc-badge" aria-hidden="true">
            {badge > 9 ? '9+' : badge}
          </span>
        )}
      </button>

      {open && (
        <div className="pc-menupanel" id={panelId} role="group" aria-label={label}>
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  )
}
