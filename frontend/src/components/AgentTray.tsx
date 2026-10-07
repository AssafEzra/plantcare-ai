/* The agent tray: a small panel that says what the agents are doing.
 *
 * The watcher in api/agentRequests.ts knows what is running; until this, nothing
 * showed it. One row per run, a spinner while it goes, a green tick or a red cross
 * when it lands, and neither fades — the panel closes only once everything in it
 * has settled, and closing is what clears it.
 *
 * Deliberately duplicates the progress already on Add Plant and the plant page.
 * Those say what stage a run has reached; this says only that an agent is active,
 * from wherever you happen to be standing.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTrayRows, type TrayRow } from '../api/agentRequests'
import { usePlants, plantName } from '../api/plants'
import './AgentTray.css'

const POSITION_KEY = 'pc.agenttray.position'

const AGENT_NAMES: Record<string, string> = {
  IDENTIFICATION: 'זיהוי',
  KNOWLEDGE: 'מחקר מקצועי',
  CARE: 'תוכנית טיפול',
  HEALTH: 'בדיקת בריאות',
}

type Point = { x: number; y: number }

/* The width at which the sidebar replaces the bottom bar (AppShell.css). Below it
   the popup docks above the bar and is not draggable: there is no room worth moving
   it around in, and a draggable overlay fights the scroll. */
const WIDE = '(min-width: 900px)'

function isWide(): boolean {
  return window.matchMedia?.(WIDE).matches ?? false
}

