/* Add plant: photographs, identification, confirmation (FINAL section 8).
 *
 * Section 15: adding a plant ALWAYS goes through the identification agent. There is
 * no manual species picker, and the description is context only — "I think this is a
 * Monstera" is a hint, never a verified fact.
 *
 * The failure branch is the one to read carefully. A run that fails says nothing
 * about the photographs: it cannot know they were the problem, and on the common
 * failure (the vendor refusing) nothing ever looked at them. That distinction is why
 * the previous version told a user their photographs were inadequate after a 429.
 * Only a NEEDS_MORE_INFORMATION result — the model looked and could not tell — is
 * allowed to mention photographs, and even then only when `request_more_photos` says
 * more would help.
 */

import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  useStartIdentification,
  useAgentRequest,
  useIdentification,
  useConfirmIdentification,
  STAGES,
} from '../api/identification'
import ImagePicker, { type PickedImage } from '../components/ImagePicker'
import { ApiError } from '../lib/errors'
import './AddPlant.css'

type Step = 'upload' | 'identifying' | 'confirm' | 'done'

export default function AddPlant() {
  const [step, setStep] = useState<Step>('upload')
  const [images, setImages] = useState<PickedImage[]>([])
  const [note, setNote] = useState('')
  const [plantId, setPlantId] = useState<string | null>(null)
  const [requestId, setRequestId] = useState<string | null>(null)
  const [identificationId, setIdentificationId] = useState<string | null>(null)
  const [knowledgePending, setKnowledgePending] = useState(false)

  function restart() {
    setStep('upload')
    setImages([])
    setNote('')
    setPlantId(null)
    setRequestId(null)
    setIdentificationId(null)
    setKnowledgePending(false)
  }

  return (
    <section className="pc-addplant">
      {step === 'upload' && (
        <UploadStep
          images={images}
          setImages={setImages}
          note={note}
          setNote={setNote}
          onStarted={(result) => {
            setPlantId(result.plantId)
            setRequestId(result.requestId)
            setStep('identifying')
          }}
        />
      )}

      {step === 'identifying' && requestId && (
        <IdentifyingStep
          requestId={requestId}
          onIdentified={(id) => {
            setIdentificationId(id)
            setStep('confirm')
          }}
          onRestart={restart}
        />
      )}

      {step === 'confirm' && identificationId && (
        <ConfirmStep
          identificationId={identificationId}
          onConfirmed={(pending) => {
            setKnowledgePending(pending)
            setStep('done')
          }}
          onRestart={restart}
        />
      )}

      {step === 'done' && <DoneStep plantId={plantId} knowledgePending={knowledgePending} />}
    </section>
  )
}

/* --- step 1 --------------------------------------------------------------- */

function UploadStep({
  images,
  setImages,
  note,
  setNote,
  onStarted,
}: {
  images: PickedImage[]
  setImages: (next: PickedImage[]) => void
  note: string
  setNote: (next: string) => void
  onStarted: (result: { plantId: string; requestId: string }) => void
}) {
  const start = useStartIdentification()

  return (
    <>
      <StepHeader title="הוספת צמח" step={1} />
      <p>צלמו או העלו עד 4 תמונות ברורות של הצמח.</p>

      <details className="pc-tips">
        <summary>איך לצלם תמונה טובה?</summary>
        <ul>
          <li>צלמו לאור יום, בלי פלאש</li>
          <li>כמה עלים שלמים במסגרת</li>
          <li>תמונה אחת מקרוב על עלה בודד עוזרת מאוד</li>
          <li>אם יש פרחים או פירות, שווה לצלם גם אותם</li>
        </ul>
      </details>

      <ImagePicker images={images} onChange={setImages} />

      <label className="pc-field">
        <span>תיאור קצר (אופציונלי)</span>
        <textarea
          rows={3}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="למשל: קיבלתי אותו במתנה, העלים החדשים בהירים יותר"
        />
        <small>אם יש לכם ניחוש מה הצמח, אפשר לכתוב כאן. זה מידע עוזר, לא קביעה.</small>
      </label>

      {start.error && (
        <p className="pc-formerror" role="alert">
          {start.error instanceof ApiError ? start.error.message : 'משהו השתבש. אפשר לנסות שוב.'}
        </p>
      )}

      <button
        type="button"
        className="pc-btn"
        disabled={images.length === 0 || start.isPending}
        onClick={() =>
          start.mutate(
            { files: images.map((i) => i.file), note: note.trim() || null },
            { onSuccess: onStarted },
          )
        }
      >
        {start.isPending ? 'שומרים את התמונות…' : 'המשך לזיהוי'}
      </button>
    </>
  )
}

