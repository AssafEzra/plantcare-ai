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
import { useNavigate } from 'react-router-dom'
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

/* Desktop only. On a phone the tray sits above the bottom bar: there is no room
   worth dragging it around in, and a draggable overlay fights the scroll. */
function canDrag(): boolean {
  return window.matchMedia?.('(min-width: 900px)').matches ?? false
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
  const navigate = useNavigate()

  useEffect(() => {
    if (!canDrag()) return
    const stored = readPosition()
    if (stored && onScreen(stored)) setPosition(stored)
  }, [])

  /* Dragging, on pointer events so a mouse and a trackpad behave the same. The
     offset is captured on grab so the panel does not jump to centre on the cursor. */
  const dragging = useRef<Point | null>(null)
  const onPointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!canDrag()) return
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

  const onPointerUp = useCallback(() => {
    if (!dragging.current) return
    dragging.current = null
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

  const style = position ? { insetInlineStart: `${position.x}px`, insetBlockStart: `${position.y}px`, insetInlineEnd: 'auto', insetBlockEnd: 'auto' } : undefined

  if (collapsed) {
    return (
      <button
        type="button"
        className="pc-tray-pill"
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
    <section className="pc-tray" style={style} aria-label="פעולות הסוכנים" role="status">
      <div
        className={`pc-tray-grip${canDrag() ? ' is-draggable' : ''}`}
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
          <TrayLine key={row.id} row={row} onOpen={(to) => navigate(to)} />
        ))}
      </ul>
    </section>
  )
}

function TrayLine({ row, onOpen }: { row: TrayRow; onOpen: (to: string) => void }) {
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

  if (!row.plantId) {
    return <li className="pc-tray-row">{body}</li>
  }

  return (
    <li>
      <button type="button" className="pc-tray-row is-link" onClick={() => onOpen(`/plants/${row.plantId}`)}>
        {body}
      </button>
    </li>
  )
}
