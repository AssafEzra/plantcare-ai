/* The plant dashboard — the central hub (FINAL section 17).
 *
 * Section 17 lists thirteen sections for one screen. The order here is the wireframe's
 * and it is not arbitrary: the hero image and status say what this plant *is* and how
 * it is doing; the actions come next, because that is why someone opened the page; and
 * history goes last, because it is for reading rather than acting.
 *
 * Everything above the timeline arrives in one `GET /v1/plants/{id}/dashboard`. The
 * timeline is fetched only once asked for — it sits below everything else on a long
 * page, so most visits never scroll to it, and in the Streamlit build fetching it on
 * every rerun cost about a second of the 5.7 that a single click spent on the API.
 *
 * Three flows here are 202-and-poll rather than request-and-response: a health check, a
 * care-plan proposal, and an environment change that triggers one. Each stays with its
 * agent request until it settles. The Streamlit version promised results "will appear
 * here in a moment" and then never looked again, so a failed run said nothing at all
 * and a successful one appeared only if the user happened to reload — reported as "did
 * a health check and nothing happened".
 */

import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import {
  usePlantDashboard,
  usePlantHistory,
  useArchivePlant,
  useRestorePlant,
  useRenamePlant,
  useSaveEnvironment,
  useLogHistoryEvent,
  useSetPlantIntensity,
  isPortrait,
  type PlantDashboard as Dashboard,
} from '../api/plantDetail'
import {
  useProposals,
  useApproveProposal,
  useRejectProposal,
  useAdjustPlan,
  useRequestProposal,
  useRequestHealthAdjustment,
} from '../api/carePlan'
import { useAssessment, useHealthHistory, useStartHealthCheck } from '../api/health'
import { useAgentRequest } from '../api/identification'
import { isDue } from '../api/careTasks'
import { useIsReadOnly } from '../lib/viewAs'
import { statusStyle, trendStyle, PLANT_STATUS_LABELS } from '../lib/status'
import { LOGGABLE_EVENTS } from '../lib/careVocab'
import { assessedAt, formatDate } from '../lib/dates'
import { ApiError } from '../lib/errors'
import Async from '../components/Async'
import StatusBadge from '../components/StatusBadge'
import PlantGallery from '../components/PlantGallery'
import CareTaskCard from '../components/CareTaskCard'
import CarePlanCard from '../components/CarePlanCard'
import ProposalDialog from '../components/ProposalDialog'
import { HealthInsight, AssessedPill, PastChecks } from '../components/HealthInsight'
import HealthAssessmentDialog from '../components/HealthAssessmentDialog'
import HealthCheckDialog from '../components/HealthCheckDialog'
import EnvironmentForm, { EnvironmentSummary } from '../components/EnvironmentForm'
import Modal from '../components/Modal'
import PageHero from '../components/PageHero'
import Timeline from '../components/Timeline'
import KnowledgePanel from '../components/KnowledgePanel'
import IdentificationPrompt from '../components/IdentificationPrompt'
import './PlantDashboard.css'

const HISTORY_PAGE = 20

export default function PlantDashboardPage() {
  const { plantId } = useParams<{ plantId: string }>()
  const query = usePlantDashboard(plantId)
  const plant = query.data

  return (
    <section className="pc-plantpage">
      <Async query={query} loadingLabel="טוען את הצמח…">
        {plant && plantId ? <Loaded plantId={plantId} plant={plant} /> : null}
      </Async>
    </section>
  )
}

