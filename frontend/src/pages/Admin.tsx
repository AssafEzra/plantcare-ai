/* The admin panel (FINAL section 29).
 *
 * Nine tabs, and the review screen is the one that matters: FINAL section 11 says the
 * Knowledge Agent never publishes, and the drafts tab is the human step that sentence
 * is describing. It is built to make the *weak* parts of a draft findable, because a
 * reviewer with limited time who reads top to bottom will approve the fourteenth
 * section least carefully.
 *
 * Reaching this route requires an ADMIN role, but that is a courtesy: the navigation
 * entry is hidden for other users while every admin route depends on `AdminDep` and
 * every admin table carries its own RLS policy. Hiding UI is never the control.
 *
 * The tab lives in the URL (`?tab=drafts`). An administrator who has just approved
 * something and wants to point a colleague at it should be able to send a link, and a
 * reload should not throw them back to the overview.
 */

import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  useAccounts,
  useAdminDeliveries,
  useAgentExecutions,
  useAgentRequests,
  useAnonymizeAccount,
  useApprovedSources,
  useApproveDraft,
  useAuditLog,
  useCatalogue,
  useCreateSource,
  useDrafts,
  useKnowledgeReports,
  useOverview,
  useRejectDraft,
  useResearchSpecies,
  useRetryDraft,
  useReviewReport,
  useSetSourceEnabled,
  useSpeciesVersions,
  useStartViewAs,
  useVersionDetail,
  type Account,
  type AgentExecution,
  type CatalogueEntry,
  type DraftStatus,
  type KnowledgeDraft,
  type KnowledgeSection,
} from '../api/admin'
import {
  DRAFT_STATUS_LABELS,
  KNOWLEDGE_SECTIONS,
  REPORT_DECISIONS,
  SOURCE_CLASS_LABELS,
  SOURCE_CLASS_ORDER,
  WEAK_SECTION,
} from '../lib/careVocab'
import { formatStamp } from '../lib/dates'
import { ApiError } from '../lib/errors'
import { enterViewAs } from '../lib/viewAs'
import type { Tone } from '../lib/status'
import Async from '../components/Async'
import StatusBadge from '../components/StatusBadge'
import './Admin.css'
import PageHero from '../components/PageHero'

const TABS: [string, string][] = [
  ['overview', 'סקירה'],
  ['drafts', 'טיוטות ידע'],
  ['published', 'ידע מפורסם'],
  ['sources', 'מקורות מאושרים'],
  ['reports', 'דיווחי משתמשים'],
  ['monitoring', 'ניטור סוכנים'],
  ['deliveries', 'התראות שנשלחו'],
  ['audit', 'יומן פעולות'],
  ['accounts', 'חשבונות'],
]

export default function Admin() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'overview'

  return (
    <section className="pc-admin">
      <PageHero eyebrow="אזור מנהלי מערכת" title="ניהול" />

      <div className="pc-tabs pc-admintabs" role="tablist">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={`pc-tabbtn${tab === key ? ' active' : ''}`}
            onClick={() => setParams({ tab: key }, { replace: true })}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'overview' && <OverviewTab />}
      {tab === 'drafts' && <DraftsTab />}
      {tab === 'published' && <PublishedTab />}
      {tab === 'sources' && <SourcesTab />}
      {tab === 'reports' && <ReportsTab />}
      {tab === 'monitoring' && <MonitoringTab />}
      {tab === 'deliveries' && <DeliveriesTab />}
      {tab === 'audit' && <AuditTab />}
      {tab === 'accounts' && <AccountsTab />}
    </section>
  )
}

/* --- shared --------------------------------------------------------------- */

function Problem({ error, fallback }: { error: unknown; fallback: string }) {
  if (!error) return null
  return (
    <p className="pc-formerror" role="alert">
      {error instanceof ApiError ? error.message : fallback}
    </p>
  )
}

function money(value: number): string {
  return `$${value.toFixed(4)}`
}

/* --- overview ------------------------------------------------------------- */

