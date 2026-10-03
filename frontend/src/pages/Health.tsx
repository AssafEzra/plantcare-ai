/* בריאות — what the last check found, per plant.
 *
 * §11 puts Health in the primary navigation but never says what the screen is; §21
 * places the health *check* on the plant dashboard, and §12 bars a health action from
 * the day's work. The user settled it: this tab lists the plants whose health needs
 * looking at, worst first.
 *
 * It used to list them as plant tiles — the same card the collection draws, which said
 * a name, a photograph and a status chip. Everything that makes this screen worth
 * opening was one navigation away: what the last check actually found, when it ran,
 * and what the checks before it concluded. All of that is on the card now, and every
 * date opens the assessment in full over the list.
 *
 * It still starts no check of its own. The check belongs to the plant dashboard, where
 * the plant's photographs are, so "בדיקה חדשה" is a link that opens it there.
 */

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { usePlants, plantName, type Plant } from '../api/plants'
import { useHealthOverview, type PlantHealthOverview } from '../api/health'
import { STATUS_SEVERITY } from '../lib/status'
import HealthPlantCard from '../components/HealthPlantCard'
import HealthAssessmentDialog from '../components/HealthAssessmentDialog'
import Async from '../components/Async'
import PageHero from '../components/PageHero'
import '../components/HealthPlantCard.css'

export default function Health() {
  const query = usePlants()
  const overview = useHealthOverview()

  /* Which assessment is open, and whose. The plant's name goes in the dialog title:
     this list holds several, and a check with no plant on it is a check about nothing
     in particular. */
  const [open, setOpen] = useState<{ id: string; plant: string } | null>(null)

  const byPlant = useMemo(() => {
    const map = new Map<string, PlantHealthOverview>()
    for (const entry of overview.data ?? []) map.set(entry.plant_id, entry)
    return map
  }, [overview.data])

  /* One request, filtered here rather than three calls with health_status=. The
     endpoint takes a single value, and "needs attention" is two of them plus the
     unknowns worth chasing. */
  /* Both cuts depend on `query.data`, not on a local `?? []` — that default builds a
     new array every render and the memo would never hold. */
  const needing = useMemo(
    () =>
      (query.data ?? [])
        .filter(
          (p) =>
            p.status === 'ACTIVE' &&
            (p.current_health_status === 'CRITICAL' ||
              p.current_health_status === 'NEEDS_ATTENTION'),
        )
        .sort(
          (a, b) =>
            (STATUS_SEVERITY[a.current_health_status] ?? 9) -
            (STATUS_SEVERITY[b.current_health_status] ?? 9),
        ),
    [query.data],
  )

  const unassessed = useMemo(
    () =>
      (query.data ?? []).filter(
        (p) => p.status === 'ACTIVE' && p.current_health_status === 'UNKNOWN',
      ),
    [query.data],
  )

  const total = query.data?.length ?? 0

  const card = (plant: Plant) => (
    <HealthPlantCard
      key={plant.id}
      plant={plant}
      health={byPlant.get(plant.id)}
      onOpenAssessment={(id) => setOpen({ id, plant: plantName(plant) })}
    />
  )

  return (
    <section>
      <PageHero
        eyebrow="מה צריך מבט"
        title="בריאות"
        count={needing.length + unassessed.length}
        subtitle={
          needing.length > 0
            ? `${needing.length} צמחים דורשים תשומת לב`
            : 'אין כרגע צמח שדורש טיפול'
        }
      />

      <Async
        query={query}
        empty={needing.length === 0 && unassessed.length === 0}
        emptyState={
          total === 0 ? (
            <div className="pc-empty">
              <span className="pc-emptyart" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 21v-8" />
                  <path d="M12 13c0-3.5 2.4-6.4 5.8-7-.3 3.7-2.7 6.4-5.8 7z" />
                  <path d="M12 15c0-3-2-5.6-5-6.2.3 3.2 2.3 5.6 5 6.2z" />
                </svg>
              </span>
              <p>עוד לא הוספתם צמחים.</p>
              <Link to="/plants/new" className="pc-btn">
                הוספת צמח
              </Link>
            </div>
          ) : (
            <div className="pc-empty">
              <span className="pc-emptyart" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 12.5l5 5L20 6.5" />
                </svg>
              </span>
              <p>כל הצמחים במצב תקין. אין מה לטפל כרגע.</p>
            </div>
          )
        }
      >
        <>
          {needing.length > 0 && (
            <>
              <div className="pc-sectionhead">
                <div>
                  <span className="pc-eyebrow">הדחוף ביותר קודם</span>
                  <h2>
                    דורשים תשומת לב <span className="pc-countpill">{needing.length}</span>
                  </h2>
                </div>
              </div>
              <div className="pc-healthlist">{needing.map(card)}</div>
            </>
          )}

          {unassessed.length > 0 && (
            <>
              <div className="pc-sectionhead">
                <div>
                  <span className="pc-eyebrow">אין עדיין אבחנה</span>
                  <h2>
                    טרם נבדקו <span className="pc-countpill">{unassessed.length}</span>
                  </h2>
                </div>
              </div>
              <div className="pc-healthlist">{unassessed.map(card)}</div>
            </>
          )}
        </>
      </Async>

      {open && (
        <HealthAssessmentDialog
          assessmentId={open.id}
          plantName={open.plant}
          onClose={() => setOpen(null)}
        />
      )}
    </section>
  )
}
