import { useMemo } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipContentProps } from 'recharts'
import { getPublicationsByMonth } from '../api/client'
import { useResource } from '../hooks/useResource'
import { formatInt, formatMonth, toChartPoints, trendSummary, yearOnlyTotal, type ChartPoint } from '../lib/format'
import { ErrorBlock, Skeleton } from './states'

const PRIMARY = 'var(--color-primary)'
const MUTED = 'var(--color-muted-fg)'

const shortMonth = (m: string) =>
  new Intl.DateTimeFormat('en-US', { month: 'short', year: '2-digit', timeZone: 'UTC' }).format(new Date(`${m}-01T00:00:00Z`))

function ChartTooltip({ active, payload }: TooltipContentProps) {
  const p = active ? (payload?.[0]?.payload as ChartPoint | undefined) : undefined
  if (!p) return null
  return (
    <div className="card px-3 py-2 text-sm shadow-md">
      <p className="text-primary m-0 font-bold">{formatMonth(p.month)}</p>
      <p className="num m-0">{formatInt(p.count)} papers dated in this month</p>
      {p.yearOnly > 0 && <p className="text-muted-fg m-0">+ {formatInt(p.yearOnly)} with only a year, not plotted</p>}
      {p.partial && <p className="text-muted-fg m-0">Partial month</p>}
    </div>
  )
}

export function PublicationsChart() {
  const { data, error, reload } = useResource(getPublicationsByMonth, [])
  const points = useMemo(() => (data ? toChartPoints(data) : []), [data])

  if (error) return <ErrorBlock message="Could not load the monthly publication counts." onRetry={reload} />
  if (!data) return <Skeleton className="h-[17rem] w-full" />

  const summary = trendSummary(data)
  const yearOnly = yearOnlyTotal(data)
  const first = points[0]
  const last = points[points.length - 1]
  const line = { stroke: PRIMARY, strokeWidth: 2, dot: false, activeDot: { r: 5 }, isAnimationActive: false, connectNulls: false, legendType: 'none' } as const

  return (
    <div className="fade-in">
      <div role="img" aria-label={summary} className="h-[17rem] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 12, right: 16, bottom: 0, left: 0 }} accessibilityLayer={false}>
            <CartesianGrid vertical={false} stroke="var(--color-border)" />
            <XAxis dataKey="month" tickFormatter={shortMonth} minTickGap={28} tick={{ fill: MUTED, fontSize: 13 }} tickLine={false} axisLine={{ stroke: 'var(--color-control-border)' }} />
            <YAxis width={52} tickFormatter={formatInt} tick={{ fill: MUTED, fontSize: 13 }} tickLine={false} axisLine={false} />
            <Tooltip content={ChartTooltip} />
            <Line dataKey="solid" {...line} />
            <Line dataKey="dashStart" {...line} strokeDasharray="5 4" />
            <Line dataKey="dashEnd" {...line} strokeDasharray="5 4" />
            {first && <ReferenceDot x={first.month} y={first.count} r={5} fill="#fff" stroke={PRIMARY} strokeWidth={2} />}
            {last && <ReferenceDot x={last.month} y={last.count} r={5} fill="#fff" stroke={PRIMARY} strokeWidth={2} />}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="text-muted-fg mt-2 mb-0 flex items-center gap-2 text-sm">
        <svg width="28" height="8" aria-hidden="true">
          <line x1="1" y1="4" x2="27" y2="4" stroke={PRIMARY} strokeWidth="2" strokeDasharray="5 4" />
        </svg>
        Dashed ends with open dots: partial months (the window starts and ends mid-month).
      </p>
      {yearOnly > 0 && (
        <p className="text-muted-fg mt-1 mb-0 text-sm">
          {formatInt(yearOnly)} papers are dated 1 January, nearly all because only the publication year is known. They
          count in the totals but are left off the line, so January does not read as a spike.
        </p>
      )}
      <details className="mt-4">
        <summary className="text-primary min-h-11 cursor-pointer py-2 font-bold">Show data table</summary>
        <div className="border-border max-h-72 overflow-auto rounded-lg border">
          <table className="num w-full border-collapse text-left text-sm">
            <caption className="sr-only">Papers per month</caption>
            <thead className="bg-surface sticky top-0">
              <tr>
                <th scope="col" className="p-2">Month</th>
                <th scope="col" className="p-2 text-right">Dated in month</th>
                <th scope="col" className="p-2 text-right">Year only</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.month} className="border-border border-t">
                  <th scope="row" className="p-2 font-normal">
                    {formatMonth(p.month)}
                    {p.partial && <span className="text-muted-fg"> (partial)</span>}
                  </th>
                  <td className="p-2 text-right">{formatInt(p.count)}</td>
                  <td className="p-2 text-right">{p.yearOnly > 0 ? formatInt(p.yearOnly) : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  )
}
