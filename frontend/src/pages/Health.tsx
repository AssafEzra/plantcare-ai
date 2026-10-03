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
import PageHero from '../components/PageHero'
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
          plants.length === 0 ? (
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
              <div className="pc-plantgrid">
                {needing.map((plant, i) => (
                  <PlantCard key={plant.id} plant={plant} index={i} />
                ))}
              </div>
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
              <p className="pc-placeholder-note">
                לצמחים האלה עדיין אין בדיקת בריאות. אפשר להריץ בדיקה מדף הצמח.
              </p>
              <div className="pc-plantgrid">
                {unassessed.map((plant, i) => (
                  <PlantCard key={plant.id} plant={plant} index={i} />
                ))}
              </div>
            </>
          )}
        </>
      </Async>
    </section>
  )
}
