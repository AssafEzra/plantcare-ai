/* Phase 2 placeholder.
 *
 * The shell, routing, RTL and design system are what phase 2 delivers; the flows
 * themselves are phase 5. Each route renders this so the navigation is genuinely
 * walkable now — and so nothing here can be mistaken for a migrated screen.
 */

export default function Placeholder({
  title,
  note,
}: {
  title: string
  note?: string
}) {
  return (
    <section className="pc-placeholder">
      <h1>{title}</h1>
      <p className="pc-placeholder-note">
        {note ?? 'המסך הזה יועבר בשלב 5 של המיגרציה.'}
      </p>
    </section>
  )
}