function Loaded({ plantId, plant }: { plantId: string; plant: Dashboard }) {
  const archived = plant.status === 'ARCHIVED'
  /* Two reasons this page can be read-only, and they are not the same reason. An
     archived plant is a record: its history stays readable and it can be restored, but
     nothing about it is edited in place. View-as is somebody else's account, where the
     API refuses every write regardless — offering the controls would invite an
     administrator to press something that answers 403. */
  const readOnly = useIsReadOnly()
  const canEdit = !archived && !readOnly

  const status = statusStyle(plant.health.current_status)
  const trend = plant.health.trend ? trendStyle(plant.health.trend) : null
  const portraits = plant.gallery.filter(isPortrait)
  const [galleryOpen, setGalleryOpen] = useState(false)

  return (
    <>
      <PageHero
        eyebrow={archived ? 'בארכיון' : 'הצמח שלי'}
        title={plant.name || plant.species?.common_name || 'הצמח שלי'}
      >
        <Link to="/" className="pc-btn">
          לרשימת הצמחים
        </Link>
      </PageHero>

      {archived && (
        <p className="pc-formnotice" role="status">
          הצמח נמצא בארכיון. ההיסטוריה נשמרת ואפשר לשחזר אותו.
        </p>
      )}

      <div className="pc-planthero">
        {/* The whole picture is the way into the gallery. A grid of photographs sitting
            below the fold was a second copy of the same subject on one page; the one a
            reader is already looking at is the obvious handle, and the hint says so
            because a bare clickable image is not obvious at all. */}
        <button
          type="button"
          className="pc-heroimage"
          onClick={() => setGalleryOpen(true)}
          aria-label={`תמונות הצמח (${portraits.length})`}
        >
          {plant.main_image?.url ? (
            <img src={plant.main_image.url} alt={plant.name ?? 'הצמח שלי'} />
          ) : (
            <p className="pc-placeholder-note">אין עדיין תמונה</p>
          )}
          <span className="pc-heroimagehint" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="5" width="18" height="14" rx="2" />
              <circle cx="8.5" cy="10" r="1.5" />
              <path d="M21 16l-5-5-5.5 5.5L8 14l-5 5" />
            </svg>
            כל התמונות <span className="pc-num">{portraits.length}</span>
          </span>
        </button>

        <div className="pc-herofacts">
          {plant.species ? (
            <>
              <p className="pc-speciesname">
                {plant.species.common_name || plant.species.scientific_name}
              </p>
              {/* Latin in an RTL paragraph: isolated so the browser cannot reorder it,
                  but still set from the start edge. `pc-ltr` also left-aligns, which put
                  the species name on the far side of the card from the name it belongs
                  under. */}
              <p className="pc-speciessci">{plant.species.scientific_name}</p>
            </>
          ) : plant.pending_identification ? (
            <p className="pc-placeholder-note">הזיהוי הושלם וממתין לאישור שלך.</p>
          ) : (
            <p className="pc-placeholder-note">הצמח עדיין לא זוהה.</p>
          )}

          <div className="pc-herobadges">
            <StatusBadge label={status.label} tone={status.tone} glyph={status.glyph} />
            {trend && <StatusBadge label={trend.label} tone={trend.tone} glyph={trend.glyph} />}
            {plant.status !== 'ACTIVE' && (
              <StatusBadge
                label={PLANT_STATUS_LABELS[plant.status] ?? plant.status}
                tone="neutral"
                glyph="·"
              />
            )}
          </div>

          {plant.health.latest_assessed_at && (
            <p className="pc-placeholder-note">{assessedAt(plant.health.latest_assessed_at)}</p>
          )}
          <p className="pc-placeholder-note">נוסף {formatDate(plant.created_at)}</p>

          {/* Archive and restore are writes like any other, so they follow the same
              gate. Under view-as the API refuses them; on an archived plant restore
              is the one write that still makes sense, which is why `canEdit` is not
              the condition here. */}
          {!readOnly && <Lifecycle plantId={plantId} archived={archived} />}
        </div>
      </div>

      {plant.pending_identification && canEdit && (
        <IdentificationPrompt plantId={plantId} pending={plant.pending_identification} />
      )}

      <Details plantId={plantId} plant={plant} canEdit={canEdit} />

      <CareSection plantId={plantId} plant={plant} canEdit={canEdit} />

      <HealthSection plantId={plantId} plant={plant} canEdit={canEdit} />

      {plant.species && (
        <section>
          <div className="pc-sectionhead">
            <h2>מידע מקצועי על המין</h2>
          </div>
          <div className="pc-card">
            <KnowledgePanel speciesId={plant.species.id} plantId={plantId} />
          </div>
        </section>
      )}

      <HistorySection plantId={plantId} canEdit={canEdit} />

      {galleryOpen && (
        <Modal title="תמונות הצמח" onClose={() => setGalleryOpen(false)}>
          <PlantGallery plantId={plantId} images={plant.gallery} canEdit={canEdit} />
        </Modal>
      )}
    </>
  )
}

