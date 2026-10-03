/* One past health check, opened over whatever screen asked for it.
 *
 * The בריאות tab shows a card per plant with the last check's headline on it and a row
 * of earlier dates. Pressing a date has to show that check in full — all of it, not a
 * second summary — and sending the reader to the plant dashboard to find it loses the
 * list they were working through. So the assessment opens here, over the list.
 *
 * The body is `HealthAssessment`, the same component the plant dashboard renders. §16
 * decides how an assessment may be presented — observations and possible issues in
 * different registers, every issue showing its evidence — and a second renderer is a
 * second place for that to go wrong.
 *
 * Fetched when opened, never before. A list of twelve plants with eight checks each is
 * ninety-six assessments, and the reader will look at one.
 */

import { useAssessment } from '../api/health'
import Async from './Async'
import HealthAssessment from './HealthAssessment'
import Modal from './Modal'

export default function HealthAssessmentDialog({
  assessmentId,
  plantName,
  onClose,
}: {
  assessmentId: string
  /** Named in the title: the reader opened this from a list of several plants. */
  plantName?: string | null
  onClose: () => void
}) {
  const query = useAssessment(assessmentId)

  return (
    <Modal title={plantName ? `בדיקת בריאות · ${plantName}` : 'בדיקת בריאות'} onClose={onClose}>
      <Async query={query} loadingLabel="טוען את הבדיקה…">
        {query.data && <HealthAssessment assessment={query.data} />}
      </Async>
    </Modal>
  )
}