function OverviewTab() {
  const query = useOverview()
  const data = query.data

  return (
    <Async query={query} loadingLabel="טוען…">
      {data && (
        <>
          {/* Ordered by what would make someone act: failures, then things waiting
              on a person, then volume. */}
          <div className="pc-metrics">
            <Metric label="בקשות AI שנכשלו" value={data.failed_agent_requests} alert />
            <Metric label="תזכורות שנכשלו" value={data.failed_notifications} alert />
            <Metric label="טיוטות לבדיקה" value={data.drafts_awaiting_review} />
            <Metric label="דיווחים פתוחים" value={data.open_knowledge_reports} />
          </div>

          <p className="pc-placeholder-note">
            נתוני <span className="pc-num">{data.window_days}</span> הימים האחרונים
          </p>

          {data.agent_stats.length === 0 ? (
            <p className="pc-placeholder-note">לא נרשמו הרצות בחלון הזמן הזה.</p>
          ) : (
            <>
              <h2>שימוש בסוכנים</h2>
              <ul className="pc-adminlist">
                {data.agent_stats.map((stat) => (
                  <li key={stat.agent_type} className="pc-card">
                    {/* Not `pc-adminrowhead`: that is a flex row with
                        space-between, for a title and a button. On a sentence it
                        pushes the words to opposite edges. */}
                    <p className="pc-statline">
                      {stat.agent_type} · <span className="pc-num">{stat.total}</span> הרצות
                      {stat.failed > 0 && (
                        <>
                          {' · '}
                          <span className="pc-fail">
                            <span className="pc-num">{stat.failed}</span> נכשלו
                          </span>
                        </>
                      )}
                    </p>
                    <p className="pc-placeholder-note">
                      עלות מוערכת <span className="pc-num">{money(stat.estimated_cost)}</span> ·
                      משך ממוצע <span className="pc-num">{stat.average_latency_ms}ms</span>
                    </p>
                  </li>
                ))}
              </ul>

              <p className="pc-placeholder-note">
                סה״כ עלות מוערכת:{' '}
                <span className="pc-num">{money(data.total_estimated_cost)}</span>
                {/* An execution with no cost is not a free execution. Saying so keeps
                    the total honest as a floor: an unpriced model and a call that
                    failed after the model had generated both land here, and both were
                    reported as $0.00 until the provider work — which is why this figure
                    disagreed with the invoice. */}
                {data.executions_missing_cost > 0 && (
                  <>
                    {' · '}
                    <span className="pc-num">{data.executions_missing_cost}</span> הרצות ללא
                    עלות מתועדת
                  </>
                )}
              </p>
            </>
          )}
        </>
      )}
    </Async>
  )
}

function Metric({ label, value, alert }: { label: string; value: number; alert?: boolean }) {
  return (
    <div className={`pc-metric${alert && value > 0 ? ' is-alert' : ''}`}>
      <span className="pc-metricvalue pc-num">{value}</span>
      <span className="pc-metriclabel">{label}</span>
    </div>
  )
}

/* --- drafts --------------------------------------------------------------- */

const DRAFT_FILTERS: (DraftStatus | 'ALL')[] = [
  'READY_FOR_REVIEW',
  'RESEARCHING',
  'REJECTED',
  'FAILED',
  'APPROVED',
  'ALL',
]

function DraftsTab() {
  const [status, setStatus] = useState<DraftStatus | 'ALL'>('READY_FOR_REVIEW')
  const query = useDrafts(status)

  return (
    <>
      <label className="pc-field pc-filter">
        <span>סינון לפי סטטוס</span>
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value as DraftStatus | 'ALL')}
        >
          {DRAFT_FILTERS.map((value) => (
            <option key={value} value={value}>
              {value === 'ALL' ? 'הכול' : (DRAFT_STATUS_LABELS[value]?.label ?? value)}
            </option>
          ))}
        </select>
      </label>

      <Async
        query={query}
        loadingLabel="טוען טיוטות…"
        empty={(query.data?.length ?? 0) === 0}
        emptyState={
          <>
            <p>אין טיוטות בסטטוס הזה.</p>
            <p className="pc-placeholder-note">
              טיוטה נפתחת אוטומטית כשמשתמש מאשר זיהוי של מין שאין לו עדיין ידע מפורסם.
            </p>
          </>
        }
      >
        <ul className="pc-adminlist">
          {query.data?.map((draft) => (
            <Draft key={draft.id} draft={draft} />
          ))}
        </ul>
      </Async>
    </>
  )
}

