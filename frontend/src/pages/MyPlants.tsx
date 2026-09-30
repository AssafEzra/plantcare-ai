/* My plants (section 13).
 *
 * Active plants by default; archived reachable separately. Search, species filter,
 * health filter and sort.
 *
 * Search and health go to the API, which already accepts `q` and `health_status`.
 * Species and sort are applied here: `/v1/plants` has no parameter for either, and a
 * user's plant list is small enough that a round trip would be slower than the work.
 * Section 13 also requires the species filter to offer "only species that actually
 * exist for the user", which is derived from the loaded rows — so it cannot offer a
 * species that would return nothing.
 */

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { usePlants, plantName, type Plant } from '../api/plants'
import { STATUS_SEVERITY, type HealthStatus } from '../lib/status'
import PlantCard from '../components/PlantCard'
import Async from '../components/Async'
import '../components/PlantCard.css'

type Sort = 'name' | 'created' | 'health'

export default function MyPlants() {
  const [archived, setArchived] = useState(false)
  const [q, setQ] = useState('')
  const [health, setHealth] = useState<HealthStatus | ''>('')
  const [species, setSpecies] = useState('')
  const [sort, setSort] = useState<Sort>('name')

  const query = usePlants({
    status: archived ? 'ARCHIVED' : undefined,
    health_status: health || undefined,
    q: q.trim() || undefined,
  })

  /* Active view means "not archived" rather than "status === ACTIVE": a plant still
     being identified is not archived, and hiding it would lose the one place its
     owner can see what happened to it.

     Depends on `query.data`, not on a local `?? []` — that default builds a new
     array every render and the memo would never hold. */
  const visible = useMemo(() => {
    const all = query.data ?? []
    return archived ? all : all.filter((p) => p.status !== 'ARCHIVED')
  }, [query.data, archived])

  const speciesOptions = useMemo(() => {
    const names = new Set<string>()
    for (const plant of visible) if (plant.species_name) names.add(plant.species_name)
    return [...names].sort((a, b) => a.localeCompare(b, 'he'))
  }, [visible])

  const shown = useMemo(() => {
    const filtered = species ? visible.filter((p) => p.species_name === species) : visible
    return [...filtered].sort(comparator(sort))
  }, [visible, species, sort])

  return (
    <section>
      <header className="pc-pagehead">
        <h1>{archived ? 'צמחים בארכיון' : 'הצמחים שלי'}</h1>
        <Link to="/plants/new" className="pc-btn">
          הוספת צמח
        </Link>
      </header>

      <div className="pc-filters">
        <label className="pc-field pc-filter">
          <span>חיפוש</span>
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="שם צמח או מין"
          />
        </label>

        <label className="pc-field pc-filter">
          <span>מין</span>
          <select value={species} onChange={(e) => setSpecies(e.target.value)}>
            <option value="">כל המינים</option>
            {speciesOptions.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>

        <label className="pc-field pc-filter">
          <span>מצב בריאות</span>
          <select value={health} onChange={(e) => setHealth(e.target.value as HealthStatus | '')}>
            <option value="">הכול</option>
            <option value="HEALTHY">בריא</option>
            <option value="NEEDS_ATTENTION">דורש תשומת לב</option>
            <option value="CRITICAL">מצב קריטי</option>
            <option value="UNKNOWN">לא ידוע</option>
          </select>
        </label>

        <label className="pc-field pc-filter">
          <span>מיון</span>
          <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            <option value="name">שם</option>
            <option value="created">תאריך הוספה</option>
            <option value="health">מצב בריאות</option>
          </select>
        </label>
      </div>

      <Async
        query={query}
        empty={shown.length === 0}
        emptyState={
          archived ? (
            <p>אין צמחים בארכיון.</p>
          ) : hasFilters(q, species, health) ? (
            <p>לא נמצאו צמחים שמתאימים לחיפוש.</p>
          ) : (
            <div className="pc-empty">
              <p>עוד לא הוספתם צמחים.</p>
              <Link to="/plants/new" className="pc-btn">
                הוספת הצמח הראשון
              </Link>
            </div>
          )
        }
      >
        <div className="pc-plantgrid">
          {shown.map((plant) => (
            <PlantCard key={plant.id} plant={plant} />
          ))}
        </div>
      </Async>

      <p className="pc-archivetoggle">
        <button type="button" className="pc-linkbtn" onClick={() => setArchived((v) => !v)}>
          {archived ? 'חזרה לצמחים הפעילים' : 'הצגת צמחים בארכיון'}
        </button>
      </p>
    </section>
  )
}

function hasFilters(q: string, species: string, health: string): boolean {
  return Boolean(q.trim() || species || health)
}

function comparator(sort: Sort): (a: Plant, b: Plant) => number {
  if (sort === 'created') {
    return (a, b) => b.created_at.localeCompare(a.created_at)
  }
  if (sort === 'health') {
    // Worst first: the reason to sort by health is to find what needs doing.
    return (a, b) =>
      (STATUS_SEVERITY[a.current_health_status] ?? 9) -
        (STATUS_SEVERITY[b.current_health_status] ?? 9) ||
      plantName(a).localeCompare(plantName(b), 'he')
  }
  return (a, b) => plantName(a).localeCompare(plantName(b), 'he')
}
