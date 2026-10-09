/* The plants, in the order their owner put them, as cards or as a list.
 *
 * No attribute of a plant knows the order a person wants. The one by the kitchen
 * window that needs watching every day belongs at the top, and name, date added and
 * health status all fail to say so. So the order is the user's, stored per user, and
 * this is where they change it.
 *
 * Ordering is done with buttons, and pointer dragging is added on top. That is the
 * same decision `PlantGallery.tsx` took, for the same reasons: native HTML5 drag and
 * drop does not work by touch at all - which is most of this application's use - and
 * a keyboard user cannot reach it either. The buttons are what make it work
 * everywhere and what a screen reader announces; the drag is what everyone else will
 * actually use.
 *
 * How the drag works, and why it is not the obvious thing
 * -------------------------------------------------------
 * The first version of this reordered the list on every pointer move, as soon as the
 * finger was over a different card. It read as broken, and the reason is worth
 * keeping: moving the dragged card out of its place changes which element is under
 * the finger, which moves it again - so the grid oscillated, and because nothing
 * followed the pointer there was no sense of holding anything, nor any way to tell
 * where it would land.
 *
 * So the order is left alone until the finger lifts. During the drag:
 *
 *  - the dragged card follows the pointer, through a transform written straight to
 *    the node rather than through state. A pointer move fires far more often than a
 *    list of thirty cards can usefully re-render, and this way none of them do.
 *  - the card under the pointer is marked, and shows which side the dragged one
 *    would be inserted on. That is the only thing a move puts into React state, and
 *    it changes a handful of times per drag rather than a hundred.
 *  - on release the list is reordered once and sent.
 *
 * `elementFromPoint` finds the card under the pointer. It is geometry rather than
 * events, so it keeps working while the pointer is captured, and it sidesteps RTL
 * completely: there is no arithmetic on `clientX` to get the wrong way round under
 * `dir="rtl"`.
 *
 * `setPointerCapture` sends the rest of the gesture to the element that captured it,
 * so the handle is its own element with nothing clickable inside - the agent tray
 * lost its close button to exactly this.
 *
 * A reorder is committed as the whole list, because that is what the endpoint takes:
 * a move shifts everything after it, and a partial list would leave the rest at
 * whatever number they had.
 */

import { useRef, useState } from 'react'
import type { Plant } from '../api/plants'
import { plantName } from '../api/plants'
import PlantCard from './PlantCard'
import './PlantArrangement.css'

export type PlantView = 'cards' | 'list'

/** Below this the finger has not really moved and the gesture is a press, not a drag. */
const SLOP_PX = 6

type Drag = {
  id: string
  /** The card the pointer is over, if any. */
  overId: string | null
  /** Whether the dragged card would land before or after the one it is over. */
  side: 'before' | 'after'
}

