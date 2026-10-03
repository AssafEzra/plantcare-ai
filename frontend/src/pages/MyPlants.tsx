/* My plants (section 13).
 *
 * Active plants by default; archived reachable separately. Search, species filter,
 * health filter and sort.
 *
 * Search goes to the API, which already accepts `q`. Species, sort and the health
 * filter are applied here: `/v1/plants` has no parameter for species or sort, and a
 * user's plant list is small enough that a round trip would be slower than the work.
 *
 * Health moved client-side when it became a row of chips and a row of counted stats.
 * Asking the server for one status returns only that status, so every other count
 * would read zero the moment a filter was on — the page would lie about what is there,
 * and a count you cannot trust is worse than no count. Section 13 already requires the
 * species filter to offer "only species that actually exist for the user", derived
 * from the loaded rows; the health filter now follows the same rule.
 *
 * `Filter` is deliberately wider than `HealthStatus`. The stat row offers two cuts that
 * are not a single health value — everything needing attention, and everything due
 * today — and a stat the reader cannot act on is decoration.
 */

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { usePlants, plantName, type Plant } from '../api/plants'
import { STATUS_SEVERITY, statusStyle, type HealthStatus } from '../lib/status'
import { dayOffset } from '../lib/dates'
import PlantCard from '../components/PlantCard'
import Async from '../components/Async'
import PageHero from '../components/PageHero'
import { useIsReadOnly } from '../lib/viewAs'
import '../components/PlantCard.css'
import './MyPlants.css'

type Sort = 'name' | 'created' | 'health'
type Filter = '' | HealthStatus | 'ATTENTION' | 'DUE_TODAY' | 'PENDING'

const HEALTH_ORDER: HealthStatus[] = ['CRITICAL', 'NEEDS_ATTENTION', 'UNKNOWN', 'HEALTHY']

const FILTER_LABELS: Record<string, string> = {
  ATTENTION: 'דורשים תשומת לב',
  DUE_TODAY: 'טיפול להיום',
  PENDING: 'ממתינים לזיהוי',
}