/* --- step 2 --------------------------------------------------------------- */

function IdentifyingStep({
  requestId,
  onIdentified,
  onRestart,
}: {
  requestId: string
  onIdentified: (identificationId: string) => void
  onRestart: () => void
}) {
  const { data, error } = useAgentRequest(requestId)

  if (data?.status === 'SUCCEEDED') {
    const id = (data.output_summary?.identification_id as string | undefined) ?? null
    if (id) {
      // Render-phase transition is fine here: it runs once, on the poll that settles.
      queueMicrotask(() => onIdentified(id))
    }
  }

  const failed = data?.status === 'FAILED' || data?.status === 'CANCELLED'
  const currentIndex = STAGES.findIndex(([code]) => code === data?.stage)

  return (
    <>
      <StepHeader title="הוספת צמח" step={2} />

      {!failed && <p>מזהים את הצמח שלך…</p>}

      {!failed && (
        <ol className="pc-stages">
          {STAGES.map(([code, label], index) => (
            <li
              key={code}
              className={
                currentIndex > index ? 'is-done' : currentIndex === index ? 'is-current' : ''
              }
            >
              {label}
            </li>
          ))}
        </ol>
      )}

      {error && (
        <p className="pc-formerror" role="alert">
          {error instanceof ApiError ? error.message : 'משהו השתבש.'}
        </p>
      )}

      {failed && (
        <>
          {/* Says nothing about photographs — see the module comment. */}
          {data?.error_code === 'AGENT_UNAVAILABLE' ? (
            <p className="pc-formnotice" role="status">
              שירות הזיהוי עמוס כרגע. אפשר לנסות שוב בעוד כמה דקות.
            </p>
          ) : (
            <p className="pc-formerror" role="alert">
              הזיהוי לא הושלם. אפשר לנסות שוב.
            </p>
          )}
          {/* Starting over, not retrying: a failed identification archives its
              plant, so there is no row left to run a second attempt against. */}
          <button type="button" className="pc-btn" onClick={onRestart}>
            התחלה מחדש
          </button>
        </>
      )}
    </>
  )
}

/* --- step 3 --------------------------------------------------------------- */