/* --- archive and restore --------------------------------------------------- */

function Lifecycle({ plantId, archived }: { plantId: string; archived: boolean }) {
  const archive = useArchivePlant(plantId)
  const restore = useRestorePlant(plantId)
  const failed = archive.error || restore.error

  return (
    <>
      <div className="pc-actionrow">
        {archived ? (
          <button
            type="button"
            className="pc-btn"
            disabled={restore.isPending}
            onClick={() => restore.mutate()}
          >
            {restore.isPending ? 'משחזרים…' : 'שחזור'}
          </button>
        ) : (
          <button
            type="button"
            className="pc-btn pc-btn-quiet"
            disabled={archive.isPending}
            onClick={() => archive.mutate()}
          >
            {archive.isPending ? 'מעבירים…' : 'העברה לארכיון'}
          </button>
        )}
      </div>
      {failed && (
        <p className="pc-formerror" role="alert">
          {failed instanceof ApiError ? failed.message : 'הפעולה לא הושלמה.'}
        </p>
      )}
    </>
  )
}

/* --- name and notes -------------------------------------------------------- */

function Details({
  plantId,
  plant,
  canEdit,
}: {
  plantId: string
  plant: Dashboard
  canEdit: boolean
}) {
  const [name, setName] = useState(plant.name ?? '')
  const [notes, setNotes] = useState(plant.notes ?? '')
  const rename = useRenamePlant(plantId)

  /* Read-only — archived, or somebody else's account under view-as. The edit panel is
     not rendered at all, so what it holds has to be readable somewhere: the conditions
     are part of what this plant IS, and a record that hides them is a worse record. */
  if (!canEdit) {
    return (
      <div className="pc-card">
        {plant.notes && (
          <>
            <h3>הערות</h3>
            <p>{plant.notes}</p>
          </>
        )}
        <h3>תנאי הגידול</h3>
        <EnvironmentSummary environment={plant.environment} />
      </div>
    )
  }

  return (
    <details className="pc-reco pc-detailsblock">
      <summary>עריכת פרטי הצמח ותנאי הגידול</summary>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          rename.mutate({ name: name.trim() || null, notes: notes.trim() || null })
        }}
      >
        <label className="pc-field">
          <span>שם הצמח</span>
          <input
            type="text"
            maxLength={120}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="pc-field">
          <span>הערות</span>
          <textarea
            rows={3}
            maxLength={2000}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
          />
        </label>

        {rename.error && (
          <p className="pc-formerror" role="alert">
            {rename.error instanceof ApiError ? rename.error.message : 'הפרטים לא נשמרו.'}
          </p>
        )}
        {rename.isSuccess && (
          <p className="pc-formnotice" role="status">
            הפרטים נשמרו.
          </p>
        )}

        <button type="submit" className="pc-btn" disabled={rename.isPending}>
          {rename.isPending ? 'שומרים…' : 'שמירה'}
        </button>
      </form>

      {/* The growing conditions were a section of their own, between the health check
          and the species article — a form sitting open in the middle of a page that is
          otherwise read, on fields that are set once and then rarely touched. They are
          editing, so they live where the editing is. A separate form rather than more
          fields in the one above it, because saving them does something else entirely:
          §12 says a change here produces a care-plan proposal. */}
      <div className="pc-editgroup">
        <h3>תנאי הגידול</h3>
        <EnvironmentSection plantId={plantId} plant={plant} />
      </div>
    </details>
  )
}

/* --- care: tasks, proposals, the plan -------------------------------------- */