function Draft({ draft }: { draft: KnowledgeDraft }) {
  const [note, setNote] = useState('')
  const approve = useApproveDraft()
  const reject = useRejectDraft()
  const retry = useRetryDraft()

  const sections = draft.content?.sections ?? {}
  const sources = (draft.content?.sources ?? []) as Record<string, unknown>[]
  const reviewable = draft.status === 'READY_FOR_REVIEW'
  const badge = DRAFT_STATUS_LABELS[draft.status]
  const busy = approve.isPending || reject.isPending || retry.isPending

  return (
    <li className="pc-card">
      <div className="pc-adminrowhead">
        {/* The species, not its id. A list of drafts is a list of plants waiting,
            and eight hex characters identify none of them. The id stays reachable
            on hover, because it is what gets pasted into a query. */}
        <h3 title={draft.species_id}>
          {draft.species_common_name ?? draft.species_scientific_name ?? (
            <span className="pc-ltr">{draft.species_id.slice(0, 8)}</span>
          )}
        </h3>
        {badge && <StatusBadge label={badge.label} tone={badge.tone as Tone} glyph="·" />}
      </div>
      <p className="pc-placeholder-note">
        {draft.species_common_name && draft.species_scientific_name && (
          <>
            <span className="pc-ltr">{draft.species_scientific_name}</span> ·{' '}
          </>
        )}
        שפה: {draft.language} · עודכן <span className="pc-num">{formatStamp(draft.updated_at)}</span>
      </p>

      {draft.admin_note && <p className="pc-formnotice">{draft.admin_note}</p>}

      {Object.keys(sections).length === 0 ? (
        <p className="pc-placeholder-note">אין עדיין תוכן לבדיקה.</p>
      ) : (
        <>
          {draft.research_notes && (
            <p className="pc-placeholder-note">הערות מחקר: {draft.research_notes}</p>
          )}
          <Sections sections={sections} />
          <h4>מקורות</h4>
          <Sources sources={sources} />
        </>
      )}

      {approve.isSuccess && (
        <p className="pc-formnotice" role="status">
          פורסמה גרסה <span className="pc-num">{approve.data.version_number}</span>.{' '}
          <span className="pc-num">{approve.data.active_plants}</span> צמחים של המין הזה פעילים
          כעת.
        </p>
      )}
      {reject.isSuccess && (
        /* A17 made visible: rejection is not the end of the road, and the plants
           waiting on this species are still waiting. */
        <p className="pc-formnotice" role="status">
          הטיוטה נדחתה. הצמחים ממשיכים להמתין וניתן לחקור מחדש.
        </p>
      )}
      {retry.isSuccess && (
        <p className="pc-formnotice" role="status">
          המחקר יצא לדרך. הטיוטה תחזור לכאן כשיסתיים.
        </p>
      )}

      <Problem error={approve.error || reject.error || retry.error} fallback="הפעולה נכשלה." />

      <label className="pc-field">
        <span>סיבת דחייה (חובה לדחייה, ומועברת לסוכן במחקר חוזר)</span>
        <input
          type="text"
          maxLength={2000}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="למשל: ההמלצה על ההשקיה אינה מתאימה לאקלים מקומי"
        />
      </label>

      <div className="pc-actionrow">
        <button
          type="button"
          className="pc-btn"
          disabled={!reviewable || busy}
          onClick={() => approve.mutate(draft.id)}
        >
          אישור ופרסום
        </button>
        <button
          type="button"
          className="pc-btn pc-btn-quiet"
          disabled={!reviewable || !note.trim() || busy}
          onClick={() => reject.mutate({ draftId: draft.id, note: note.trim() })}
        >
          דחייה
        </button>
        <button
          type="button"
          className="pc-btn pc-btn-quiet"
          /* A17: the path out of a rejected or failed draft, and so the path out of
             KNOWLEDGE_PENDING for the plants waiting on it. */
          disabled={draft.status === 'RESEARCHING' || draft.status === 'APPROVED' || busy}
          onClick={() => retry.mutate({ draftId: draft.id, reason: note.trim() || null })}
        >
          מחקר מחדש
        </button>
      </div>
    </li>
  )
}

/**
 * The draft's text, weakest first.
 *
 * Section order would put the shakiest claim wherever it happens to fall in the
 * fourteen. The warning line exists to tell a reviewer where to start, and a weak
 * section opens by default so it cannot be scrolled past.
 */
function Sections({ sections }: { sections: Record<string, KnowledgeSection> }) {
  const weak = Object.entries(sections)
    .filter(([, section]) => (section?.confidence ?? 1) < WEAK_SECTION)
    .sort((a, b) => (a[1].confidence ?? 1) - (b[1].confidence ?? 1))
    .map(([name]) => name)

  const label = (name: string) =>
    KNOWLEDGE_SECTIONS.find(([key]) => key === name)?.[1] ?? name

  return (
    <>
      {weak.length > 0 && (
        <p className="pc-formerror" role="status">
          סעיפים בביטחון נמוך: {weak.map(label).join(', ')}
        </p>
      )}

      {KNOWLEDGE_SECTIONS.map(([name, text]) => {
        const section = sections[name]
        if (!section) return null
        const confidence = section.confidence ?? 0
        return (
          <details key={name} className="pc-reco" open={confidence < WEAK_SECTION}>
            <summary>
              {text} · ביטחון <span className="pc-num">{confidence.toFixed(2)}</span>
            </summary>
            <p className="pc-prose">{section.text}</p>
          </details>
        )
      })}
    </>
  )
}

