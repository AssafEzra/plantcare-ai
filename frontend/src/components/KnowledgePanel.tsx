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
        sections.map(([label, text]) => <Section key={label} label={label} text={text ?? ''} />)
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

/**
 * One heading, its first sentence, and the rest behind a disclosure.
 *
 * Seven sections of three or four paragraphs each is a document, and it was set out in
 * full on a page that already carries the plant's photographs, its tasks, its plan and
 * its last health check. The opening sentence of each is what a reader scans for —
 * "bright indirect light", "every seven to ten days" — and the rest is there the moment
 * they want it, the same way the source list already works.
 *
 * Nothing is summarised or rewritten: the split is the text's own first sentence
 * boundary. Where there is no second sentence the disclosure is simply absent.
 */
function Section({ label, text }: { label: string; text: string }) {
  const [first, rest] = splitFirstSentence(text)

  return (
    <section className="pc-knowledgesection">
      <h4>{label}</h4>
      <p>{first}</p>
      {rest && (
        <details className="pc-reco">
          <summary>להרחבה</summary>
          <p>{rest}</p>
        </details>
      )}
    </section>
  )
}

/**
 * Split on the first sentence end.
 *
 * `.`, `!`, `?` or `׃` followed by whitespace. The whitespace is what excludes a
 * decimal: the point inside "5.5" is followed by a digit, never by a space, so "pH של
 * 5.5–6.5. תערובת מומלצת…" splits where a reader would and "15.5 מעלות" does not split
 * at all. A first sentence shorter than twenty characters is more likely a stray full
 * stop than a sentence, so the text is left whole.
 */
function splitFirstSentence(text: string): [string, string | null] {
  const trimmed = text.trim()
  const match = /[.!?׃](?=\s)/.exec(trimmed)
  if (!match) return [trimmed, null]

  const cut = match.index + 1
  const first = trimmed.slice(0, cut).trim()
  const rest = trimmed.slice(cut).trim()
  if (!rest || first.length < 20) return [trimmed, null]
  return [first, rest]
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
