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

/* How long a finger must stay still on a card before the card is picked up.
 *
 * A touch that starts on a card is also how the page is scrolled, and the two cannot
 * both win: claim the gesture immediately and the list becomes impossible to scroll,
 * never claim it and the card cannot be dragged. The hold is what separates them, and
 * it is the same thing a phone's home screen does.
 *
 * 650ms. Long enough that scrolling never picks a card up by accident, short enough
 * that someone who meant to move one is not left wondering whether it is broken. A
 * mouse has no such ambiguity, so it skips the wait entirely. */
const LONG_PRESS_MS = 650

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
    /** Whether the card has been picked up. False while a hold is still being waited for. */
    armed: boolean
    /** A mouse arms at once; a finger has to hold. Also decides whether a release counts
        as a tap, because holding a card and letting go is not a request to open it. */
    immediate: boolean
    timer: number | null
    surface: HTMLElement | null
    pointerId: number
    /** Where the card would land, as of the last move.
     *
     * The same thing `drag` holds, kept here as well because the release has to read
     * it synchronously. `setDrag` schedules a render rather than assigning, so a
     * pointerup arriving in the same task as the last pointermove saw the *previous*
     * target - the card landed one slot behind where it was dropped, every time the
     * drag ended promptly. State drives the marker; this drives the reorder. */
    landing: { overId: string | null; side: 'before' | 'after' } | null
  } | null>(null)

  /* Set when a gesture turns out to have been a drag, read by the click that the
     browser fires afterwards. The card is an anchor, so without this every drag would
     also open the plant it just moved. */
  const swallowClick = useRef(false)

  /* Held while a card is up, and only then.
     `touch-action: none` cannot do this job: the value is read when the touch begins,
     and at that moment we do not yet know whether this is a scroll or a pick-up - that
     is the whole point of the hold. Setting it later has no effect on a gesture already
     under way, so the scroll is refused here instead, where it can be decided late. */
  const scrollLock = useRef<((event: TouchEvent) => void) | null>(null)

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

  function lockScroll() {
    if (scrollLock.current) return
    const refuse = (event: TouchEvent) => event.preventDefault()
    scrollLock.current = refuse
    document.addEventListener('touchmove', refuse, { passive: false })
  }

  function unlockScroll() {
    if (!scrollLock.current) return
    document.removeEventListener('touchmove', scrollLock.current)
    scrollLock.current = null
  }

  /** Give up on a gesture that turned out to be something else - usually a scroll. */
  function abandon() {
    const held = gesture.current
    if (!held) return
    if (held.timer !== null) window.clearTimeout(held.timer)
    if (held.node) held.node.style.transform = ''
    try {
      held.surface?.releasePointerCapture(held.pointerId)
    } catch {
      // The capture may never have been taken.
    }
    gesture.current = null
    unlockScroll()
    setDrag(null)
  }

  /* Claim the rest of the gesture.
   *
   * Deliberately not done at pointerdown for a card. While a pointer is captured the
   * browser fires the resulting `click` at the capture element rather than at what was
   * under the pointer - and what is under the pointer is the anchor that opens the
   * plant. Capturing early therefore swallowed every tap: the card could be dragged
   * and could no longer be opened. Taken once the gesture is known to be a drag, by
   * which point there is no click left to protect. */
  function takeCapture(held: NonNullable<typeof gesture.current>) {
    try {
      held.surface?.setPointerCapture(held.pointerId)
    } catch {
      /* `setPointerCapture` throws for a pointer the browser no longer considers
         active. The capture is an improvement to the gesture, not a precondition for
         it: without it the drag still works while the pointer is over the page. */
    }
  }

  function hold(
    event: React.PointerEvent<HTMLElement>,
    id: string,
    immediate: boolean,
    captureNow: boolean,
  ) {
    /* A fresh gesture, so whatever the last one decided about clicks is spent. Cleared
       here rather than in the click handler, because a drag that ends outside the page
       never produces the click that would have cleared it. */
    swallowClick.current = false

    const started = {
      id,
      startX: event.clientX,
      startY: event.clientY,
      node: slotOf(id),
      moved: false,
      /* A mouse knows at once that it is dragging, so it can measure now. A finger
         must not: the page may scroll under it before the hold completes, and rects
         taken before that would all be stale. */
      targets: immediate ? measureTargets(id) : [],
      armed: immediate,
      immediate,
      timer: null as number | null,
      surface: event.currentTarget,
      pointerId: event.pointerId,
      landing: null,
    }
    gesture.current = started

    if (!immediate) {
      started.timer = window.setTimeout(() => {
        const held = gesture.current
        if (!held) return
        held.timer = null
        held.armed = true
        held.targets = measureTargets(held.id)
        lockScroll()
        takeCapture(held)
        /* The card visibly lifts the moment it is picked up, before it has moved at
           all. Without it the hold is invisible and indistinguishable from a tap that
           did not register, which is what made the first handle-less attempt feel
           broken. */
        setDrag({ id: held.id, overId: null, side: 'before' })
      }, LONG_PRESS_MS)
    }

    /* Recorded before the capture is asked for, not after: that exception used to
       leave the gesture unrecorded, so every later move was ignored and the drag
       silently did nothing at all. */
    if (captureNow) takeCapture(started)
  }

  /** The list's handle: a dedicated control, so there is nothing to disambiguate. */
  function startDrag(event: React.PointerEvent<HTMLElement>, id: string) {
    event.preventDefault()
    hold(event, id, true, true)
  }

  /** A card in the grid, where the same press might be a tap, a scroll or a drag. */
  function pressCard(event: React.PointerEvent<HTMLElement>, id: string) {
    if (!reorderable || view === 'list') return
    // Secondary buttons open menus and must not start anything.
    if (event.pointerType === 'mouse' && event.button !== 0) return
    hold(event, id, event.pointerType === 'mouse', false)
  }

  function onDragMove(event: React.PointerEvent<HTMLElement>) {
    const held = gesture.current
    if (!held) return

    const dx = event.clientX - held.startX
    const dy = event.clientY - held.startY

    /* The hold has not completed yet, and the finger has set off. It was going
       somewhere - scrolling the list, almost always - so the card is put down and the
       page is left to do what it was already doing. */
    if (!held.armed) {
      if (Math.hypot(dx, dy) >= SLOP_PX) abandon()
      return
    }

    if (!held.moved) {
      if (Math.hypot(dx, dy) < SLOP_PX) return
      held.moved = true
      // Now it is unambiguously a drag, so the rest of the gesture is ours.
      takeCapture(held)
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
      held.landing = null
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

    held.landing = { overId: over.id, side }
    setDrag((current) =>
      current && current.overId === over.id && current.side === side
        ? current
        : { id: held.id, overId: over.id, side },
    )
  }

  /* No event parameter: the capture is released through the element it was taken on,
     which the gesture already holds, and a release can also arrive from a path that
     has no event to hand. */
  function endDrag() {
    const held = gesture.current
    if (!held) return

    if (held.timer !== null) window.clearTimeout(held.timer)
    try {
      held.surface?.releasePointerCapture(held.pointerId)
    } catch {
      // The capture may never have been taken; see `takeCapture`.
    }
    if (held.node) held.node.style.transform = ''
    gesture.current = null
    unlockScroll()

    const landing = held.landing
    setDrag(null)

    /* A card that was picked up does not open when it is put down, even if it landed
       exactly where it started. The press asked for the plant to be moved, and
       answering that with a navigation is what would make the gesture feel unsafe to
       use. A mouse is excluded: there a press is a click until it travels. */
    if (held.moved || (held.armed && !held.immediate)) swallowClick.current = true

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

  /* Where the gesture lives in each view.
   *
   * The list keeps the `‹ ⠿ ›` cluster: it is a row with room beside the text, and the
   * two arrows are the only way to reorder without a pointer at all - by keyboard, or
   * by a screen reader that never knows where anything is on screen. Deleting them
   * everywhere would have made the feature pointer-only.
   *
   * The grid has no such room. The cluster sat on the photograph in the same corner as
   * the health badge and covered it, worst at phone widths where a card is half a
   * screen wide and `דורש תשומת לב` is most of its top edge. So in the grid the card
   * itself is the handle, and the corner goes back to saying what state the plant is
   * in. */
  const byCard = reorderable && view !== 'list'

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
              byCard ? 'is-arrangeable' : '',
              held ? 'is-dragging' : '',
              target ? `is-drop is-drop-${drag?.side}` : '',
            ]
              .filter(Boolean)
              .join(' ')}
            data-plant-id={plant.id}
            {...(byCard
              ? {
                  onPointerDown: (event: React.PointerEvent<HTMLDivElement>) =>
                    pressCard(event, plant.id),
                  onPointerMove: onDragMove,
                  onPointerUp: endDrag,
                  // Not `endDrag`: a cancel is the browser taking the gesture away,
                  // which is not a drop and must not reorder anything.
                  onPointerCancel: abandon,
                  // The card is an anchor, and a browser offers to drag a link.
                  onDragStart: (event: React.DragEvent) => event.preventDefault(),
                  // A long press is also how a phone asks for the link menu.
                  onContextMenu: (event: React.MouseEvent) => {
                    if (gesture.current) event.preventDefault()
                  },
                  onClickCapture: (event: React.MouseEvent) => {
                    if (!swallowClick.current) return
                    swallowClick.current = false
                    event.preventDefault()
                    event.stopPropagation()
                  },
                }
              : {})}
          >
            <PlantCard plant={plant} index={i} />

            {reorderable && view === 'list' && (
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