function Sources({ sources }: { sources: Record<string, unknown>[] }) {
  if (!sources.length) return <p className="pc-placeholder-note">לא צורפו מקורות.</p>

  const ordered = [...sources].sort(
    (a, b) =>
      (SOURCE_CLASS_ORDER[String(a.source_class)] ?? 9) -
      (SOURCE_CLASS_ORDER[String(b.source_class)] ?? 9),
  )

  return (
    <ul className="pc-sources">
      {ordered.map((source, index) => {
        const badge = SOURCE_CLASS_LABELS[String(source.source_class)]
        return (
          <li key={String(source.id ?? index)} className="pc-source">
            <StatusBadge
              label={badge?.label ?? String(source.source_class ?? '—')}
              tone={(badge?.tone ?? 'neutral') as Tone}
              glyph="·"
            />
            {source.title ? <p className="pc-sourcetitle">{String(source.title)}</p> : null}
            {source.publisher ? (
              <p className="pc-placeholder-note">{String(source.publisher)}</p>
            ) : null}
            {source.url ? (
              <a href={String(source.url)} target="_blank" rel="noopener noreferrer">
                פתיחת המקור
              </a>
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}

/* --- published knowledge -------------------------------------------------- */

function PublishedTab() {
  const [search, setSearch] = useState('')
  const [openVersion, setOpenVersion] = useState<string | null>(null)
  const [speciesId, setSpeciesId] = useState('')
  const query = useCatalogue(search.trim())

  if (openVersion) {
    return <Version versionId={openVersion} onClose={() => setOpenVersion(null)} />
  }

  return (
    <>
      <p className="pc-placeholder-note">
        כל המינים שיש להם ידע מפורסם. גרסאות שפורסמו אינן ניתנות לעריכה או למחיקה.
      </p>

      <label className="pc-field pc-filter">
        <span>חיפוש מין</span>
        <input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="שם מדעי או שם עברי"
        />
      </label>

      <Async
        query={query}
        loadingLabel="טוען…"
        empty={(query.data?.length ?? 0) === 0}
        emptyState={<p>לא נמצאו מינים עם ידע מפורסם.</p>}
      >
        <ul className="pc-adminlist">
          {query.data?.map((entry) => (
            <Catalogued key={entry.id} entry={entry} onOpen={() => setOpenVersion(entry.id)} />
          ))}
        </ul>
      </Async>

      <details className="pc-reco">
        <summary>היסטוריית גרסאות לפי מזהה מין</summary>
        <label className="pc-field">
          <span>מזהה מין</span>
          <input
            type="text"
            className="pc-ltr"
            value={speciesId}
            onChange={(event) => setSpeciesId(event.target.value)}
            placeholder="UUID של המין"
          />
        </label>
        {speciesId.trim() && (
          <SpeciesVersions speciesId={speciesId.trim()} onOpen={setOpenVersion} />
        )}
      </details>
    </>
  )
}

function Catalogued({ entry, onOpen }: { entry: CatalogueEntry; onOpen: () => void }) {
  return (
    <li className="pc-card">
      <div className="pc-adminrowhead">
        <h3>
          {entry.common_name || entry.scientific_name}{' '}
          <span className="pc-sci pc-ltr">{entry.scientific_name}</span>
        </h3>
        <button type="button" className="pc-btn pc-btn-sm" onClick={onOpen}>
          פתיחת הידע
        </button>
      </div>
      <p className="pc-placeholder-note">
        גרסה <span className="pc-num">{entry.version_number}</span> · {entry.language} · פורסם{' '}
        <span className="pc-num">{entry.published_at.slice(0, 10)}</span> ·{' '}
        <span className="pc-num">{entry.plant_count}</span> צמחים
      </p>
      <ResearchControl entry={entry} />
    </li>
  )
}

/**
 * Start a fresh research run for a species whose article is already published.
 *
 * Published knowledge had no route back into research: the retry control lives on a
 * draft, and an approved species has no open draft to press it on. This is the screen
 * where that judgement is formed — it shows the text, the version and how many plants
 * are reading it — so it is where the control belongs.
 *
 * Folded into a disclosure rather than sitting beside "open" because this is a
 * browsing screen where every article listed is working. Opening it is the first half
 * of the confirmation and typing a reason is the second. The reason is not a
 * formality: it reaches the agent, so a second attempt can address the objection
 * instead of reproducing the article that prompted it.
 */
function ResearchControl({ entry }: { entry: CatalogueEntry }) {
  const [reason, setReason] = useState('')
  const research = useResearchSpecies()
  const open = entry.open_draft_status

  return (
    <details className="pc-reco">
      <summary>מחקר חדש</summary>

      {open ? (
        /* The route refuses this with a 409. Saying so here means the administrator
           does not have to meet it, and names where the draft is. */
        <p className="pc-formnotice">
          כבר קיימת טיוטה פתוחה למין הזה ({DRAFT_STATUS_LABELS[open]?.label ?? open}). אפשר
          לטפל בה בלשונית טיוטות ידע.
        </p>
      ) : research.isSuccess ? (
        <p className="pc-formnotice" role="status">
          המחקר יצא לדרך. הטיוטה תופיע בלשונית טיוטות ידע כשיסתיים.
        </p>
      ) : (
        <>
          <p className="pc-placeholder-note">
            מחקר חדש פותח טיוטה לבדיקה. הידע המפורסם נשאר פעיל עד שהטיוטה תאושר, ואם היא
            תידחה לא ישתנה דבר. הרצה אחת אורכת כחמש דקות והיא היקרה ביותר במערכת.
          </p>
          <label className="pc-field">
            <span>סיבת המחקר (מועברת לסוכן)</span>
            <input
              type="text"
              maxLength={1000}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="למשל: הפרק על השקיה שגוי"
            />
          </label>
          <Problem error={research.error} fallback="לא הצלחנו להתחיל מחקר." />
          <button
            type="button"
            className="pc-btn"
            disabled={reason.trim().length < 3 || research.isPending}
            onClick={() =>
              research.mutate({
                speciesId: entry.species_id,
                reason: reason.trim(),
                language: entry.language,
              })
            }
          >
            {research.isPending ? 'מתחילים…' : 'התחלת מחקר'}
          </button>
        </>
      )}
    </details>
  )
}

function SpeciesVersions({
  speciesId,
  onOpen,
}: {
  speciesId: string
  onOpen: (versionId: string) => void
}) {
  const query = useSpeciesVersions(speciesId)
  return (
    <Async
      query={query}
      loadingLabel="טוען…"
      empty={(query.data?.length ?? 0) === 0}
      emptyState={<p>לא נמצאו גרסאות למין הזה.</p>}
    >
      <ul className="pc-adminlist">
        {query.data?.map((version) => (
          <li key={version.id} className="pc-adminrowhead">
            <span>
              גרסה <span className="pc-num">{version.version_number}</span> ·{' '}
              <span className="pc-num">{version.published_at.slice(0, 10)}</span>
              {version.is_current && ' · נוכחית'}
            </span>
            <button
              type="button"
              className="pc-btn pc-btn-sm"
              onClick={() => onOpen(version.id)}
            >
              פתיחה
            </button>
          </li>
        ))}
      </ul>
    </Async>
  )
}

/**
 * One published version, in full.
 *
 * The tab used to show a version number, a date and a badge — never the text. Its own
 * endpoint has always returned the content and the sources; the screen read neither,
 * so "published knowledge" could be confirmed to exist and never read.
 */
function Version({ versionId, onClose }: { versionId: string; onClose: () => void }) {
  const query = useVersionDetail(versionId)
  const detail = query.data

  return (
    <Async query={query} loadingLabel="טוען…">
      {detail && (
        <>
          <div className="pc-adminrowhead">
            <h2>
              גרסה <span className="pc-num">{detail.version_number}</span> · {detail.language}
            </h2>
            <button type="button" className="pc-btn pc-btn-sm pc-btn-quiet" onClick={onClose}>
              סגירה
            </button>
          </div>
          <p className="pc-placeholder-note">
            פורסם <span className="pc-num">{formatStamp(detail.published_at)}</span>
            {detail.is_current && ' · הגרסה הנוכחית'}
          </p>

          {Object.keys(detail.content).length === 0 && (
            <p className="pc-placeholder-note">לגרסה הזו אין תוכן.</p>
          )}

          {KNOWLEDGE_SECTIONS.map(([name, label]) => {
            const section = detail.content[name]
            const text = typeof section === 'string' ? section : section?.text
            if (!text) return null
            const confidence = typeof section === 'string' ? undefined : section?.confidence
            return (
              <details key={name} className="pc-reco">
                <summary>{label}</summary>
                <p className="pc-prose">{text}</p>
                {/* Confidence is per section and is the reason a reviewer looks at
                    one section rather than another. */}
                {confidence !== undefined && (
                  <p className="pc-placeholder-note">
                    רמת ביטחון: <span className="pc-num">{confidence}</span>
                  </p>
                )}
              </details>
            )
          })}

          <h3>מקורות</h3>
          <Sources sources={detail.sources as unknown as Record<string, unknown>[]} />
        </>
      )}
    </Async>
  )
}

/* --- approved sources ----------------------------------------------------- */

function SourcesTab() {
  const query = useApprovedSources()
  const create = useCreateSource()
  const setEnabled = useSetSourceEnabled()

  const [name, setName] = useState('')
  const [domain, setDomain] = useState('')
  const [reliability, setReliability] = useState(3)

  return (
    <>
      <details className="pc-reco">
        <summary>הוספת מקור מאושר</summary>
        <label className="pc-field">
          <span>שם</span>
          <input
            type="text"
            maxLength={200}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="pc-field">
          <span>דומיין</span>
          <input
            type="text"
            className="pc-ltr"
            maxLength={200}
            value={domain}
            onChange={(event) => setDomain(event.target.value)}
            placeholder="rhs.org.uk"
          />
          {/* The server normalises a pasted URL down to the bare host, because
              classification is a label-boundary suffix match. */}
          <small>אפשר להדביק כתובת מלאה; נשמר רק הדומיין.</small>
        </label>
        <label className="pc-field">
          <span>
            רמת אמינות: <span className="pc-num">{reliability}</span>
          </span>
          <input
            type="range"
            min={1}
            max={5}
            value={reliability}
            onChange={(event) => setReliability(Number(event.target.value))}
          />
        </label>
        <Problem error={create.error} fallback="המקור לא נוסף." />
        {create.isSuccess && (
          <p className="pc-formnotice" role="status">
            המקור נוסף.
          </p>
        )}
        <button
          type="button"
          className="pc-btn"
          disabled={!name.trim() || !domain.trim() || create.isPending}
          onClick={() =>
            create.mutate(
              { name: name.trim(), domain: domain.trim(), reliability_level: reliability },
              {
                onSuccess: () => {
                  setName('')
                  setDomain('')
                },
              },
            )
          }
        >
          {create.isPending ? 'מוסיפים…' : 'הוספה'}
        </button>
      </details>

      <Problem error={setEnabled.error} fallback="לא הצלחנו לעדכן את המקור." />

      <Async
        query={query}
        loadingLabel="טוען…"
        empty={(query.data?.length ?? 0) === 0}
        emptyState={<p>אין עדיין מקורות מאושרים.</p>}
      >
        <ul className="pc-adminlist">
          {query.data?.map((source) => (
            <li key={source.id} className="pc-card">
              <div className="pc-adminrowhead">
                <h3>
                  {source.name} <code>{source.domain}</code>
                </h3>
                <StatusBadge
                  label={source.is_enabled ? 'פעיל' : 'מושבת'}
                  tone={source.is_enabled ? 'success' : 'neutral'}
                  glyph={source.is_enabled ? '✓' : '·'}
                />
              </div>
              {source.reliability_level && (
                <p className="pc-placeholder-note">
                  אמינות: <span className="pc-num">{source.reliability_level}/5</span>
                </p>
              )}
              <button
                type="button"
                className="pc-btn pc-btn-sm pc-btn-quiet"
                disabled={setEnabled.isPending}
                onClick={() =>
                  setEnabled.mutate({ sourceId: source.id, enabled: !source.is_enabled })
                }
              >
                {source.is_enabled ? 'השבתה' : 'הפעלה מחדש'}
              </button>
              {source.is_enabled && (
                /* Disabling deliberately does not touch existing provenance rows:
                   they record what was true when a version published. */
                <p className="pc-placeholder-note">
                  השבתה אינה משנה גרסאות שכבר פורסמו.
                </p>
              )}
            </li>
          ))}
        </ul>
      </Async>
    </>
  )
}

/* --- user reports --------------------------------------------------------- */

function ReportsTab() {
  const query = useKnowledgeReports()
  const review = useReviewReport()

  return (
    <>
      <p className="pc-placeholder-note">
        דיווחי משתמשים על שגיאות במידע. אישור דיווח אינו מפעיל מחקר — לשם כך יש לחקור מחדש
        בלשונית הטיוטות.
      </p>

      <Problem error={review.error} fallback="הדיווח לא עודכן." />

      <Async
        query={query}
        loadingLabel="טוען…"
        empty={(query.data?.length ?? 0) === 0}
        emptyState={<p>אין דיווחים פתוחים.</p>}
      >
        <ul className="pc-adminlist">
          {query.data?.map((report) => (
            <li key={report.id} className="pc-card">
              <p className="pc-prose">{report.report_text}</p>
              <p className="pc-placeholder-note">
                מין: <span className="pc-ltr">{(report.species_id ?? '—').slice(0, 8)}</span> ·{' '}
                <span className="pc-num">{formatStamp(report.created_at)}</span>
              </p>
              <div className="pc-actionrow">
                {REPORT_DECISIONS.map(([status, label]) => (
                  <button
                    key={status}
                    type="button"
                    className="pc-btn pc-btn-sm pc-btn-quiet"
                    disabled={review.isPending}
                    onClick={() => review.mutate({ reportId: report.id, status })}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </li>
          ))}
        </ul>
      </Async>
    </>
  )
}

/* --- agent monitoring ----------------------------------------------------- */

function MonitoringTab() {
  const [executionFailures, setExecutionFailures] = useState(false)
  const [requestFailures, setRequestFailures] = useState(false)
  const executions = useAgentExecutions(executionFailures)
  const requests = useAgentRequests(requestFailures)

  return (
    <>
      <p className="pc-placeholder-note">
        הרצות של סוכני ה-AI: מודל, גרסת פרומפט, משך ועלות. תוכן הפרומפטים והתשובות אינו נשמר
        ואינו ניתן לצפייה.
      </p>

      <label className="pc-toggle">
        <input
          type="checkbox"
          checked={executionFailures}
          onChange={(event) => setExecutionFailures(event.target.checked)}
        />
        <span>רק כשלים</span>
      </label>

      <Async
        query={executions}
        loadingLabel="טוען…"
        empty={(executions.data?.length ?? 0) === 0}
        emptyState={<p>אין הרצות להצגה.</p>}
      >
        <ul className="pc-adminlist">
          {executions.data?.map((execution) => (
            <Execution key={execution.id} execution={execution} />
          ))}
        </ul>
      </Async>

      {/* The requests those executions belong to. An execution row says a model call
          happened; a request says whether the *user's* operation finished. They can
          disagree — a run whose provider error escaped the gateway leaves a FAILED
          request and no execution at all — and only this view makes that visible. */}
      <h2>בקשות סוכן</h2>
      <p className="pc-placeholder-note">
        מה שהמשתמש ביקש, לעומת הקריאות למודל שלמעלה. פער ביניהן הוא סימן לתקלה.
      </p>

      <label className="pc-toggle">
        <input
          type="checkbox"
          checked={requestFailures}
          onChange={(event) => setRequestFailures(event.target.checked)}
        />
        <span>רק כשלים</span>
      </label>

      <Async
        query={requests}
        loadingLabel="טוען…"
        empty={(requests.data?.length ?? 0) === 0}
        emptyState={<p>אין בקשות להצגה.</p>}
      >
        <ul className="pc-adminlist">
          {requests.data?.map((request) => (
            <li key={request.id} className="pc-card">
              <div className="pc-adminrowhead">
                <h3>
                  {request.agent_type} · {request.status}
                </h3>
                {request.status === 'FAILED' && (
                  <StatusBadge label="נכשל" tone="danger" glyph="!" />
                )}
              </div>
              <p className="pc-placeholder-note">
                <span className="pc-num">{formatStamp(request.created_at)}</span>
                {request.stage && ` · שלב ${request.stage}`}
                {request.error_code && ` · ${request.error_code}`}
              </p>
            </li>
          ))}
        </ul>
      </Async>
    </>
  )
}

function Execution({ execution }: { execution: AgentExecution }) {
  /* Tokens and cost can be null, and null is not zero: a call that failed after the
     model generated was still billed, and a model with no price in its provider's
     table cannot be costed at all. Formatting either as 0 would restate the
     understatement this distinction exists to remove. */
  const tokens =
    execution.input_tokens === null
      ? 'לא תועד'
      : `${execution.input_tokens}+${execution.output_tokens ?? 0} טוקנים`

  return (
    <li className="pc-card">
      <div className="pc-adminrowhead">
        <h3>
          {execution.agent_type} · <span className="pc-ltr">{execution.model}</span>
        </h3>
        {execution.status === 'FAILED' && <StatusBadge label="נכשל" tone="danger" glyph="!" />}
      </div>
      <p className="pc-placeholder-note">
        <span className="pc-num">{formatStamp(execution.created_at)}</span> · פרומפט{' '}
        <span className="pc-ltr">{execution.prompt_version}</span> · ניסיון{' '}
        <span className="pc-num">{execution.attempt}</span> ·{' '}
        <span className="pc-num">{execution.latency_ms}ms</span> ·{' '}
        <span className="pc-num">{tokens}</span> ·{' '}
        <span className="pc-num">
          {execution.estimated_cost === null ? 'עלות לא תועדה' : money(execution.estimated_cost)}
        </span>
      </p>
      {execution.error_code && (
        <p className="pc-placeholder-note">שגיאה: {execution.error_code}</p>
      )}
    </li>
  )
}

/* --- notification deliveries ---------------------------------------------- */

function DeliveriesTab() {
  const [failuresOnly, setFailuresOnly] = useState(false)
  const query = useAdminDeliveries(failuresOnly)

  return (
    <>
      <p className="pc-placeholder-note">
        כל שליחה נרשמת לפני הקריאה לספק, כך שהיומן מראה גם ניסיונות שנכשלו. כשלא מוגדר ספק
        דואר, המערכת אינה שולחת דבר וזה ייראה כאן.
      </p>

      <label className="pc-toggle">
        <input
          type="checkbox"
          checked={failuresOnly}
          onChange={(event) => setFailuresOnly(event.target.checked)}
        />
        <span>רק כשלים</span>
      </label>

      <Async
        query={query}
        loadingLabel="טוען…"
        empty={(query.data?.length ?? 0) === 0}
        emptyState={<p>לא נשלחו התראות.</p>}
      >
        <ul className="pc-adminlist">
          {query.data?.map((delivery) => (
            <li key={delivery.id} className="pc-card">
              <StatusBadge
                label={delivery.status}
                tone={
                  delivery.status === 'SENT'
                    ? 'success'
                    : delivery.status === 'FAILED'
                      ? 'danger'
                      : 'neutral'
                }
                glyph="·"
              />
              <p className="pc-placeholder-note">
                <span className="pc-ltr">{delivery.dedupe_key}</span> · תוזמן{' '}
                <span className="pc-num">{formatStamp(delivery.scheduled_at)}</span>
                {delivery.sent_at && (
                  <>
                    {' · נשלח '}
                    <span className="pc-num">{formatStamp(delivery.sent_at)}</span>
                  </>
                )}
              </p>
              {delivery.error_message && (
                <p className="pc-placeholder-note">שגיאה: {delivery.error_message}</p>
              )}
            </li>
          ))}
        </ul>
      </Async>
    </>
  )
}

/* --- audit log ------------------------------------------------------------ */

function AuditTab() {
  const query = useAuditLog()

  return (
    <>
      {/* Append-only at the table, and it had no screen at all until late: an audit
          log nobody can open records everything and proves nothing. */}
      <p className="pc-placeholder-note">
        כל פעולת ניהול מהותית נרשמת כאן. הטבלה מסרבת לעדכון ולמחיקה עבור כל תפקיד, כך שהרישום
        אינו ניתן לשינוי בדיעבד.
      </p>

      <Async
        query={query}
        loadingLabel="טוען…"
        empty={(query.data?.length ?? 0) === 0}
        emptyState={<p>אין רישומים.</p>}
      >
        <ul className="pc-adminlist">
          {query.data?.map((entry) => (
            <li key={entry.id} className="pc-card">
              <h3 className="pc-ltr">{entry.action}</h3>
              <p className="pc-placeholder-note">
                <span className="pc-num">{formatStamp(entry.created_at)}</span>
                {entry.target_table && ` · ${entry.target_table}`}
                {entry.target_id && (
                  <>
                    {' · '}
                    <span className="pc-ltr">{entry.target_id.slice(0, 8)}</span>
                  </>
                )}
              </p>
              {entry.payload && (
                <details className="pc-reco">
                  <summary>פרטים</summary>
                  <pre>{JSON.stringify(entry.payload, null, 2)}</pre>
                </details>
              )}
            </li>
          ))}
        </ul>
      </Async>
    </>
  )
}

/* --- accounts ------------------------------------------------------------- */

function AccountsTab() {
  const [search, setSearch] = useState('')
  const query = useAccounts(search.trim())

  return (
    <>
      <p className="pc-placeholder-note">
        חשבונות אינם נמחקים פיזית. אנונימיזציה מוחקת פרטים מזהים, חוסמת גישה ומשמרת את
        ההיסטוריה.
      </p>

      <label className="pc-field pc-filter">
        <span>חיפוש לפי אימייל</span>
        <input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </label>

      <Async
        query={query}
        loadingLabel="טוען…"
        empty={(query.data?.length ?? 0) === 0}
        emptyState={<p>לא נמצאו חשבונות.</p>}
      >
        <ul className="pc-adminlist">
          {query.data?.slice(0, 25).map((account) => (
            <AccountRow key={account.id} account={account} />
          ))}
        </ul>
      </Async>
    </>
  )
}

function AccountRow({ account }: { account: Account }) {
  const [reason, setReason] = useState('')
  const startViewAs = useStartViewAs()
  const anonymize = useAnonymizeAccount()

  const anonymized = Boolean(account.anonymized_at)

  return (
    <li className="pc-card">
      <div className="pc-adminrowhead">
        <h3 className="pc-ltr">{account.email ?? '(אנונימי)'}</h3>
        {anonymized ? (
          <StatusBadge label="אנונימי" tone="neutral" glyph="·" />
        ) : (
          !account.is_active && <StatusBadge label="מושבת" tone="neutral" glyph="·" />
        )}
      </div>
      <p className="pc-placeholder-note">
        {account.role} · נוצר <span className="pc-num">{account.created_at.slice(0, 10)}</span>
      </p>

      {!anonymized && (
        <>
          <Problem error={startViewAs.error || anonymize.error} fallback="הפעולה נכשלה." />

          <div className="pc-actionrow">
            {/* Read-only, and audited. The API refuses every non-GET carrying the
                act-as header, so this cannot change anything in the user's account;
                what it can do is show an administrator why a user is confused. */}
            <button
              type="button"
              className="pc-btn pc-btn-sm pc-btn-quiet"
              disabled={startViewAs.isPending}
              onClick={() =>
                startViewAs.mutate(account.id, {
                  onSuccess: () => enterViewAs(account.id, account.email),
                })
              }
            >
              צפייה כמשתמש
            </button>
          </div>

          <label className="pc-field">
            <span>סיבה</span>
            <input
              type="text"
              maxLength={500}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="למשל: בקשת מחיקה מהמשתמש"
            />
          </label>

          {anonymize.isSuccess && (
            <p className="pc-formnotice" role="status">
              החשבון עבר אנונימיזציה. ההיסטוריה נשמרה.
            </p>
          )}

          <button
            type="button"
            className="pc-btn pc-btn-quiet"
            /* A26: the reason is the only record of why an account was closed, so the
               action is unavailable without one. */
            disabled={reason.trim().length < 3 || anonymize.isPending}
            onClick={() => anonymize.mutate({ accountId: account.id, reason: reason.trim() })}
          >
            {anonymize.isPending ? 'מבצעים…' : 'אנונימיזציה'}
          </button>
        </>
      )}
    </li>
  )
}
