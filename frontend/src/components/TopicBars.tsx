import { Check } from '@phosphor-icons/react'
import { useState, type CSSProperties } from 'react'
import { getFields } from '../api/client'
import { useResource } from '../hooks/useResource'
import { formatInt } from '../lib/format'
import { ErrorBlock, Skeleton } from './states'

const COLLAPSED = 12

type Props = { selected: string | null; onSelect: (field: string | null) => void }

/**
 * Fields as a list of toggle buttons with a proportional bar, not an SVG chart: the bars filter the
 * paper list, so they must be real controls (focusable, `aria-pressed`) with the label in the text.
 */
export function TopicBars({ selected, onSelect }: Props) {
  const { data, error, reload } = useResource(getFields, [])
  const [expanded, setExpanded] = useState(false)

  if (error) return <ErrorBlock message="Could not load the research fields." onRetry={reload} />
  if (!data) {
    return (
      <div aria-busy="true" className="grid gap-4 md:grid-cols-2">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-14" />
        ))}
      </div>
    )
  }

  // A shared link can select a field below the fold; never hide the active filter.
  const selectedIndex = selected ? data.findIndex((f) => f.name === selected) : -1
  const showAll = expanded || selectedIndex >= COLLAPSED
  const items = showAll ? data : data.slice(0, COLLAPSED)
  const max = data[0]?.count ?? 1

  return (
    <div className="fade-in">
      <ul
        className="m-0 grid list-none gap-2 p-0 md:grid-flow-col md:gap-x-6 md:[grid-template-rows:repeat(var(--rows),auto)]"
        style={{ '--rows': Math.ceil(items.length / 2) } as CSSProperties}
      >
        {items.map((f) => {
          const on = f.name === selected
          return (
            <li key={f.name}>
              <button
                type="button"
                aria-pressed={on}
                onClick={() => onSelect(on ? null : f.name)}
                className={`hover:bg-surface block w-full cursor-pointer rounded-lg border-2 p-3 text-left transition-colors ${
                  on ? 'border-primary bg-surface' : 'border-transparent'
                }`}
              >
                <span className="flex items-baseline justify-between gap-3">
                  <span className="text-primary font-bold">
                    {f.name}
                    {on && (
                      <span className="ml-2 inline-flex items-center gap-1 text-sm font-bold">
                        <Check size={16} weight="bold" aria-hidden="true" />
                        Filtering
                      </span>
                    )}
                  </span>
                  <span className="num text-muted-fg shrink-0">{formatInt(f.count)}</span>
                </span>
                <span aria-hidden="true" className="bg-border mt-2 block h-2.5 overflow-hidden rounded-full">
                  <span
                    className={`block h-full rounded-full ${on ? 'bg-accent' : 'bg-primary'}`}
                    style={{ width: `${Math.max(2, (f.count / max) * 100)}%` }}
                  />
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      {data.length > COLLAPSED && !(selectedIndex >= COLLAPSED) && (
        <button type="button" className="btn mt-4" aria-expanded={expanded} onClick={() => setExpanded((e) => !e)}>
          {expanded ? 'Show fewer fields' : `Show all ${data.length} fields`}
        </button>
      )}
    </div>
  )
}
