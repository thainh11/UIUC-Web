import type { MonthCount } from '../api/types'

const INT = new Intl.NumberFormat('en-US')
export const formatInt = (n: number) => INT.format(n)
export const formatPercent = (share: number) => `${Math.round(share * 100)}%`

const MONTH = new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })
const DAY = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })

/** `YYYY-MM` or `YYYY-MM-DD` to a readable label, always in UTC so the day never shifts. */
export function formatMonth(iso: string): string {
  return MONTH.format(new Date(`${iso.slice(0, 7)}-01T00:00:00Z`))
}
export const formatDay = (iso: string) => DAY.format(new Date(`${iso}T00:00:00Z`))

export function formatWindow(firstDate: string, lastDate: string): string {
  return `${formatMonth(firstDate)} – ${formatMonth(lastDate)}`
}

/** Two letters for the placeholder avatar: first and last word of the name. */
export function initials(name: string): string {
  const words = name.split(/[\s,]+/).filter((w) => /\p{L}/u.test(w))
  if (words.length === 0) return '?'
  const first = words[0]![0]!
  const last = words.length > 1 ? words[words.length - 1]![0]! : ''
  return (first + last).toUpperCase()
}

/** The Experts "no portrait" image is a placeholder, not a photo. */
export function realPhotoUrl(url: string | null): string | null {
  return url && !/no-portrait/i.test(url) ? url : null
}

export type ChartPoint = {
  month: string
  /** Papers with a real month: the API count minus the year-only dates. */
  count: number
  /** Papers dated 1 January, i.e. a publication year without a month; left off the line. */
  yearOnly: number
  partial: boolean
  /** Per-series values so the first and last (partial) months render dashed, joined to the solid line. */
  solid: number | null
  dashStart: number | null
  dashEnd: number | null
}

const dated = (m: MonthCount) => m.count - m.year_only

export const yearOnlyTotal = (months: MonthCount[]) => months.reduce((sum, m) => sum + m.year_only, 0)

/**
 * The first and last months of the rolling window are partial. Mark them and split the line so the
 * dashed segments stop them reading as a real drop in output. Year-only dates (stored as 1 January)
 * are left off the line, otherwise every January reads as a spike.
 */
export function toChartPoints(months: MonthCount[]): ChartPoint[] {
  const last = months.length - 1
  return months.map((m, i) => {
    const partial = i === 0 || i === last
    const count = dated(m)
    return {
      month: m.month,
      count,
      yearOnly: m.year_only,
      partial,
      solid: i >= 1 && i <= last - 1 ? count : null,
      dashStart: i <= 1 ? count : null,
      dashEnd: i >= last - 1 ? count : null,
    }
  })
}

export function trendSummary(months: MonthCount[]): string {
  if (months.length < 3) return ''
  const full = months.slice(1, -1)
  const peak = full.reduce((a, b) => (dated(b) > dated(a) ? b : a))
  const lo = full.reduce((a, b) => (dated(b) < dated(a) ? b : a))
  const yearOnly = yearOnlyTotal(months)
  return (
    `Papers per month, ${formatMonth(months[0]!.month)} to ${formatMonth(months[months.length - 1]!.month)}. ` +
    `Highest full month: ${formatMonth(peak.month)} (${formatInt(dated(peak))}). ` +
    `Lowest: ${formatMonth(lo.month)} (${formatInt(dated(lo))}). ` +
    `The first and last months are partial.` +
    (yearOnly > 0 ? ` ${formatInt(yearOnly)} papers with only a publication year are not plotted.` : '')
  )
}
