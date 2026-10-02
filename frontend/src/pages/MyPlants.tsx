/* My plants (section 13).
 *
 * Active plants by default; archived reachable separately. Search, species filter,
 * health filter and sort.
 *
 * Search goes to the API, which already accepts `q`. Species, sort and health are
 * applied here: `/v1/plants` has no parameter for species or sort, and a user's plant
 * list is small enough that a round trip would be slower than the work.
 *
 * Health moved client-side when it became a row of chips carrying counts. Asking the
 * server for one status returns only that status, so every other chip's count would
 * read zero the moment a filter was on — the chips would lie about what is there, and
 * a count you cannot trust is worse than no count. Section 13 also requires the
 * species filter to offer "only species that actually exist for the user", which is
 * derived from the loaded rows, so it cannot offer a species that would return
 * nothing. The health chips now follow the same rule.
 */

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { usePlants, plantName, type Plant } from '../api/plants'
import { STATUS_SEVERITY, statusStyle, type HealthStatus } from '../lib/status'
import PlantCard from '../components/PlantCard'
import Async from '../components/Async'
import { useIsReadOnly } from '../lib/viewAs'
import '../components/PlantCard.css'
import './MyPlants.css'

type Sort = 'name' | 'created' | 'health'

const HEALTH_ORDER: HealthStatus[] = ['CRITICAL', 'NEEDS_ATTENTION', 'UNKNOWN', 'HEALTHY']

export default function MyPlants() {
  const [archived, setArchived] = useState(false)
  const [q, setQ] = useState('')
  const [health, setHealth] = useState<HealthStatus | ''>('')
  const [species, setSpecies] = useState('')
  const [sort, setSort] = useState<Sort>('name')
  const readOnly = useIsReadOnly()

  const query = usePlants({
    status: archived ? 'ARCHIVED' : undefined,
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

  /* Counted before the health filter is applied, so a chip always says how many it
     would show rather than how many are showing. */
  const counts = useMemo(() => {
    const byStatus = new Map<string, number>()
    for (const plant of visible) {
      const key = plant.status === 'ACTIVE' ? plant.current_health_status : 'UNKNOWN'
      byStatus.set(key, (byStatus.get(key) ?? 0) + 1)
    }
    return byStatus
  }, [visible])

  const needingAttention =
    (counts.get('CRITICAL') ?? 0) + (counts.get('NEEDS_ATTENTION') ?? 0)

  const shown = useMemo(() => {
    let filtered = visible
    if (species) filtered = filtered.filter((p) => p.species_name === species)
    if (health) {
      filtered = filtered.filter((p) =>
        p.status === 'ACTIVE' ? p.current_health_status === health : health === 'UNKNOWN',
      )
    }
    return [...filtered].sort(comparator(sort))
  }, [visible, species, health, sort])

  return (
    <section className="pc-myplants">
      <header className="pc-planthero">
        <div className="pc-planthero-text">
          <h1>{archived ? 'צמחים בארכיון' : 'הצמחים שלי'}</h1>
          <p className="pc-planthero-sub">{summary(visible.length, needingAttention, archived)}</p>
        </div>

        {!readOnly && !archived && (
          <Link to="/plants/new" className="pc-btn pc-planthero-add">
            <span aria-hidden="true">+</span> הוספת צמח
          </Link>
        )}

        <label className="pc-plantsearch">
          <span className="pc-sr-only">חיפוש צמח</span>
          <span className="pc-plantsearch-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <circle cx="11" cy="11" r="7" />
              <path d="M20 20l-3.2-3.2" />
            </svg>
          </span>
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="חיפוש לפי שם או מין"
          />
        </label>
      </header>

      <div className="pc-plantcontrols">
        <div className="pc-chiprow" role="group" aria-label="סינון לפי מצב בריאות">
          <button
            type="button"
            className={`pc-chip${health === '' ? ' is-on' : ''}`}
            aria-pressed={health === ''}
            onClick={() => setHealth('')}
          >
            הכול
            <span className="pc-chipcount">{visible.length}</span>
          </button>

          {HEALTH_ORDER.map((status) => {
            const count = counts.get(status) ?? 0
            if (count === 0) return null
            const style = statusStyle(status)
            return (
              <button
                key={status}
                type="button"
                className={`pc-chip pc-chip-${style.tone}${health === status ? ' is-on' : ''}`}
                aria-pressed={health === status}
                onClick={() => setHealth(health === status ? '' : status)}
              >
                <span aria-hidden="true">{style.glyph}</span>
                {style.label}
                <span className="pc-chipcount">{count}</span>
              </button>
            )
          })}
        </div>

        <div className="pc-plantselects">
          {speciesOptions.length > 1 && (
            <label className="pc-field pc-filter">
              <span className="pc-sr-only">מין</span>
              <select value={species} onChange={(e) => setSpecies(e.target.value)}>
                <option value="">כל המינים</option>
                {speciesOptions.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
          )}

          <label className="pc-field pc-filter">
            <span className="pc-sr-only">מיון</span>
            <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
              <option value="name">מיון: שם</option>
              <option value="created">מיון: תאריך הוספה</option>
              <option value="health">מיון: מצב בריאות</option>
            </select>
          </label>
        </div>
      </div>

      <Async
        query={query}
        empty={shown.length === 0}
        emptyState={
          archived ? (
            <p>אין צמחים בארכיון.</p>
          ) : hasFilters(q, species, health) ? (
            <div className="pc-plantempty">
              <p>לא נמצאו צמחים שמתאימים לחיפוש.</p>
              <button
                type="button"
                className="pc-btn pc-btn-quiet"
                onClick={() => {
                  setQ('')
                  setSpecies('')
                  setHealth('')
                }}
              >
                ניקוי הסינון
              </button>
            </div>
          ) : (
            <div className="pc-plantempty">
              <span className="pc-plantempty-art" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 21v-8" />
                  <path d="M12 13c0-3.5 2.4-6.4 5.8-7-.3 3.7-2.7 6.4-5.8 7z" />
                  <path d="M12 15c0-3-2-5.6-5-6.2.3 3.2 2.3 5.6 5 6.2z" />
                </svg>
              </span>
              <p>עוד לא הוספתם צמחים.</p>
              {!readOnly && (
                <Link to="/plants/new" className="pc-btn">
                  הוספת הצמח הראשון
                </Link>
              )}
            </div>
          )
        }
      >
        <div className="pc-plantgrid">
          {shown.map((plant, i) => (
            <PlantCard key={plant.id} plant={plant} index={i} />
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

function summary(total: number, needing: number, archived: boolean): string {
  if (archived) return `${total} צמחים בארכיון`
  if (total === 0) return 'הגינה שלכם מחכה לצמח הראשון'
  const plants = total === 1 ? 'צמח אחד' : `${total} צמחים`
  if (needing === 0) return `${plants} · כולם במצב תקין`
  return `${plants} · ${needing} דורשים תשומת לב`
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
