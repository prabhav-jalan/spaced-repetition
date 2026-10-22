export function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone
}

export function allTimeZones(): string[] {
  return Intl.supportedValuesOf('timeZone')
}

function calendarDate(isoDate: string): Date {
  const [year, month, day] = isoDate.split('-').map(Number)
  return new Date(year, month - 1, day)
}

export function longDay(isoDate: string): string {
  return calendarDate(isoDate).toLocaleDateString(undefined, {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  })
}

export function shortDay(isoDate: string): string {
  return calendarDate(isoDate).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function overdueLabel(daysOverdue: number): string {
  if (daysOverdue === 0) return 'Due today'
  return daysOverdue === 1 ? '1 day overdue' : `${daysOverdue} days overdue`
}