function ConfirmStep({
  identificationId,
  onConfirmed,
  onRestart,
}: {
  identificationId: string
  onConfirmed: (knowledgePending: boolean) => void
  onRestart: () => void
}) {
  const { data, isPending, error } = useIdentification(identificationId)
  const confirm = useConfirmIdentification(identificationId)
  const [selected, setSelected] = useState<string | null>(null)
  const [name, setName] = useState('')

  if (isPending) {
    return (
      <div className="pc-async" role="status">
        <span className="pc-spinner" aria-hidden="true" />
        <span>טוען…</span>
      </div>
    )
  }

  if (error || !data) {
    return (
      <>
        <p className="pc-formerror" role="alert">
          {error instanceof ApiError ? error.message : 'לא נמצאה תוצאת זיהוי.'}
        </p>
        <button type="button" className="pc-btn" onClick={onRestart}>
          התחלה מחדש
        </button>
      </>
    )
  }

  /* The model looked and could not tell. A FAILED run never reaches this step, so
     its own account of what was missing is worth showing, and asking for
     photographs is honest here — but only when it says they would help. */
  if (data.status !== 'SUCCESS' || data.candidates.length === 0) {
    return (
      <>
        <StepHeader title="לא הצלחנו לזהות" step={3} />
        <p className="pc-formnotice" role="status">
          {data.insufficient_reason || 'לא הצלחנו לזהות את הצמח מהתמונות האלה.'}
        </p>
        {data.request_more_photos && <p className="pc-placeholder-note">תמונות נוספות או ברורות יותר יעזרו.</p>}
        <button type="button" className="pc-btn" onClick={onRestart}>
          {data.request_more_photos ? 'העלאת תמונות אחרות' : 'התחלה מחדש'}
        </button>
      </>
    )
  }

  const candidates = [...data.candidates].sort((a, b) => a.rank - b.rank)
  const chosen = selected ?? candidates[0].id
  const chosenCandidate = candidates.find((c) => c.id === chosen)!

  return (
    <>
      <StepHeader title="הזיהוי הושלם" step={3} />

      {data.confidence_level && (
        <p className="pc-confidence">
          רמת ודאות: <strong>{CONFIDENCE[data.confidence_level]}</strong>
        </p>
      )}

      <ul className="pc-candidates">
        {candidates.map((candidate) => (
          <li key={candidate.id}>
            <label className={`pc-candidate${chosen === candidate.id ? ' is-chosen' : ''}`}>
              <input
                type="radio"
                name="candidate"
                checked={chosen === candidate.id}
                onChange={() => setSelected(candidate.id)}
              />
              <span className="pc-candidatebody">
                <span className="pc-candidatename">
                  {candidate.common_name || candidate.scientific_name}
                </span>
                <span className="pc-candidatesci pc-ltr">{candidate.scientific_name}</span>
              </span>
              {candidate.confidence_score !== null && (
                <span className="pc-candidatescore pc-num">
                  {Math.round(candidate.confidence_score * 100)}%
                </span>
              )}
            </label>
          </li>
        ))}
      </ul>

      {data.wikipedia_url && (
        <p>
          <a href={data.wikipedia_url} target="_blank" rel="noopener noreferrer">
            מידע נוסף על {chosenCandidate.common_name || chosenCandidate.scientific_name}
          </a>
        </p>
      )}

      {/* Section 18: the personal name is asked for after the species is settled,
          it is optional, and it defaults to the common name. */}
      <label className="pc-field">
        <span>שם אישי לצמח (אופציונלי)</span>
        <input
          type="text"
          maxLength={120}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={chosenCandidate.common_name || chosenCandidate.scientific_name}
        />
      </label>

      {confirm.error && (
        <p className="pc-formerror" role="alert">
          {confirm.error instanceof ApiError ? confirm.error.message : 'משהו השתבש.'}
        </p>
      )}

      <div className="pc-actionrow">
        <button
          type="button"
          className="pc-btn"
          disabled={confirm.isPending}
          onClick={() =>
            confirm.mutate(
              { candidateId: chosen, name: name.trim() || null },
              { onSuccess: (result) => onConfirmed(Boolean(result.knowledge_pending)) },
            )
          }
        >
          {confirm.isPending ? 'מאשרים…' : 'אישור והוספת הצמח'}
        </button>
        <button type="button" className="pc-btn pc-btn-quiet" onClick={onRestart}>
          לא אף אחד מאלה
        </button>
      </div>
    </>
  )
}

const CONFIDENCE: Record<string, string> = {
  HIGH: 'גבוהה',
  MEDIUM: 'בינונית',
  LOW: 'נמוכה',
}

/* --- done ----------------------------------------------------------------- */

function DoneStep({
  plantId,
  knowledgePending,
}: {
  plantId: string | null
  knowledgePending: boolean
}) {
  const navigate = useNavigate()

  return (
    <>
      <StepHeader title={knowledgePending ? 'כמעט סיימנו' : 'הצמח נוסף'} />

      {knowledgePending ? (
        <>
          <p>זיהינו את הצמח שלך ומכינים עבורו מידע מקצועי.</p>
          <ol className="pc-stages">
            <li className="is-done">הזיהוי אושר</li>
            <li className="is-done">הצמח נוסף</li>
            <li className="is-current">הכנת מידע מקצועי</li>
            <li>אישור מידע</li>
          </ol>
          <p className="pc-formnotice" role="status">
            אפשר להמשיך להשתמש באפליקציה. נעדכן כשהמידע יהיה מוכן.
          </p>
        </>
      ) : (
        <p className="pc-formnotice" role="status">
          הזיהוי אושר והצמח מוכן.
        </p>
      )}

      <div className="pc-actionrow">
        <button
          type="button"
          className="pc-btn"
          onClick={() => navigate(plantId ? `/plants/${plantId}` : '/plants')}
        >
          לצמח שלי
        </button>
        <Link to="/plants" className="pc-btn pc-btn-quiet">
          לרשימת הצמחים
        </Link>
      </div>
    </>
  )
}

function StepHeader({ title, step }: { title: string; step?: number }) {
  return (
    <header className="pc-stephead">
      <h1>{title}</h1>
      {step && (
        <p className="pc-placeholder-note">
          שלב <span className="pc-num">{step}</span> מתוך <span className="pc-num">3</span>
        </p>
      )}
    </header>
  )
}