function readPosition(): Point | null {
  try {
    const raw = localStorage.getItem(POSITION_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Point
    if (typeof parsed?.x !== 'number' || typeof parsed?.y !== 'number') return null
    return parsed
  } catch {
    // Private mode, cleared site data, or a value from an older shape. The
    // default corner is always correct, so there is nothing to recover.
    return null
  }
}

/* A remembered point can be off-screen after a resize or a rotation, which would
   hide the tray completely with no way to get it back. */
function onScreen(point: Point): boolean {
  return (
    point.x >= 0 &&
    point.y >= 0 &&
    point.x < window.innerWidth - 80 &&
    point.y < window.innerHeight - 40
  )
}

export default function AgentTray() {
  const { rows, clear, busy } = useTrayRows()
  const [collapsed, setCollapsed] = useState(false)
  const [position, setPosition] = useState<Point | null>(null)
  const [wide, setWide] = useState(isWide)

  useEffect(() => {
    const stored = readPosition()
    if (stored && isWide() && onScreen(stored)) setPosition(stored)
  }, [])

  /* The layout is state, not a question asked once while rendering. `canDrag()` was
     called during render and never again, so a popup dragged on a wide window kept
     those coordinates when the window was narrowed - and they were off-screen. The
     bottom bar appeared, the popup did not, and it had been rendering the whole
     time just outside the viewport.

     Below the breakpoint the stylesheet owns the position and the stored point is
     ignored rather than forgotten, so widening again puts it back where it was
     left. Above it, a point that stops fitting after a resize falls back to the
     docked corner instead of disappearing. */
  useEffect(() => {
    const query = window.matchMedia(WIDE)
    const onChange = () => {
      setWide(query.matches)
      if (query.matches) setPosition((current) => (current && !onScreen(current) ? null : current))
    }
    query.addEventListener('change', onChange)
    window.addEventListener('resize', onChange)
    return () => {
      query.removeEventListener('change', onChange)
      window.removeEventListener('resize', onChange)
    }
  }, [])

  /* Dragging, on pointer events so a mouse and a trackpad behave the same. The
     offset is captured on grab so the panel does not jump to centre on the cursor. */
  const dragging = useRef<Point | null>(null)
  const onPointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!isWide()) return

    /* Not when the press landed on a control. `setPointerCapture` sends every
       later pointer event for this gesture to the capturing element - and the
       click with them - so capturing here swallowed the collapse and close
       buttons entirely: they sit inside the grip, and neither ever fired. */
    if ((event.target as HTMLElement).closest('button')) return

    const box = event.currentTarget.parentElement?.getBoundingClientRect()
    if (!box) return
    dragging.current = { x: event.clientX - box.left, y: event.clientY - box.top }
    event.currentTarget.setPointerCapture(event.pointerId)
  }, [])

  const onPointerMove = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const grab = dragging.current
    if (!grab) return
    setPosition({ x: event.clientX - grab.x, y: event.clientY - grab.y })
  }, [])

  const onPointerUp = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return
    dragging.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    setPosition((current) => {
      if (current) {
        try {
          localStorage.setItem(POSITION_KEY, JSON.stringify(current))
        } catch {
          // Not worth failing a drag over. It reopens in the default corner.
        }
      }
      return current
    })
  }, [])

  if (rows.length === 0) return null

  /* Physical `left`/`top`, not the logical properties the stylesheet uses for the
     resting corner. `<html dir="rtl">`, so `inset-inline-start` is the RIGHT edge
     while `clientX` counts from the left - setting one from the other sent the
     panel the opposite way across the screen on every drag. The resting position
     stays logical, because there it should follow the writing direction. */
  // Only the wide layout honours a dragged position. Narrow, the popup docks above
  // the bottom bar and nothing inline competes with the stylesheet.
  const placed = wide ? position : null
  const style = placed ? { left: `${placed.x}px`, top: `${placed.y}px` } : undefined
  const dragged = placed ? ' is-dragged' : ''

  if (collapsed) {
    return (
      <button
        type="button"
        className={`pc-tray-pill${dragged}`}
        style={style}
        onClick={() => setCollapsed(false)}
        aria-label={busy ? `${rows.length} פעולות סוכן, אחת או יותר פעילות` : `${rows.length} פעולות סוכן הסתיימו`}
      >
        {busy ? <span className="pc-tray-spinner" aria-hidden="true" /> : <span aria-hidden="true">✓</span>}
        <span>{rows.length}</span>
      </button>
    )
  }

  return (
    <section className={`pc-tray${dragged}`} style={style} aria-label="פעולות הסוכנים" role="status">
      <div
        className={`pc-tray-grip${wide ? ' is-draggable' : ''}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <span className="pc-tray-title">סוכנים</span>
        <button
          type="button"
          className="pc-tray-ctrl"
          onClick={() => setCollapsed(true)}
          aria-label="כיווץ"
        >
          –
        </button>
        {/* Closable only once nothing is running: a panel you can dismiss mid-run
            is a panel that stops telling you what you asked it to tell you. */}
        <button
          type="button"
          className="pc-tray-ctrl"
          onClick={clear}
          disabled={busy}
          aria-label={busy ? 'אי אפשר לסגור בזמן שסוכן פועל' : 'סגירה'}
          title={busy ? 'אי אפשר לסגור בזמן שסוכן פועל' : undefined}
        >
          ×
        </button>
      </div>

      <ul className="pc-tray-list">
        {rows.map((row) => (
          <TrayLine key={row.id} row={row} />
        ))}
      </ul>
    </section>
  )
}

function TrayLine({ row }: { row: TrayRow }) {
  // The plant's name, from the list the app already holds. Knowledge runs carry no
  // plant - they belong to a species - so that row names the agent alone.
  const { data: plants } = usePlants()
  const plant = row.plantId ? plants?.find((entry) => entry.id === row.plantId) : undefined
  const name = plant ? plantName(plant) : null

  const running = row.status === 'QUEUED' || row.status === 'PROCESSING'
  const failed = row.status === 'FAILED' || row.status === 'CANCELLED'
  const label = AGENT_NAMES[row.agentType] ?? row.agentType

  const body = (
    <>
      <span className={`pc-tray-mark${failed ? ' is-failed' : ''}${running ? '' : ' is-done'}`}>
        {running ? <span className="pc-tray-spinner" aria-hidden="true" /> : failed ? '✗' : '✓'}
      </span>
      <span className="pc-tray-label">{label}</span>
      {name && <span className="pc-tray-plant">{name}</span>}
    </>
  )

  /* Knowledge belongs to a species, not a plant, and there is no species screen to
     send anyone to. Rendered as plain text rather than as a button that does
     nothing - an inert button is indistinguishable from a broken one, which is
     exactly how it was read the first time this ran. */
  if (!row.plantId) {
    return (
      <li className="pc-tray-row is-static" title="מחקר על המין - אין מסך לפתוח">
        {body}
      </li>
    )
  }

  /* A real link, not a button calling `navigate`. This is navigation, so it should
     be an anchor: it survives anything that swallows a synthetic click, it shows
     its destination on hover, and it can be opened in a new tab. The button
     version did nothing when pressed and gave no way to see why. */
  return (
    <li>
      <Link className="pc-tray-row is-link" to={`/plants/${row.plantId}`}>
        {body}
      </Link>
    </li>
  )
}
