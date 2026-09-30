/* בריאות — plants needing attention.
 *
 * Section 11 puts Health in the primary navigation but never says what the screen
 * is; section 21 places the health *check* on the plant dashboard only, and section
 * 12 bars a health action from Home. The user settled it: this tab lists the plants
 * whose health needs looking at, worst first.
 *
 * It starts no health check and offers no action of its own — the check belongs to
 * the plant dashboard (section 21), so every row here is a way in rather than a
 * shortcut past it.
 */

import { Link } from 'react-router-dom'
import { usePlants } from '../api/plants'
import { STATUS_SEVERITY } from '../lib/status'
import PlantCard from '../components/PlantCard'
import Async from '../components/Async'
import '../components/PlantCard.css'

export default function Health() {
  const query = usePlants()
  const plants = query.data ?? []

  /* One request, filtered here rather than three calls with health_status=. The
     endpoint takes a single value, and "needs attention" is two of them plus the
     unknowns worth chasing. */
  const needing = plants
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
    )

  const unassessed = plants.filter(
    (p) => p.status === 'ACTIVE' && p.current_health_status === 'UNKNOWN',
  )

  return (
    <section>
      <header className="pc-pagehead">
        <h1>בריאות</h1>
      </header>

      <Async
        query={query}
        empty={needing.length === 0 && unassessed.length === 0}
        emptyState={
          plants.length === 0 ? (
            <div className="pc-empty">
              <p>עוד לא הוספתם צמחים.</p>
              <Link to="/plants/new" className="pc-btn">
                הוספת צמח
              </Link>
            </div>
          ) : (
            <p>כל הצמחים במצב תקין. אין מה לטפל כרגע.</p>
          )
        }
      >
        <>
          {needing.length > 0 && (
            <>
              <div className="pc-sectionhead">
                <h2>דורשים תשומת לב</h2>
              </div>
              <div className="pc-plantgrid">
                {needing.map((plant) => (
                  <PlantCard key={plant.id} plant={plant} />
                ))}
              </div>
            </>
          )}

          {unassessed.length > 0 && (
            <>
              <div className="pc-sectionhead">
                <h2>טרם נבדקו</h2>
              </div>
              <p className="pc-placeholder-note">
                לצמחים האלה עדיין אין בדיקת בריאות. אפשר להריץ בדיקה מדף הצמח.
              </p>
              <div className="pc-plantgrid">
                {unassessed.map((plant) => (
                  <PlantCard key={plant.id} plant={plant} />
                ))}
              </div>
            </>
          )}
        </>
      </Async>
    </section>
  )
}