export default function MyPlants() {
  const [archived, setArchived] = useState(false)
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState<Filter>('')
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

  /* Counted before any filter is applied, so every number says how many it would show
     rather than how many are showing. */
  const counts = useMemo(() => {
    const byStatus = new Map<string, number>()
    let dueToday = 0
    let pending = 0
    for (const plant of visible) {
      const key = plant.status === 'ACTIVE' ? plant.current_health_status : 'UNKNOWN'
      byStatus.set(key, (byStatus.get(key) ?? 0) + 1)
      if (isDueToday(plant)) dueToday += 1
      if (isPending(plant)) pending += 1
    }
    return {
      byStatus,
      dueToday,
      pending,
      healthy: byStatus.get('HEALTHY') ?? 0,
      attention: (byStatus.get('CRITICAL') ?? 0) + (byStatus.get('NEEDS_ATTENTION') ?? 0),
    }
  }, [visible])

  const shown = useMemo(() => {
    let filtered = visible
    if (species) filtered = filtered.filter((p) => p.species_name === species)
    if (filter) filtered = filtered.filter((p) => matches(p, filter))
    return [...filtered].sort(comparator(sort))
  }, [visible, species, filter, sort])

  const stats: { key: Filter; caption: string; value: number; unit: string; tone: string }[] = [
    { key: 'HEALTHY', caption: 'במצב תקין', value: counts.healthy, unit: 'צמחים', tone: 'success' },
    { key: 'ATTENTION', caption: 'דורשים תשומת לב', value: counts.attention, unit: 'צמחים', tone: 'warning' },
    { key: 'DUE_TODAY', caption: 'טיפולים להיום', value: counts.dueToday, unit: 'משימות', tone: 'primary' },
    { key: 'PENDING', caption: 'ממתינים לזיהוי', value: counts.pending, unit: 'צמחים', tone: 'neutral' },
  ]

  return (
    <section className="pc-myplants">
      <PageHero
        eyebrow={archived ? 'הארכיון' : 'הגינה שלכם'}
        title={archived ? 'צמחים בארכיון' : 'הצמחים שלי'}
        count={visible.length}
        subtitle={summary(visible.length, counts.attention, archived)}
      >
        {!readOnly && !archived && (
          <Link to="/plants/new" className="pc-btn">
            <span aria-hidden="true">+</span> הוספת צמח
          </Link>
        )}
      </PageHero>

      {!archived && (
        <div className="pc-statrow">
          {stats.map((stat) => (
            <button
              key={stat.key}
              type="button"
              className={`pc-stat pc-stat-${stat.tone}${filter === stat.key ? ' is-on' : ''}`}
              aria-pressed={filter === stat.key}
              onClick={() => setFilter(filter === stat.key ? '' : stat.key)}
              disabled={stat.value === 0}
            >
              <span className="pc-statcaption">{stat.caption}</span>
              <span className="pc-statvalue">
                {stat.value}
                <span className="pc-statunit">{stat.unit}</span>
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="pc-plantbar">
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

      <div className="pc-chiprow" role="group" aria-label="סינון לפי מצב בריאות">
        <button
          type="button"
          className={`pc-chip${filter === '' ? ' is-on' : ''}`}
          aria-pressed={filter === ''}
          onClick={() => setFilter('')}
        >
          הכול
          <span className="pc-chipcount">{visible.length}</span>
        </button>

        {HEALTH_ORDER.map((status) => {
          const count = counts.byStatus.get(status) ?? 0
          if (count === 0) return null
          const style = statusStyle(status)
          return (
            <button
              key={status}
              type="button"
              className={`pc-chip pc-chip-${style.tone}${filter === status ? ' is-on' : ''}`}
              aria-pressed={filter === status}
              onClick={() => setFilter(filter === status ? '' : status)}
            >
              <span aria-hidden="true">{style.glyph}</span>
              {style.label}
              <span className="pc-chipcount">{count}</span>
            </button>
          )
        })}
      </div>

      {/* The stat row can set a cut the chips cannot show as selected, so the page says
          out loud what it is filtered by rather than leaving the reader to wonder why
          six of ten plants are missing. */}
      {FILTER_LABELS[filter] && (
        <p className="pc-activefilter">
          מוצגים: {FILTER_LABELS[filter]}
          <button type="button" className="pc-linkbtn" onClick={() => setFilter('')}>
            ניקוי
          </button>
        </p>
      )}

      <Async
        query={query}
        empty={shown.length === 0}
        emptyState={
          archived ? (
            <p>אין צמחים בארכיון.</p>
          ) : hasFilters(q, species, filter) ? (
            <div className="pc-empty">
              <p>לא נמצאו צמחים שמתאימים לחיפוש.</p>
              <button
                type="button"
                className="pc-btn pc-btn-quiet"
                onClick={() => {
                  setQ('')
                  setSpecies('')
                  setFilter('')
                }}
              >
                ניקוי הסינון
              </button>
            </div>
          ) : (
            <div className="pc-empty">
              <span className="pc-emptyart" aria-hidden="true">
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
  if (archived) return 'צמחים שהוצאו מהמעקב'
  if (total === 0) return 'הגינה שלכם מחכה לצמח הראשון'
  if (needing === 0) return 'כל הצמחים במצב תקין'
  return `${needing} מהם דורשים תשומת לב`
}

/** Overdue counts as due today: it is work waiting now, not work that was missed. */
function isDueToday(plant: Plant): boolean {
  if (!plant.next_task) return false
  if (plant.next_task.status === 'OVERDUE') return true
  return dayOffset(plant.next_task.due_at_utc) <= 0
}

function isPending(plant: Plant): boolean {
  return plant.status !== 'ACTIVE' || plant.awaiting_confirmation
}

function matches(plant: Plant, filter: Filter): boolean {
  if (filter === 'DUE_TODAY') return isDueToday(plant)
  if (filter === 'PENDING') return isPending(plant)
  if (filter === 'ATTENTION') {
    return (
      plant.status === 'ACTIVE' &&
      (plant.current_health_status === 'CRITICAL' ||
        plant.current_health_status === 'NEEDS_ATTENTION')
    )
  }
  return plant.status === 'ACTIVE'
    ? plant.current_health_status === filter
    : filter === 'UNKNOWN'
}

function hasFilters(q: string, species: string, filter: Filter): boolean {
  return Boolean(q.trim() || species || filter)
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