function CareSection({
  plantId,
  plant,
  canEdit,
}: {
  plantId: string
  plant: Dashboard
  canEdit: boolean
}) {
  const [openProposal, setOpenProposal] = useState<string | null>(null)

  const proposalsQuery = useProposals(plantId, plant.open_proposals > 0)
  const proposals = proposalsQuery.data ?? []
  const approve = useApproveProposal(plantId)
  const reject = useRejectProposal(plantId)
  const adjust = useAdjustPlan(plantId)
  const setIntensity = useSetPlantIntensity()
  const requestPlan = useRequestProposal(plantId)

  /* Stay with a queued proposal until it exists. Care took 105 seconds on its first
     live run, so "it will appear in a moment" is a promise that has to be kept. */
  const [watching, setWatching] = useState<string | null>(null)
  const watched = useAgentRequest(watching)
  const settled = watched.data?.status
  const waiting = Boolean(watching) && settled !== 'SUCCEEDED' && settled !== 'FAILED'

  const shown = proposals.find((proposal) => proposal.id === openProposal)
  const upcoming = plant.upcoming_tasks.slice(0, 5)

  return (
    <>
      {upcoming.length > 0 && (
        <section>
          <div className="pc-sectionhead">
            <h2>הטיפול הקרוב</h2>
          </div>
          <ul className="pc-tasklist">
            {upcoming.map((task) => (
              <CareTaskCard
                key={task.id}
                task={task}
                plantId={plantId}
                linkToPlant={false}
                /* Done and Skip only on what is actually due. A task three days out
                   drawn with the same buttons invites completing it early, which
                   anchors the whole recurrence to today and quietly shifts the plan. */
                actionable={
                  canEdit && (task.status === 'PENDING' || task.status === 'OVERDUE') && isDue(task)
                }
              />
            ))}
          </ul>
        </section>
      )}

      {proposals.length > 0 && (
        <section>
          <div className="pc-sectionhead">
            <h2>ממתין לאישור שלך</h2>
          </div>
          {/* A summary on the page, the decision in a window. */}
          <ul className="pc-proposallist">
            {proposals.map((proposal) => (
              <li key={proposal.id} className="pc-card">
                <p className="pc-proposalsource">
                  גרסה <span className="pc-num">{proposal.version_number}</span>
                </p>
                {proposal.change_summary && (
                  <p className="pc-placeholder-note">{proposal.change_summary}</p>
                )}
                <button
                  type="button"
                  className="pc-btn"
                  onClick={() => setOpenProposal(proposal.id)}
                >
                  הצעת עדכון לתוכנית טיפול
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {shown && (
        <ProposalDialog
          proposal={shown}
          busy={approve.isPending || reject.isPending}
          error={approve.error || reject.error}
          onClose={() => setOpenProposal(null)}
          onApprove={() =>
            approve.mutate(shown.id, { onSuccess: () => setOpenProposal(null) })
          }
          onReject={() => reject.mutate(shown.id, { onSuccess: () => setOpenProposal(null) })}
        />
      )}

      <section>
        <div className="pc-sectionhead">
          <h2>תוכנית הטיפול</h2>
        </div>

        {plant.care_plan ? (
          <CarePlanCard
            plan={plant.care_plan}
            canEdit={canEdit}
            adjusting={adjust.isPending}
            adjustError={adjust.error}
            schedule={plant.care_schedule}
            onSetIntensity={(intensity) => setIntensity.mutate({ plantId: plant.id, intensity })}
            settingIntensity={setIntensity.isPending}
            intensitySaved={setIntensity.isSuccess}
            intensityError={setIntensity.error}
            onAdjust={(overrides, summary) =>
              adjust.mutate(
                { versionId: plant.care_plan!.id, overrides, summary },
                {
                  /* A saved adjustment is a decision waiting to be made, so saving
                     opens the window it lives in: the change summary, the diff of what
                     actually moves, and approve or decline. Reported twice against the
                     Streamlit build — "it wont let you save", then "it still doesnt show
                     the string after i save" — because the confirmation rendered at the
                     top of a page the user was at the bottom of. */
                  onSuccess: (result) => setOpenProposal(String(result.version_id)),
                },
              )
            }
          />
        ) : proposals.length === 0 ? (
          <div className="pc-card">
            {waiting ? (
              <p role="status">מכינים הצעה לתוכנית טיפול…</p>
            ) : settled === 'FAILED' ? (
              <p className="pc-formerror" role="alert">
                לא הצלחנו להכין הצעה כרגע. אפשר לנסות שוב.
              </p>
            ) : (
              <>
                <p>אין עדיין תוכנית טיפול.</p>
                <p className="pc-placeholder-note">
                  נכין הצעה לתוכנית המבוססת על המידע המקצועי של המין ועל התנאים בבית שלך.
                </p>
              </>
            )}

            {requestPlan.error && (
              <p className="pc-formerror" role="alert">
                {requestPlan.error instanceof ApiError
                  ? requestPlan.error.message
                  : 'לא הצלחנו להתחיל את ההכנה.'}
              </p>
            )}

            {canEdit && !waiting && (
              <button
                type="button"
                className="pc-btn"
                disabled={requestPlan.isPending}
                onClick={() =>
                  requestPlan.mutate('INITIAL_PLAN', {
                    onSuccess: (accepted) => setWatching(accepted.agent_request_id),
                  })
                }
              >
                {requestPlan.isPending ? 'מתחילים…' : 'הכנת תוכנית'}
              </button>
            )}
          </div>
        ) : null}
      </section>
    </>
  )
}

/* --- health ---------------------------------------------------------------- */

function HealthSection({
  plantId,
  plant,
  canEdit,
}: {
  plantId: string
  plant: Dashboard
  canEdit: boolean
}) {
  /* `?health-check=1` opens the dialog on arrival. The בריאות screen lists plants with
     a "בדיקה חדשה" link on each, and the check itself lives here, where the plant's
     photographs are — without this the link would land the reader on a long page with
     the button somewhere down it. Read once, on mount: a user who closes the dialog has
     closed it, and the parameter is cleared so a reload does not reopen it. */
  const [params, setParams] = useSearchParams()
  const [dialogOpen, setDialogOpen] = useState(canEdit && params.get('health-check') === '1')
  const [watching, setWatching] = useState<string | null>(null)
  /* Which past check is open over the page. The summary on the card is a summary; §16
     turns on the reasoning being reachable, and the dialog is where it is reachable
     from — the same dialog the בריאות list opens. */
  const [openAssessment, setOpenAssessment] = useState<string | null>(null)

  function closeDialog() {
    setDialogOpen(false)
    if (params.has('health-check')) {
      params.delete('health-check')
      setParams(params, { replace: true })
    }
  }

  const start = useStartHealthCheck(plantId)
  const watched = useAgentRequest(watching)
  const status = watched.data?.status
  const running = Boolean(watching) && status !== 'SUCCEEDED' && status !== 'FAILED'

  /* The plant's own verdict, not the agent request's — `status` above is the run. */
  const health = statusStyle(plant.health.current_status)
  const healthTrend = plant.health.trend ? trendStyle(plant.health.trend) : null

  const assessment = useAssessment(plant.health.latest_assessment_id)
  /* Fetched with the section rather than behind a "בדיקות קודמות" link. The dates are
     the card now, not a disclosure under it, and one small list beside a page that
     already makes several requests is not the thing to defer. */
  const history = useHealthHistory(plantId, Boolean(plant.health.latest_assessment_id))
  const adjustment = useRequestHealthAdjustment(plantId)

  /* Everything but the latest: the latest has its own line above these. */
  const past = (history.data ?? []).filter(
    (entry) => entry.id !== plant.health.latest_assessment_id,
  )


  /* The health check offers the plant's existing photographs as well. Portraits only:
     an earlier health close-up is already tied to the check it was taken for. */
  const offerable = plant.gallery.filter(isPortrait)

  return (
    <section>
      <div className="pc-sectionhead">
        <h2>בריאות הצמח</h2>
        {canEdit && !running && (
          <button type="button" className="pc-btn pc-btn-sm" onClick={() => setDialogOpen(true)}>
            בדיקת בריאות
          </button>
        )}
      </div>

      {running && <p role="status">בודקים את הצמח…</p>}

      {status === 'FAILED' && (
        <p className="pc-formerror" role="alert">
          {/* Section 25: the failure is visible, and nothing authoritative was written. */}
          הבדיקה לא הושלמה. אפשר לנסות שוב, ותמונות חדות יותר עוזרות.
        </p>
      )}

      {dialogOpen && (
        <HealthCheckDialog
          gallery={offerable}
          busy={start.isPending}
          error={start.error}
          onClose={closeDialog}
          onSubmit={(files, existingImageIds, note) =>
            start.mutate(
              { files, existingImageIds, note },
              {
                onSuccess: (accepted) => {
                  setWatching(accepted.agent_request_id)
                  closeDialog()
                },
              },
            )
          }
        />
      )}

      {plant.health.latest_assessment_id ? (
        /* The same card the בריאות list draws: what the last check found, when it ran,
           and the checks before it as dates. The whole assessment used to be rendered
           inline here — a wall of prose between the care plan and the species article,
           which is where a reader stops reading. */
        <div className="pc-card pc-healthsummary">
          <div className="pc-healthbadges">
            <StatusBadge label={health.label} tone={health.tone} glyph={health.glyph} />
            {healthTrend && (
              <StatusBadge
                label={healthTrend.label}
                tone={healthTrend.tone}
                glyph={healthTrend.glyph}
              />
            )}
          </div>

          <Async query={assessment} loadingLabel="טוען את הבדיקה…">
            {assessment.data && (
              <>
                {/* Two of each, as on the בריאות list. The database already orders
                    issues by severity and recommendations by priority, so the top of
                    each is the top of each — not a summary written here. */}
                <HealthInsight
                  issues={assessment.data.possible_issues.slice(0, 2)}
                  recommendations={assessment.data.recommendations
                    .slice(0, 2)
                    .map((recommendation) => recommendation.recommendation_text)}
                  unreadable={assessment.data.overall_status === 'UNKNOWN'}
                  reason={assessment.data.insufficient_information_reason}
                />
                <AssessedPill
                  at={assessment.data.created_at}
                  onOpen={() => setOpenAssessment(assessment.data.id)}
                />
              </>
            )}
          </Async>

          <PastChecks entries={past} onOpen={setOpenAssessment} />

          {adjustment.error && (
            <p className="pc-formerror" role="alert">
              {adjustment.error instanceof ApiError
                ? adjustment.error.message
                : 'לא הצלחנו להכין הצעה.'}
            </p>
          )}
          {adjustment.isSuccess && (
            <p className="pc-formnotice" role="status">
              מכינים הצעה לעדכון התוכנית. היא תופיע כאן כשתהיה מוכנה.
            </p>
          )}
        </div>
      ) : (
        !running && <p className="pc-placeholder-note">עדיין לא בוצעה בדיקת בריאות לצמח הזה.</p>
      )}

      {openAssessment && (
        <HealthAssessmentDialog
          assessmentId={openAssessment}
          onClose={() => setOpenAssessment(null)}
          /* §16: the Health Agent cannot change the plan, so this raises a proposal.
             Offered only on the latest check and only when there is a plan to revisit —
             acting on a superseded assessment, or queueing a second competing
             INITIAL_PLAN, are both worse than not offering it. */
          onAdjustPlan={
            canEdit && plant.care_plan && openAssessment === plant.health.latest_assessment_id
              ? (assessmentId) => adjustment.mutate(assessmentId)
              : undefined
          }
          adjusting={adjustment.isPending}
        />
      )}
    </section>
  )
}

/* --- environment ----------------------------------------------------------- */

function EnvironmentSection({ plantId, plant }: { plantId: string; plant: Dashboard }) {
  const save = useSaveEnvironment(plantId)
  const requestReview = useRequestProposal(plantId)
  const [reviewing, setReviewing] = useState(false)

  return (
    <>
      <EnvironmentForm
        environment={plant.environment}
        saving={save.isPending}
        error={save.error}
        onSave={(values) =>
          save.mutate(values, {
            onSuccess: () => {
              /* Section 12: an environment change produces a proposal, never a silent
                 rewrite — and only when there is a plan to review. Queueing one for a
                 plant with no care plan yet would put a second, competing INITIAL_PLAN
                 in front of the user. */
              if (!plant.care_plan) return
              setReviewing(true)
              requestReview.mutate('ENVIRONMENT_CHANGE', {
                onSettled: () => setReviewing(false),
              })
            },
          })
        }
      />

      {save.isSuccess && !reviewing && (
        <p className="pc-formnotice" role="status">
          {requestReview.isError
            ? /* The conditions are saved either way, and saying otherwise would send the
                 user back to re-enter something that is already stored. */
              'תנאי הגידול נשמרו. לא הצלחנו להתחיל בדיקה של תוכנית הטיפול כרגע.'
            : requestReview.isSuccess
              ? 'תנאי הגידול נשמרו. בודקים אם צריך לעדכן את תוכנית הטיפול.'
              : 'תנאי הגידול נשמרו.'}
        </p>
      )}
    </>
  )
}

/* --- history --------------------------------------------------------------- */

function HistorySection({ plantId, canEdit }: { plantId: string; canEdit: boolean }) {
  const [open, setOpen] = useState(false)
  const [limit, setLimit] = useState(HISTORY_PAGE)
  const query = usePlantHistory(plantId, limit, open)
  const entries = query.data ?? []

  return (
    <section>
      <div className="pc-sectionhead">
        <h2>היסטוריה</h2>
      </div>

      {canEdit && <LogEvent plantId={plantId} />}

      {!open ? (
        <button
          type="button"
          className="pc-btn pc-btn-quiet pc-btn-block"
          onClick={() => setOpen(true)}
        >
          הצגת היומן
        </button>
      ) : (
        <Async query={query} loadingLabel="טוען היסטוריה…">
          <>
            <Timeline entries={entries} />
            {entries.length >= limit && (
              <p className="pc-archivetoggle">
                <button
                  type="button"
                  className="pc-linkbtn"
                  onClick={() => setLimit((current) => current + HISTORY_PAGE)}
                >
                  טעינת עוד
                </button>
              </p>
            )}
          </>
        </Async>
      )}
    </section>
  )
}

/**
 * Record something the user did out of band (FINAL section 19).
 *
 * Repotting a plant on a whim is still part of its history, and the care plan should not
 * have to have asked for it first. Restricted to the four kinds section 19 names as
 * user-created — the rest are written by the actions that cause them, and the endpoint
 * refuses anything else.
 */
function LogEvent({ plantId }: { plantId: string }) {
  const [eventType, setEventType] = useState(LOGGABLE_EVENTS[0][0])
  const [note, setNote] = useState('')
  const log = useLogHistoryEvent(plantId)

  // A custom note with nothing in it is an empty timeline row. The server refuses it
  // too; disabling says so before the round trip.
  const blocked = eventType === 'CUSTOM_NOTE' && !note.trim()

  return (
    <details className="pc-reco pc-detailsblock">
      <summary>רישום פעולה שביצעת</summary>
      <p className="pc-placeholder-note">
        דברים שעשית מחוץ לתוכנית — הם עדיין חלק מההיסטוריה של הצמח.
      </p>

      <form
        onSubmit={(event) => {
          event.preventDefault()
          log.mutate(
            { event_type: eventType, note: note.trim() || null },
            { onSuccess: () => setNote('') },
          )
        }}
      >
        <label className="pc-field">
          <span>מה קרה?</span>
          <select value={eventType} onChange={(event) => setEventType(event.target.value)}>
            {LOGGABLE_EVENTS.map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </select>
        </label>

        <label className="pc-field">
          <span>הערה</span>
          <input
            type="text"
            maxLength={1000}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>

        {log.error && (
          <p className="pc-formerror" role="alert">
            {log.error instanceof ApiError ? log.error.message : 'הרישום לא נשמר.'}
          </p>
        )}
        {log.isSuccess && (
          <p className="pc-formnotice" role="status">
            נרשם בהיסטוריה.
          </p>
        )}

        <button type="submit" className="pc-btn" disabled={blocked || log.isPending}>
          {log.isPending ? 'רושמים…' : 'רישום'}
        </button>
      </form>
    </details>
  )
}