export default function PlantArrangement({
  plants,
  view,
  reorderable,
  onReorder,
}: {
  plants: Plant[]
  view: PlantView
  /** False while a sort, a filter, the archive or read-only mode is in force. */
  reorderable: boolean
  onReorder: (plantIds: string[]) => void
}) {
  const [drag, setDrag] = useState<Drag | null>(null)

  /* Everything a move needs but no render should depend on. Kept in a ref so a
     pointer move can write the transform and read the start point without putting
     the component through a render it has no use for. */
  const gesture = useRef<{
    id: string
    startX: number
    startY: number
    node: HTMLElement | null
    moved: boolean
    /** Where every *other* card is, in page coordinates, measured once at the start. */
    targets: { id: string; left: number; top: number; right: number; bottom: number }[]
  } | null>(null)

  function commit(next: Plant[]) {
    const before = plants.map((plant) => plant.id).join()
    const after = next.map((plant) => plant.id).join()
    if (before !== after) onReorder(next.map((plant) => plant.id))
  }

  function move(id: string, by: number) {
    const from = plants.findIndex((plant) => plant.id === id)
    const to = from + by
    if (from < 0 || to < 0 || to >= plants.length) return
    const next = [...plants]
    next.splice(to, 0, ...next.splice(from, 1))
    commit(next)
  }

  function slotOf(id: string): HTMLElement | null {
    return document.querySelector<HTMLElement>(`[data-plant-id="${id}"]`)
  }

  /**
   * Where every card except the dragged one sits, in page coordinates.
   *
   * Measured once, at the start of the gesture, and used instead of
   * `elementFromPoint` - which was the first approach and was wrong for a reason
   * worth recording. The dragged card follows the pointer, so its own drag handle
   * ends up directly under the pointer; the hit test then returned the card being
   * dragged on every single move, no target was ever found, and the drop did
   * nothing. Geometry has no such problem, because the dragged card is simply not
   * in the list.
   *
   * Page rather than viewport coordinates so that scrolling mid-drag does not
   * silently shift every target.
   */
  function measureTargets(dragging: string) {
    return [...document.querySelectorAll<HTMLElement>('[data-plant-id]')]
      .filter((node) => node.dataset.plantId && node.dataset.plantId !== dragging)
      .map((node) => {
        const box = node.getBoundingClientRect()
        return {
          id: node.dataset.plantId as string,
          left: box.left + window.scrollX,
          top: box.top + window.scrollY,
          right: box.right + window.scrollX,
          bottom: box.bottom + window.scrollY,
        }
      })
  }

  function startDrag(event: React.PointerEvent<HTMLButtonElement>, id: string) {
    event.preventDefault()

    /* Recorded before the capture is asked for, not after. `setPointerCapture`
       throws for a pointer the browser does not consider active, and with the two
       the other way round that exception left the gesture unrecorded - so every
       later move was ignored and the drag silently did nothing at all. The capture
       is an improvement to the gesture, not a precondition for it: without it the
       drag still works as long as the pointer stays over the page. */
    gesture.current = {
      id,
      startX: event.clientX,
      startY: event.clientY,
      node: slotOf(id),
      moved: false,
      targets: measureTargets(id),
    }

    try {
      event.currentTarget.setPointerCapture(event.pointerId)
    } catch {
      // Not fatal; see above.
    }
  }

  function onDragMove(event: React.PointerEvent<HTMLButtonElement>) {
    const held = gesture.current
    if (!held) return

    const dx = event.clientX - held.startX
    const dy = event.clientY - held.startY

    if (!held.moved) {
      if (Math.hypot(dx, dy) < SLOP_PX) return
      held.moved = true
    }

    /* Physical `translate`, not a logical offset, and written straight to the node.
       `clientX` counts from the left of the viewport whatever the writing
       direction, so this is one of the few places in the application where the
       physical axis is the correct one. */
    if (held.node) held.node.style.transform = `translate(${dx}px, ${dy}px)`

    const x = event.clientX + window.scrollX
    const y = event.clientY + window.scrollY
    const over = held.targets.find(
      (box) => x >= box.left && x <= box.right && y >= box.top && y <= box.bottom,
    )

    /* Rebuilt from the gesture rather than spread over whatever is in state. The
       first move of a drag runs before any `setDrag` has landed, so a spread of the
       previous value produced an object with no `id` at all - nothing rendered as
       being dragged, and the release found nothing to move. */
    if (!over) {
      setDrag((current) =>
        current && current.overId === null ? current : { id: held.id, overId: null, side: 'before' },
      )
      return
    }

    /* Which half of the card the pointer is in decides the side, measured along
       whichever axis separates this card from its neighbours: the list is one
       column, so the halves are top and bottom, while the grid puts cards side by
       side and the halves are left and right. */
    const wide = over.right - over.left > over.bottom - over.top
    const side: Drag['side'] =
      view === 'list' || wide
        ? y < (over.top + over.bottom) / 2
          ? 'before'
          : 'after'
        : // Right-to-left: the half nearer the right edge comes first.
          x > (over.left + over.right) / 2
          ? 'before'
          : 'after'

    setDrag((current) =>
      current && current.overId === over.id && current.side === side
        ? current
        : { id: held.id, overId: over.id, side },
    )
  }

  function endDrag(event: React.PointerEvent<HTMLButtonElement>) {
    const held = gesture.current
    if (!held) return

    try {
      event.currentTarget.releasePointerCapture(event.pointerId)
    } catch {
      // The capture may never have been taken; see `startDrag`.
    }
    if (held.node) held.node.style.transform = ''
    gesture.current = null

    const landing = drag
    setDrag(null)

    if (!held.moved || !landing?.overId) return

    const from = plants.findIndex((plant) => plant.id === held.id)
    const onto = plants.findIndex((plant) => plant.id === landing.overId)
    if (from < 0 || onto < 0) return

    const next = [...plants]
    const [moving] = next.splice(from, 1)
    /* The target's index after the removal, which is one lower when the card came
       from above it. Getting this wrong is an off-by-one that drops the card on the
       far side of where the marker was. */
    const base = onto - (from < onto ? 1 : 0)
    next.splice(landing.side === 'before' ? base : base + 1, 0, moving)

    commit(next)
  }

  return (
    <div
      className={`pc-plantgrid${view === 'list' ? ' pc-plantgrid-list' : ''}${
        drag ? ' is-arranging' : ''
      }`}
    >
      {plants.map((plant, i) => {
        const held = drag?.id === plant.id
        const target = drag?.overId === plant.id
        return (
          <div
            key={plant.id}
            className={[
              'pc-plantslot',
              held ? 'is-dragging' : '',
              target ? `is-drop is-drop-${drag?.side}` : '',
            ]
              .filter(Boolean)
              .join(' ')}
            data-plant-id={plant.id}
          >
            <PlantCard plant={plant} index={i} />

            {reorderable && (
              <div className="pc-plantmove" role="group" aria-label={`מקום של ${plantName(plant)}`}>
                <button
                  type="button"
                  className="pc-plantmove-btn"
                  aria-label={`הזזת ${plantName(plant)} אחורה`}
                  disabled={i === 0}
                  onClick={() => move(plant.id, -1)}
                >
                  ‹
                </button>

                {/* The handle. Its own element with nothing inside it, because the
                    pointer capture would swallow a click on anything it contained.
                    `touch-action: none` in the stylesheet is what stops a touch drag
                    scrolling the page instead of moving the plant. */}
                <button
                  type="button"
                  className="pc-planthandle"
                  aria-label={`גרירת ${plantName(plant)}`}
                  onPointerDown={(event) => startDrag(event, plant.id)}
                  onPointerMove={onDragMove}
                  onPointerUp={endDrag}
                  onPointerCancel={endDrag}
                >
                  <span aria-hidden="true">⠿</span>
                </button>

                <button
                  type="button"
                  className="pc-plantmove-btn"
                  aria-label={`הזזת ${plantName(plant)} קדימה`}
                  disabled={i === plants.length - 1}
                  onClick={() => move(plant.id, 1)}
                >
                  ›
                </button>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
