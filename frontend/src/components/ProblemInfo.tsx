import type { ReactNode } from 'react'
import type { Problem } from '../api/types.ts'

export function ProblemInfo({ problem, detail }: { problem: Problem; detail?: ReactNode }) {
  return (
    <div className="problem-info">
      <a className="problem-title" href={problem.url} target="_blank" rel="noreferrer">
        {problem.title}
      </a>
      <div className="problem-meta">
        <span className={`difficulty difficulty-${problem.difficulty}`}>{problem.difficulty}</span>
        <span>{problem.topic}</span>
        {detail}
      </div>
    </div>
  )
}
