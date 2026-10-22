import { useMemo, useState } from 'react'
import { useProblems } from '../api/queries.ts'
import type { CatalogProblem } from '../api/types.ts'
import { ErrorNote } from '../components/ErrorNote.tsx'
import { ProblemInfo } from '../components/ProblemInfo.tsx'
import { ResultButtons } from '../components/ResultButtons.tsx'
import { shortDay } from '../time.ts'

function statusLabel(problem: CatalogProblem): string {
  if (problem.status === 'new') return 'New'
  if (problem.status === 'due') return 'Due'
  return `Next ${shortDay(problem.due_date ?? '')}`
}

function byTopic(problems: CatalogProblem[]): [string, CatalogProblem[]][] {
  const groups = new Map<string, CatalogProblem[]>()
  for (const problem of problems) {
    groups.set(problem.topic, [...(groups.get(problem.topic) ?? []), problem])
  }
  return [...groups]
}

export function CatalogPage() {
  const problems = useProblems()
  const [search, setSearch] = useState('')
  const [topic, setTopic] = useState('')

  const all = useMemo(() => problems.data ?? [], [problems.data])
  const topics = useMemo(() => [...new Set(all.map((problem) => problem.topic))], [all])
  const groups = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return byTopic(
      all.filter(
        (problem) =>
          (!topic || problem.topic === topic) &&
          (!needle || problem.title.toLowerCase().includes(needle)),
      ),
    )
  }, [all, search, topic])

  if (problems.isPending) return <p className="muted">Loading the catalog…</p>
  if (problems.isError) return <ErrorNote error={problems.error} />

  const practiced = all.filter((problem) => problem.status !== 'new').length
  return (
    <section>
      <header className="page-head">
        <h1>Catalog</h1>
        <p className="muted">
          NeetCode 150 · {practiced} of {all.length} practiced
        </p>
      </header>

      <div className="filters">
        <input
          type="search"
          placeholder="Search problems"
          aria-label="Search problems"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select aria-label="Topic" value={topic} onChange={(event) => setTopic(event.target.value)}>
          <option value="">All topics</option>
          {topics.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>

      {groups.length === 0 && <p className="empty muted">No problems match.</p>}
      {groups.map(([name, items]) => (
        <section key={name} className="topic">
          <h2>
            {name}{' '}
            <span className="muted">
              {items.filter((problem) => problem.status !== 'new').length}/{items.length}
            </span>
          </h2>
          <ul className="problem-list">
            {items.map((problem) => (
              <li key={problem.id} className="problem-row">
                <ProblemInfo
                  problem={problem}
                  detail={
                    <span className={`status status-${problem.status}`}>
                      {statusLabel(problem)}
                    </span>
                  }
                />
                <ResultButtons problemId={problem.id} title={problem.title} />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </section>
  )
}
