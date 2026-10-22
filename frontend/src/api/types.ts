export type Result = 'easy' | 'struggled' | 'failed'
export type Difficulty = 'easy' | 'medium' | 'hard'
export type Status = 'new' | 'scheduled' | 'due'

export interface Problem {
  id: number
  slug: string
  title: string
  url: string
  difficulty: Difficulty
  topic: string
}

export interface CatalogProblem extends Problem {
  status: Status
  due_date: string | null
}

export interface Review {
  problem: Problem
  due_date: string
  days_overdue: number
}

export interface Today {
  local_date: string
  reviews: Review[]
}

export interface Me {
  id: number
  email: string
  display_name: string
  timezone: string
  email_enabled: boolean
  local_date: string
  totals: { attempts: number; problems: number; due_today: number }
}

export interface LoggedAttempt {
  id: number
  problem_id: number
  result: Result
  local_date: string
  was_due: boolean
  rescheduled: boolean
  due_date: string
  interval_days: number
}

export type MeChanges = Partial<Pick<Me, 'timezone' | 'email_enabled'>>
