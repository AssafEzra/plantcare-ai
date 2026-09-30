/* "Is this your plant?", asked on the plant's own page (FINAL section 8).
 *
 * The reason this exists rather than living only in the Add Plant wizard: the
 * confirmation used to be held in wizard state, so a refresh, a closed tab, or a walk
 * away between "analysing" and the result left the identification finished in the
 * database and unanswerable in the interface — the plant's own page said "not
 * identified yet" and offered nothing to press.
 *
 * The confirmation is a property of the plant, not of a wizard step, so it renders
 * wherever the plant is.
 */

import { useState } from 'react'
import {
  useConfirmIdentification,
  useReportWrongIdentification,
} from '../api/identification'
import type { PendingIdentification } from '../api/plantDetail'
import { CONFIDENCE_LABELS } from '../lib/careVocab'
import { ApiError } from '../lib/errors'

export default function IdentificationPrompt({
  plantId,
  pending,
}: {
  plantId: string
  pending: PendingIdentification
}) {
  const candidates = [...pending.candidates].sort((a, b) => a.rank - b.rank)
  const [selected, setSelected] = useState<string | null>(null)
  const [name, setName] = useState('')

  const confirm = useConfirmIdentification(pending.id, plantId)
  const chosen = selected ?? candidates[0]?.id
  const chosenCandidate = candidates.find((candidate) => candidate.id === chosen)

  if (!chosenCandidate) return null

  const lowConfidence = pending.confidence_level === 'LOW'

  return (
    <section className="pc-card">
      <h2>זיהינו את הצמח — האם זה נכון?</h2>

      {pending.confidence_level && (
        <p className="pc-placeholder-note">
          רמת ודאות: {CONFIDENCE_LABELS[pending.confidence_level] ?? pending.confidence_level}
        </p>
      )}

      {lowConfidence && (
        /* Section 8 asks for a low-confidence warning. The user still decides — hiding
           a weak result would leave them with nothing to act on — but they should know
           what they are agreeing to. */
        <p className="pc-formnotice" role="status">
          הזיהוי אינו ודאי. כדאי לבדוק את האפשרויות הנוספות לפני שמאשרים.
        </p>
      )}

      {pending.image_quality && <p className="pc-placeholder-note">{pending.image_quality}</p>}

      <ul className="pc-candidates">
        {candidates.map((candidate, index) => (
          <li key={candidate.id}>
            <label className={`pc-candidate${chosen === candidate.id ? ' is-chosen' : ''}`}>
              <input
                type="radio"
                name={`candidate-${pending.id}`}
                checked={chosen === candidate.id}
                onChange={() => setSelected(candidate.id)}
              />
              <span className="pc-candidatebody">
                <span className="pc-candidatename">
                  {/* The position is not only a tie-breaker: candidates arrive ranked by
                      confidence, so showing it tells the user something true. */}
                  <span className="pc-num">{index + 1}</span>.{' '}
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

      {/* Naming is optional and the API fills it from the candidate's common name when
          it is left empty, so the field is an invitation rather than a gate in front of
          a plant the user has already waited for. */}
      <label className="pc-field">
        <span>איך לקרוא לצמח? (אופציונלי)</span>
        <input
          type="text"
          maxLength={120}
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={chosenCandidate.common_name || chosenCandidate.scientific_name}
        />
      </label>

      {confirm.error ? (
        <p className="pc-formerror" role="alert">
          {confirm.error instanceof ApiError ? confirm.error.message : 'האישור לא נשמר.'}
        </p>
      ) : null}

      <button
        type="button"
        className="pc-btn"
        disabled={confirm.isPending}
        onClick={() =>
          confirm.mutate({ candidateId: chosen, name: name.trim() || null })
        }
      >
        {confirm.isPending ? 'מאשרים…' : 'זה הצמח שלי'}
      </button>

      <WrongReport identificationId={pending.id} plantId={plantId} />
    </section>
  )
}

/**
 * The user can say the model is wrong (A13).
 *
 * It records history and changes nothing — confirmation stays the only thing that moves
 * a plant — so the copy has to be honest that this is a report rather than a correction
 * that takes effect.
 */
function WrongReport({
  identificationId,
  plantId,
}: {
  identificationId: string
  plantId: string
}) {
  const [guess, setGuess] = useState('')
  const [note, setNote] = useState('')
  const report = useReportWrongIdentification(identificationId, plantId)

  if (report.isSuccess) {
    return (
      <p className="pc-formnotice" role="status">
        הדיווח נשמר. אפשר לנסות שוב עם תמונות אחרות.
      </p>
    )
  }

  return (
    <details className="pc-reco">
      <summary>אף אחת מהאפשרויות אינה נכונה</summary>

      <p className="pc-placeholder-note">
        הדיווח נשמר בהיסטוריה של הצמח ומסייע לנו להשתפר. הוא אינו קובע את המין — לשם כך צריך
        לאשר אפשרות או לנסות תמונות אחרות.
      </p>

      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (!guess.trim() && !note.trim()) return
          report.mutate({ scientificName: guess.trim() || null, note: note.trim() || null })
        }}
      >
        <label className="pc-field">
          <span>אם ידוע לך, מה המין?</span>
          <input
            type="text"
            maxLength={200}
            value={guess}
            onChange={(event) => setGuess(event.target.value)}
            placeholder="למשל: Monstera deliciosa"
          />
        </label>

        <label className="pc-field">
          <span>מה לא מתאים?</span>
          <textarea
            rows={3}
            maxLength={1000}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>

        {report.error ? (
          <p className="pc-formerror" role="alert">
            {report.error instanceof ApiError ? report.error.message : 'הדיווח לא נשלח.'}
          </p>
        ) : null}

        <button
          type="submit"
          className="pc-btn pc-btn-quiet"
          disabled={report.isPending || (!guess.trim() && !note.trim())}
        >
          {report.isPending ? 'שולחים…' : 'שליחת דיווח'}
        </button>
      </form>
    </details>
  )
}
