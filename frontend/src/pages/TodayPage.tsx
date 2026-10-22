import { useToday } from '../api/queries.ts'
import { ErrorNote } from '../components/ErrorNote.tsx'
import { ProblemInfo } from '../components/ProblemInfo.tsx'
import { ResultButtons } from '../components/ResultButtons.tsx'
import { Link } from '../router.tsx'
import { longDay, overdueLabel } from '../time.ts'

export function TodayPage() {
  const today = useToday()

  if (today.isPending) return <p className="muted">Loading today's reviews…</p>
  if (today.isError) return <ErrorNote error={today.error} />

  const { local_date: localDate, reviews } = today.data
  return (
    <section>
      <header className="page-head">
        <h1>Today</h1>
        <p className="muted">
          {longDay(localDate)} · {reviews.length === 1 ? '1 review' : `${reviews.length} reviews`}
        </p>
      </header>

      {reviews.length === 0 ? (
        <div className="empty">
          <p>Nothing to review today.</p>
          <p className="muted">
            Rate a problem you've practiced in the <Link to="/catalog">catalog</Link> and it comes
            back here when it's due.
          </p>
        </div>
      ) : (
        <ul className="problem-list">
          {reviews.map(({ problem, days_overdue: daysOverdue }) => (
            <li key={problem.id} className="problem-row">
              <ProblemInfo
                problem={problem}
                detail={
                  <span className={daysOverdue > 0 ? 'overdue' : undefined}>
                    {overdueLabel(daysOverdue)}
                  </span>
                }
              />
              <ResultButtons problemId={problem.id} title={problem.title} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
