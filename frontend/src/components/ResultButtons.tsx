import { useLogAttempt } from '../api/queries.ts'
import type { Result } from '../api/types.ts'
import { shortDay } from '../time.ts'

const BUTTONS: { result: Result; label: string }[] = [
  { result: 'easy', label: 'Easy' },
  { result: 'struggled', label: 'Struggled' },
  { result: 'failed', label: 'Failed' },
]

export function ResultButtons({ problemId, title }: { problemId: number; title: string }) {
  const logAttempt = useLogAttempt()
  const logged = logAttempt.data

  return (
    <div className="result-area">
      <div className="result-buttons" role="group" aria-label={`How did ${title} go?`}>
        {BUTTONS.map(({ result, label }) => (
          <button
            key={result}
            type="button"
            className={`result result-${result}`}
            disabled={logAttempt.isPending}
            onClick={() => logAttempt.mutate({ problemId, result })}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="result-note" aria-live="polite">
        {logAttempt.isError && <span className="error">{logAttempt.error.message}</span>}
        {logged &&
          (logged.rescheduled
            ? `Next review ${shortDay(logged.due_date)}`
            : `Logged. Already scheduled today for ${shortDay(logged.due_date)}`)}
      </p>
    </div>
  )
}
