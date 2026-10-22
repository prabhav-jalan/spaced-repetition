import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { browserTimeZone } from '../time.ts'
import { request } from './client.ts'
import type { CatalogProblem, LoggedAttempt, Me, MeChanges, Result, Today } from './types.ts'

const keys = {
  me: ['me'],
  today: ['reviews', 'today'],
  problems: ['problems'],
} as const

export function useMe() {
  return useQuery({ queryKey: keys.me, queryFn: () => request<Me>('GET', '/me') })
}

export function useToday() {
  return useQuery({ queryKey: keys.today, queryFn: () => request<Today>('GET', '/reviews/today') })
}

export function useProblems() {
  return useQuery({
    queryKey: keys.problems,
    queryFn: () => request<CatalogProblem[]>('GET', '/problems'),
  })
}

export function useLogAttempt() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ problemId, result }: { problemId: number; result: Result }) =>
      request<LoggedAttempt>('POST', '/attempts', { problem_id: problemId, result }),
    onSuccess: () => queryClient.invalidateQueries(),
  })
}

export function useUpdateMe() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (changes: MeChanges) => request<Me>('PATCH', '/me', changes),
    onSuccess: async (me) => {
      queryClient.setQueryData(keys.me, me)
      await queryClient.invalidateQueries({ queryKey: keys.today })
      await queryClient.invalidateQueries({ queryKey: keys.problems })
    },
  })
}

export function useDevSignIn() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (email: string) =>
      request<Me>('POST', '/dev/login', { email, timezone: browserTimeZone() }),
    onSuccess: (me) => {
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== keys.me[0] })
      queryClient.setQueryData(keys.me, me)
    },
  })
}

export function useSignOut() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => request<void>('POST', '/logout'),
    onSuccess: () => queryClient.resetQueries(),
  })
}
