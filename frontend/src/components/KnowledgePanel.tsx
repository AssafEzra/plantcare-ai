/* The professional information about a species, and where it came from.
 *
 * Two halves that used to be separated by an accident of where the code lived. The
 * prose reached users; the source list lived inside the admin panel, so only an
 * administrator ever saw it — even though `GET /v1/species/{id}/knowledge` has always
 * returned `sources` to everyone and its own docstring says "what a user sees: the
 * current version *and where it came from*".
 *
 * That matters more here than in an admin screen. The whole point of the deterministic
 * source verification is that a reader can tell a fetched, approved page from something
 * the model asserted; hiding the distinction leaves them trusting all of it equally,
 * which is the opposite of what the machinery was built for.
 *
 * FINAL section 10: users report errors; they never edit. There is no input on this
 * panel except the report.
 */

import { useState } from 'react'
import {
  isNotPrepared,
  readSection,
  useKnowledge,
  useReportKnowledgeError,
  type Knowledge,
} from '../api/knowledge'
import { KNOWLEDGE_SECTIONS, SOURCE_CLASS_LABELS, SOURCE_CLASS_ORDER } from '../lib/careVocab'
import { ApiError } from '../lib/errors'
import type { Tone } from '../lib/status'
import StatusBadge from './StatusBadge'
import './KnowledgePanel.css'

export default function KnowledgePanel({
  speciesId,
  plantId,
}: {
  speciesId: string
  plantId: string
}) {
  const query = useKnowledge(speciesId)

  if (query.isPending) {
    return (
      <p className="pc-placeholder-note" role="status">
        טוען…
      </p>
    )
  }

  // A 404 is an ordinary outcome: research may still be running. Not an error state.
  if (isNotPrepared(query.error)) {
    return <p className="pc-placeholder-note">המידע המקצועי עדיין בהכנה.</p>
  }

  if (query.error || !query.data) {
    return (
      <p className="pc-formerror" role="alert">
        {query.error instanceof ApiError ? query.error.message : 'לא הצלחנו לטעון את המידע.'}
      </p>
    )
  }

  return <Article knowledge={query.data} speciesId={speciesId} plantId={plantId} />
}

function Article({
  knowledge,
  speciesId,
  plantId,
}: {
  knowledge: Knowledge
  speciesId: string
  plantId: string
}) {
  const provisional = knowledge.review === 'pending'
  const sections = KNOWLEDGE_SECTIONS.map(
    ([name, label]) => [label, readSection(knowledge.content, name)] as const,
  ).filter(([, text]) => text)

  return (
    <div className="pc-knowledge">
      {provisional && (
        /* The plant no longer waits for review before it gets knowledge and a plan.
           That is only honest if the page says what the user is reading. */
        <p className="pc-formnotice" role="status">
          המידע הזה נוצר על ידי הסוכן וממתין לאישור מומחה. ייתכנו בו אי-דיוקים, והוא עשוי
          להשתנות אחרי הבדיקה.
        </p>
      )}

      {sections.length === 0 ? (
        /* An empty box reads as a broken page. Saying so is worse news and better
           information. */
        <p className="pc-placeholder-note">המידע המקצועי אינו זמין להצגה כרגע.</p>
      ) : (
        sections.map(([label, text]) => (
          <section key={label} className="pc-knowledgesection">
            <h4>{label}</h4>
            <p>{text}</p>
          </section>
        ))
      )}

      {provisional ? (
        /* No version number, because there is no published version yet, and no source
           list, because verification is part of the review this has not had. Claiming
           either would be the overclaiming the notice above exists to prevent. */
        <p className="pc-placeholder-note">
          נוצר <span className="pc-num">{knowledge.published_at.slice(0, 10)}</span> · ממתין
          לאישור
        </p>
      ) : (
        <>
          <p className="pc-placeholder-note">
            גרסה <span className="pc-num">{knowledge.version_number}</span> · פורסם{' '}
            <span className="pc-num">{knowledge.published_at.slice(0, 10)}</span>
          </p>
          <details className="pc-reco">
            <summary>
              מקורות (<span className="pc-num">{knowledge.sources.length}</span>)
            </summary>
            <Sources sources={knowledge.sources} />
          </details>
        </>
      )}

      <ReportForm speciesId={speciesId} plantId={plantId} />
    </div>
  )
}

function Sources({ sources }: { sources: Knowledge['sources'] }) {
  if (!sources.length) return <p className="pc-placeholder-note">לא צורפו מקורות.</p>

  /* Worst first, deliberately. A reader needs to see what is *not* backed by a fetched
     page before the text resting on it. */
  const ordered = [...sources].sort(
    (a, b) =>
      (SOURCE_CLASS_ORDER[a.source_class] ?? 9) - (SOURCE_CLASS_ORDER[b.source_class] ?? 9),
  )

  return (
    <ul className="pc-sources">
      {ordered.map((source) => {
        const badge = SOURCE_CLASS_LABELS[source.source_class]
        return (
          <li key={source.id} className="pc-source">
            {badge ? (
              <StatusBadge label={badge.label} tone={badge.tone as Tone} glyph="·" />
            ) : (
              <StatusBadge label={source.source_class} tone="neutral" glyph="·" />
            )}
            {source.title && <p className="pc-sourcetitle">{source.title}</p>}
            {source.publisher && <p className="pc-placeholder-note">{source.publisher}</p>}
            {source.url && (
              <a href={source.url} target="_blank" rel="noopener noreferrer">
                פתיחת המקור
              </a>
            )}
            {source.notes && <p className="pc-placeholder-note">{source.notes}</p>}
          </li>
        )
      })}
    </ul>
  )
}

function ReportForm({ speciesId, plantId }: { speciesId: string; plantId: string }) {
  const [text, setText] = useState('')
  const report = useReportKnowledgeError(speciesId)

  if (report.isSuccess) {
    return (
      <p className="pc-formnotice" role="status">
        הדיווח נשלח לבדיקה. תודה.
      </p>
    )
  }

  return (
    <details className="pc-reco">
      <summary>דיווח על טעות במידע</summary>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (text.trim()) report.mutate({ plantId, text: text.trim() })
        }}
      >
        <label className="pc-field">
          <span>מה לא מדויק?</span>
          <textarea
            rows={3}
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="למשל: ההמלצה על ההשקיה אינה מתאימה למין הזה"
          />
        </label>

        {report.error && (
          <p className="pc-formerror" role="alert">
            {report.error instanceof ApiError ? report.error.message : 'הדיווח לא נשלח.'}
          </p>
        )}

        <button type="submit" className="pc-btn" disabled={!text.trim() || report.isPending}>
          {report.isPending ? 'שולחים…' : 'שליחת דיווח'}
        </button>
      </form>
    </details>
  )
}
