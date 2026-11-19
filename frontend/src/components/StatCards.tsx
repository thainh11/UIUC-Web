import { getOverview } from '../api/client'
import { useResource } from '../hooks/useResource'
import { formatInt, formatPercent, formatWindow } from '../lib/format'
import { ErrorBlock, Skeleton } from './states'

const CARD = 'card p-4'

export function StatCards() {
  const { data, error, reload } = useResource(getOverview, [])

  if (error) return <ErrorBlock message="Could not load the summary numbers." onRetry={reload} />

  const cards = data && [
    { label: 'Papers', value: formatInt(data.papers), note: formatWindow(data.first_date, data.last_date) },
    { label: 'UIUC author profiles', value: formatInt(data.uiuc_authors), note: formatWindow(data.first_date, data.last_date) },
    { label: 'Citations', value: formatInt(data.citations), note: `To these papers, ${formatWindow(data.first_date, data.last_date)}` },
    { label: 'Open access', value: formatPercent(data.open_access_share), note: `Share of papers, ${formatWindow(data.first_date, data.last_date)}` },
    { label: 'Faculty', value: formatInt(data.faculty), note: `${formatInt(data.linked_faculty)} with linked papers` },
  ]

  return (
    <ul aria-busy={!data} className="m-0 grid list-none grid-cols-2 gap-3 p-0 md:grid-cols-3 lg:grid-cols-5">
      {(cards ?? Array.from({ length: 5 })).map((c, i) =>
        c ? (
          <li key={c.label} className={`${CARD} fade-in ${i === 4 ? 'col-span-2 md:col-span-1' : ''}`}>
            <p className="text-muted-fg m-0 text-sm font-bold">{c.label}</p>
            <p className="num text-primary m-0 mt-1 font-serif text-4xl font-medium">{c.value}</p>
            <p className="text-muted-fg m-0 mt-1 text-sm">{c.note}</p>
          </li>
        ) : (
          <li key={i} className={`${CARD} ${i === 4 ? 'col-span-2 md:col-span-1' : ''}`}>
            <Skeleton className="h-4 w-20" />
            <Skeleton className="mt-2 h-9 w-28" />
            <Skeleton className="mt-2 h-4 w-32" />
          </li>
        ),
      )}
    </ul>
  )
}
